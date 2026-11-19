"""On-shore tank farm layer: crude receipt, storage and send-out by grade.

Imports ``crude_receipt`` (vessel discharge). When no layer exports it, the
layer uses its fixed delivery table. Exports ``crude_supply`` (crude sent to
the crude units). When no layer imports it, the send-out follows the fixed
demand table and any shortfall has a penalty cost.
"""
from __future__ import annotations

from .. import spec as S
from .base import (CRUDE_RECEIPT, CRUDE_SUPPLY, GRADES, PERIODS, Column, Context, Field, Fragment, Grid,
                   Layer, Table, register)


@register
class TankFarmLayer(Layer):
    type_name = "tank_farm"
    title = "Tank farm"
    default_id = "tank"
    description = ("Dedicated crude tanks with capacity, heel, and inlet and outlet rate limits. "
                   "Imports crude_receipt (from the berths) and exports crude_supply (to the crude units).")
    fields = [
        Field("no_simultaneous", "A tank does not receive and send in the same period", "bool", True,
              "Standing time for settling and gauging. This adds two binary variables per tank and period."),
        Field("end_fraction", "Closing stock as a fraction of opening stock (each grade)", "float", 0.8,
              "0 means no closing-stock target.", 0, unit=""),
        Field("hold_cost", "Inventory holding cost", "float", 0.0, "", 0, unit="$/m3 per period"),
        Field("short_cost", "Penalty for unmet fixed demand", "float", 200.0,
              "Used only when no crude unit layer takes the crude.", 0, unit="$/m3"),
        Field("reject_cost", "Penalty for fixed deliveries that do not fit", "float", 1000.0,
              "Used only when no berth layer supplies the crude.", 0, unit="$/m3"),
    ]
    tables = [
        Table("tanks", "Tanks", [
            Column("name", "Tank", "text", "T1"),
            Column("grade", "Grade", "grade", ""),
            Column("capacity", "Capacity", "float", 80000.0, "m3"),
            Column("heel", "Heel (minimum)", "float", 5000.0, "m3"),
            Column("initial", "Opening stock", "float", 30000.0, "m3"),
            Column("in_rate", "Max inlet rate", "float", 6000.0, "m3/h"),
            Column("out_rate", "Max outlet rate", "float", 1500.0, "m3/h"),
        ], "Each tank holds one grade.", key_column="name"),
        Table("deliveries", "Fixed deliveries (fallback)", [
            Column("grade", "Grade", "grade", ""),
            Column("first", "First period", "int", 1),
            Column("last", "Last period", "int", 1),
            Column("volume", "Volume", "float", 0.0, "m3"),
        ], "Used only when no enabled layer exports crude_receipt. The volume is spread evenly "
           "from the first to the last period."),
        Table("demand", "Fixed send-out demand (fallback)", [
            Column("grade", "Grade", "grade", ""),
            Column("rate", "Rate", "float", 0.0, "m3/h"),
        ], "Used only when no enabled layer imports crude_supply."),
    ]
    import_ports = [CRUDE_RECEIPT.name]
    export_ports = [CRUDE_SUPPLY.name]

    @classmethod
    def example_config(cls) -> dict:
        cfg = cls.defaults()
        cfg["tanks"] = [
            {"name": "T1", "grade": "", "capacity": 80000, "heel": 5000, "initial": 30000,
             "in_rate": 6000, "out_rate": 1500},
            {"name": "T2", "grade": "", "capacity": 80000, "heel": 5000, "initial": 20000,
             "in_rate": 6000, "out_rate": 1500},
        ]
        return cfg

    def check(self, grid: Grid) -> list[str]:
        errs = super().check(grid)
        if not self.rows("tanks"):
            errs.append("add one or more tanks.")
        if errs:
            return errs
        for t in self.rows("tanks"):
            if not t["heel"] <= t["initial"] <= t["capacity"]:
                errs.append(f"tank {t['name']}: the opening stock must be from the heel to the capacity.")
        tank_grades = {str(t["grade"]) for t in self.rows("tanks")}
        for d in self.rows("deliveries"):
            if not 1 <= d["first"] <= d["last"] <= grid.periods:
                errs.append(f"fixed delivery of grade {d['grade']}: the periods must be from 1 to {grid.periods}, "
                            "and the first period must not be after the last.")
            if str(d["grade"]) not in tank_grades:
                errs.append(f"fixed delivery of grade {d['grade']}: no tank holds this grade.")
        return errs

    def compile(self, ctx: Context, out: Fragment) -> None:
        grid = ctx.grid
        tanks = self.rows("tanks")
        names = [str(t["name"]) for t in tanks]
        by = {str(t["name"]): t for t in tanks}
        last = grid.periods
        binary = bool(self.cfg.get("no_simultaneous", True))

        out.set("I", names, "Tanks")
        out.set("IG", [(str(t["name"]), str(t["grade"])) for t in tanks], "Tank and its grade")
        for key, desc in (("capacity", "Capacity (m3)"), ("heel", "Heel (m3)"), ("initial", "Opening stock (m3)"),
                          ("in_rate", "Max inlet rate (m3/h)"), ("out_rate", "Max outlet rate (m3/h)")):
            out.param(key, index="i in {I}", values={n: by[n][key] for n in names}, description=desc)

        out.var("inv", f"i in {{I}}, k in {PERIODS}", lb="{heel}[i]", ub="{capacity}[i]",
                description="Stock at the end of the period (m3)")
        out.var("fin", f"i in {{I}}, k in {PERIODS}", description="Crude into the tank in the period (m3)")
        out.var("fout", f"i in {{I}}, k in {PERIODS}", description="Crude out of the tank in the period (m3)")
        out.con("Balance", f"i in {{I}}, k in {PERIODS}",
                "{inv}[i, k] == ({initial}[i] if k == 1 else {inv}[i, k - 1]) + {fin}[i, k] - {fout}[i, k]",
                description="Stock balance")
        if binary:
            out.var("rcv", f"i in {{I}}, k in {PERIODS}", domain="Binary", description="1 if the tank receives")
            out.var("snd", f"i in {{I}}, k in {PERIODS}", domain="Binary", description="1 if the tank sends")
            out.con("InRate", f"i in {{I}}, k in {PERIODS}", "{fin}[i, k] <= {in_rate}[i] * period_h * {rcv}[i, k]",
                    description="Inlet rate limit")
            out.con("OutRate", f"i in {{I}}, k in {PERIODS}", "{fout}[i, k] <= {out_rate}[i] * period_h * {snd}[i, k]",
                    description="Outlet rate limit")
            out.con("OneMode", f"i in {{I}}, k in {PERIODS}", "{rcv}[i, k] + {snd}[i, k] <= 1",
                    description="No receipt and send-out in the same period")
        else:
            out.con("InRate", f"i in {{I}}, k in {PERIODS}", "{fin}[i, k] <= {in_rate}[i] * period_h",
                    description="Inlet rate limit")
            out.con("OutRate", f"i in {{I}}, k in {PERIODS}", "{fout}[i, k] <= {out_rate}[i] * period_h",
                    description="Outlet rate limit")

        # Receipt: from the berth layer, or the fixed deliveries.
        src = ctx.source(CRUDE_RECEIPT.name, self)
        if src:
            out.con("Receive", f"g in {GRADES}, k in {PERIODS}",
                    "sum({fin}[i, k] for (i, gg) in {IG} if gg == g) == " + src + "[g, k]",
                    description=f"Crude from the berths ({src}) goes into tanks of its grade")
        else:
            fixed: dict = {}
            for d in self.rows("deliveries"):
                first, last = int(d["first"]), int(d["last"])
                share = float(d["volume"]) / (last - first + 1)
                for k in range(first, last + 1):
                    key = (str(d["grade"]), k)
                    fixed[key] = fixed.get(key, 0.0) + share
            out.param("delivery", index=f"g in {GRADES}, k in {PERIODS}", values=fixed,
                      description="Fixed deliveries (m3, fallback)")
            out.var("reject", f"g in {GRADES}, k in {PERIODS}", description="Fixed delivery that does not fit (m3)")
            out.con("Receive", f"g in {GRADES}, k in {PERIODS}",
                    "sum({fin}[i, k] for (i, gg) in {IG} if gg == g) + {reject}[g, k] == {delivery}[g, k]",
                    description="Fixed deliveries go into tanks of their grade")
            out.cost(f"{self.num('reject_cost'):g} * sum({{reject}}[g, k] for g in {GRADES} for k in {PERIODS})")

        out.expr(CRUDE_SUPPLY.name, f"g in {GRADES}, k in {PERIODS}",
                 "sum({fout}[i, k] for (i, gg) in {IG} if gg == g)",
                 description="Crude sent out by grade and period (m3)")
        if not ctx.consumed(CRUDE_SUPPLY.name, self):
            rates = {}
            for d in self.rows("demand"):
                rates[str(d["grade"])] = rates.get(str(d["grade"]), 0.0) + float(d["rate"])
            out.param("demand", index=f"g in {GRADES}", values=rates, description="Fixed send-out rate (m3/h, fallback)")
            out.var("short", f"g in {GRADES}, k in {PERIODS}", description="Unmet fixed demand (m3)")
            out.con("Demand", f"g in {GRADES}, k in {PERIODS}",
                    "{crude_supply}[g, k] + {short}[g, k] == {demand}[g] * period_h",
                    description="Send-out follows the fixed demand")
            out.cost(f"{self.num('short_cost'):g} * sum({{short}}[g, k] for g in {GRADES} for k in {PERIODS})")

        frac = self.num("end_fraction")
        if frac > 0:
            out.con("Closing", f"g in {GRADES}",
                    f"sum({{inv}}[i, {last}] for (i, gg) in {{IG}} if gg == g) >= "
                    f"{frac:g} * sum({{initial}}[i] for (i, gg) in {{IG}} if gg == g)",
                    description="Closing stock target by grade")
        hold = self.num("hold_cost")
        if hold > 0:
            out.cost(f"{hold:g} * sum({{inv}}[i, k] for i in {{I}} for k in {PERIODS})")
        if not src and not ctx.consumed(CRUDE_SUPPLY.name, self) and not self.rows("deliveries") \
                and not self.rows("demand"):
            raise S.SpecError(self.where, "the layer has no receipt and no send-out. Enable a berth or crude unit "
                                          "layer, or fill the fixed delivery or demand table.")
