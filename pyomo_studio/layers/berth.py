"""Berth allocation layer: discrete berths, continuous start times.

Each vessel uses one berth. Berth service cannot overlap. When another layer
imports ``crude_receipt``, the layer also decides in which periods of the
shared grid each vessel pumps, so tank ullage can slow a discharge and keep
the vessel at the berth longer (demurrage).
"""
from __future__ import annotations

from .base import (CRUDE_RECEIPT, GRADES, PERIODS, Column, Context, Field, Fragment, Grid, Layer, Table,
                   register)


@register
class BerthLayer(Layer):
    type_name = "berth"
    title = "Berth allocation"
    default_id = "berth"
    description = ("Assigns vessels to berths and sets their berthing times. Exports the crude that the "
                   "vessels discharge in each period (port crude_receipt) when a tank layer uses it.")
    fields = [
        Field("hookup_h", "Hook-up time before pumping", "float", 2.0, "Mooring, hoses and checks.", 0, unit="h"),
        Field("release_h", "Release time after pumping", "float", 1.0, "Hoses off and unmooring.", 0, unit="h"),
        Field("first_stage", "Berth plan is a first-stage decision", "bool", True,
              "In a stochastic model, berth and order decisions are then the same in all scenarios."),
    ]
    tables = [
        Table("vessels", "Vessels", [
            Column("name", "Vessel", "text", "V1"),
            Column("grade", "Grade", "grade", ""),
            Column("volume", "Volume", "float", 50000.0, "m3"),
            Column("arrival", "Arrival", "float", 0.0, "h"),
            Column("due", "Due", "float", 24.0, "h"),
            Column("pump_rate", "Pump rate", "float", 5000.0, "m3/h"),
            Column("length", "Length", "float", 250.0, "m"),
            Column("cost_h", "Cost in port", "float", 1500.0, "$/h"),
            Column("late_cost", "Late cost", "float", 3000.0, "$/h"),
        ], "Time is in hours from the start of the grid.", key_column="name"),
        Table("berths", "Berths", [
            Column("name", "Berth", "text", "B1"),
            Column("open", "Opens at", "float", 0.0, "h"),
            Column("max_rate", "Max discharge rate", "float", 6000.0, "m3/h"),
            Column("max_length", "Max vessel length", "float", 300.0, "m"),
        ], key_column="name"),
    ]
    export_ports = [CRUDE_RECEIPT.name]

    @classmethod
    def example_config(cls) -> dict:
        cfg = cls.defaults()
        cfg["vessels"] = [
            {"name": "V1", "grade": "", "volume": 40000, "arrival": 0, "due": 20, "pump_rate": 5000,
             "length": 240, "cost_h": 1500, "late_cost": 3000},
            {"name": "V2", "grade": "", "volume": 30000, "arrival": 4, "due": 24, "pump_rate": 4000,
             "length": 200, "cost_h": 1200, "late_cost": 3000},
        ]
        cfg["berths"] = [{"name": "B1", "open": 0, "max_rate": 6000, "max_length": 300},
                         {"name": "B2", "open": 0, "max_rate": 4000, "max_length": 250}]
        return cfg

    def check(self, grid: Grid) -> list[str]:
        errs = super().check(grid)
        if not self.rows("vessels"):
            errs.append("add one or more vessels.")
        if not self.rows("berths"):
            errs.append("add one or more berths.")
        for v in self.rows("vessels"):
            if isinstance(v.get("pump_rate"), (int, float)) and v["pump_rate"] <= 0:
                errs.append(f"vessel {v['name']}: the pump rate must be more than 0.")
        for b in self.rows("berths"):
            if isinstance(b.get("max_rate"), (int, float)) and b["max_rate"] <= 0:
                errs.append(f"berth {b['name']}: the max discharge rate must be more than 0.")
        if errs:
            return errs
        for v in self.rows("vessels"):
            if not any(v["length"] <= b["max_length"] for b in self.rows("berths")):
                errs.append(f"vessel {v['name']} ({v['length']:g} m) is too long for all berths.")
        return errs

    def check_linked(self, grid: Grid) -> list[str]:
        errs = []
        for v in self.rows("vessels"):
            if str(v["grade"]) not in grid.grades:
                errs.append(f"vessel {v['name']}: set a grade from the shared grades to send its crude to the tanks.")
        return errs

    def compile(self, ctx: Context, out: Fragment) -> None:
        grid = ctx.grid
        vessels, berths = self.rows("vessels"), self.rows("berths")
        hook, rel = self.num("hookup_h"), self.num("release_h")
        names = [str(v["name"]) for v in vessels]
        bnames = [str(b["name"]) for b in berths]
        rate = {(str(v["name"]), str(b["name"])): min(v["pump_rate"], b["max_rate"])
                for v in vessels for b in berths}
        hand = {k: hook + rel + next(v["volume"] for v in vessels if str(v["name"]) == k[0]) / r
                for k, r in rate.items()}
        ok = {(str(v["name"]), str(b["name"])): 1 if v["length"] <= b["max_length"] else 0
              for v in vessels for b in berths}
        latest = max([v["arrival"] for v in vessels] + [b["open"] for b in berths] + [0.0])
        big_m = latest + sum(max(hand[(n, b)] for b in bnames) for n in names) + grid.horizon
        stage = 1 if self.cfg.get("first_stage", True) else 2

        out.set("V", names, "Vessels")
        out.set("B", bnames, "Berths")
        out.set("PAIRS", [(u, v) for u in names for v in names if u != v], "Ordered pairs of vessels")
        by = {str(v["name"]): v for v in vessels}
        out.param("arr", index="v in {V}", values={n: by[n]["arrival"] for n in names},
                  description="Arrival time (h)")
        out.param("due", index="v in {V}", values={n: by[n]["due"] for n in names},
                  description="Due time for departure (h)")
        out.param("vol", index="v in {V}", values={n: by[n]["volume"] for n in names},
                  description="Cargo volume (m3)")
        out.param("cost_h", index="v in {V}", values={n: by[n]["cost_h"] for n in names},
                  description="Cost of time in port ($/h)")
        out.param("late_cost", index="v in {V}", values={n: by[n]["late_cost"] for n in names},
                  description="Cost of a late departure ($/h)")
        out.param("hand", index="v in {V}, b in {B}", values=hand,
                  description="Shortest service time: hook-up + volume / rate + release (h)")
        out.param("rate", index="v in {V}, b in {B}", values=rate, description="Discharge rate (m3/h)")
        out.param("ok", index="v in {V}, b in {B}", values=ok, description="1 if the vessel fits the berth")
        out.param("open", index="b in {B}", values={str(b["name"]): b["open"] for b in berths},
                  description="Berth opening time (h)")
        out.param("M", big_m, description="Big-M for time (h)")

        out.var("x", "v in {V}, b in {B}", domain="Binary", stage=stage, description="1 if vessel v uses berth b")
        out.var("y", "(u, v) in {PAIRS}", domain="Binary", stage=stage, description="1 if u is served before v")
        out.var("t", "v in {V}", lb="{arr}[v]", description="Berthing time (h)")
        out.var("dep", "v in {V}", description="Departure time (h)")
        out.var("late", "v in {V}", description="Time after the due time (h)")

        out.con("Assign", "v in {V}", "sum({x}[v, b] for b in {B}) == 1", description="Each vessel uses one berth")
        out.con("Fit", "v in {V}, b in {B}", "{x}[v, b] == 0", condition="{ok}[v, b] == 0",
                description="No vessel at a berth that is too short")
        out.con("Order", "(u, v) in {PAIRS}", "{y}[u, v] + {y}[v, u] == 1", condition="u < v",
                description="One of each two vessels goes first")
        out.con("Open", "v in {V}, b in {B}", "{t}[v] >= {open}[b] * {x}[v, b]",
                condition="{open}[b] > 0", description="No berthing before the berth opens")
        out.con("Service", "v in {V}", "{dep}[v] >= {t}[v] + sum({hand}[v, b] * {x}[v, b] for b in {B})",
                description="Departure after the shortest service time")
        out.con("NoOverlap", "(u, v) in {PAIRS}, b in {B}",
                "{t}[v] >= {dep}[u] - {M} * (3 - {y}[u, v] - {x}[u, b] - {x}[v, b])",
                description="Vessels at the same berth do not overlap")
        out.con("Late", "v in {V}", "{late}[v] >= {dep}[v] - {due}[v]", description="Lateness")

        if ctx.consumed(CRUDE_RECEIPT.name, self):
            errs = self.check_linked(grid)
            if errs:
                from .. import spec as S
                raise S.SpecError(self.where, errs[0])
            out.set("VG", [(str(v["name"]), str(v["grade"])) for v in vessels], "Vessel and its crude grade")
            out.param("hook", hook, description="Hook-up time (h)")
            out.param("rel", rel, description="Release time (h)")
            out.param("vmax", index="v in {V}", values={n: max(rate[(n, b)] for b in bnames) for n in names},
                      description="Highest discharge rate of the vessel at any berth (m3/h)")
            out.var("q", f"v in {{V}}, k in {PERIODS}", description="Crude discharged in the period (m3)")
            out.var("z", f"v in {{V}}, k in {PERIODS}", domain="Binary", description="1 if the vessel pumps in the period")
            out.con("PumpAfterHookup", f"v in {{V}}, k in {PERIODS}",
                    "{t}[v] + {hook} <= (k - 1) * period_h + {M} * (1 - {z}[v, k])",
                    description="Pumping starts after berthing and hook-up")
            out.con("PumpBeforeDeparture", f"v in {{V}}, k in {PERIODS}",
                    "{dep}[v] >= (k * period_h + {rel}) * {z}[v, k]",
                    description="The vessel stays until its last pumping period ends")
            out.con("PumpRate", f"v in {{V}}, k in {PERIODS}",
                    "{q}[v, k] <= period_h * sum({rate}[v, b] * {x}[v, b] for b in {B})",
                    description="Discharge rate of the vessel at its berth")
            out.con("PumpOn", f"v in {{V}}, k in {PERIODS}", "{q}[v, k] <= period_h * {vmax}[v] * {z}[v, k]",
                    description="Discharge only in pumping periods")
            out.con("NotBeforeArrival", f"v in {{V}}, k in {PERIODS}", "{z}[v, k] == 0",
                    condition="(k - 1) * period_h < {arr}[v] + {hook}",
                    description="No pumping before arrival and hook-up")
            out.con("Discharge", "v in {V}", f"sum({{q}}[v, k] for k in {PERIODS}) == {{vol}}[v]",
                    description="Each vessel discharges all of its cargo")
            out.con("Horizon", "v in {V}", f"{{dep}}[v] <= {grid.horizon:g}",
                    description="Service ends in the time grid")
            out.expr(CRUDE_RECEIPT.name, f"g in {GRADES}, k in {PERIODS}",
                     "sum({q}[v, k] for (v, gg) in {VG} if gg == g)",
                     description="Crude received by grade and period (m3)")

        out.cost("sum({cost_h}[v] * ({dep}[v] - {arr}[v]) for v in {V})")
        out.cost("sum({late_cost}[v] * {late}[v] for v in {V})")

    def schedule(self, grid: Grid) -> dict | None:
        return {
            "type": "gantt", "tasks": f"v in {self.name_of('V')}", "condition": "", "label": "v",
            "resource": f"which({self.name_of('x')}, v)", "start": f"{self.name_of('t')}[v]",
            "duration": f"{self.name_of('dep')}[v] - {self.name_of('t')}[v]",
            "release": f"{self.name_of('arr')}[v]", "due": f"{self.name_of('due')}[v]",
            "time_unit": "h", "time_origin": grid.start, "wait_warning": "4", "late_tolerance": "0.01",
        }
