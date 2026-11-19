"""Crude distillation unit layer: charge rate, crude blend and start-ups.

Imports ``crude_supply`` (from the tank farm). When no layer exports it, each
grade has a fixed availability rate. The cost is the start-up cost minus the
crude margin, so the units run as much as the crude and the limits allow.
"""
from __future__ import annotations

from .. import spec as S
from .base import (CRUDE_SUPPLY, GRADES, PERIODS, Column, Context, Field, Fragment, Grid, Layer, Table,
                   register)


@register
class CrudeUnitLayer(Layer):
    type_name = "cdu"
    title = "Crude distillation units"
    default_id = "cdu"
    description = ("Crude units with charge-rate limits, ramp limits, a sulfur limit on the blend and "
                   "start-up costs. Imports crude_supply (from the tank farm).")
    fields = [
        Field("ramp", "Max change of charge rate between periods", "float", 150.0, "", 0, unit="m3/h"),
        Field("start_cost", "Start-up cost", "float", 25000.0, "", 0, unit="$"),
        Field("initially_on", "Units are running at the start", "bool", True),
    ]
    tables = [
        Table("units", "Crude units", [
            Column("name", "Unit", "text", "CDU1"),
            Column("min_rate", "Min charge", "float", 500.0, "m3/h"),
            Column("max_rate", "Max charge", "float", 1200.0, "m3/h"),
            Column("max_sulfur", "Max blend sulfur", "float", 2.0, "wt%"),
        ], key_column="name"),
        Table("crudes", "Crude properties", [
            Column("grade", "Grade", "grade", ""),
            Column("sulfur", "Sulfur", "float", 1.0, "wt%"),
            Column("margin", "Margin", "float", 20.0, "$/m3"),
            Column("max_frac", "Max blend fraction", "float", 1.0, "0 to 1"),
            Column("available", "Availability (fallback)", "float", 0.0, "m3/h"),
        ], "Give each shared grade one row. Availability is used only when no layer exports crude_supply.",
            key_column="grade"),
    ]
    import_ports = [CRUDE_SUPPLY.name]

    @classmethod
    def example_config(cls) -> dict:
        cfg = cls.defaults()
        cfg["units"] = [{"name": "CDU1", "min_rate": 500, "max_rate": 1200, "max_sulfur": 2.0}]
        return cfg

    def check(self, grid: Grid) -> list[str]:
        errs = super().check(grid)
        if not self.rows("units"):
            errs.append("add one or more crude units.")
        if errs:
            return errs
        for u in self.rows("units"):
            if not 0 <= u["min_rate"] <= u["max_rate"]:
                errs.append(f"unit {u['name']}: the min charge must be from 0 to the max charge.")
        have = {str(c["grade"]) for c in self.rows("crudes")}
        missing = [g for g in grid.grades if g not in have]
        if missing:
            errs.append(f"give the crude properties of grade {', '.join(missing)}.")
        for c in self.rows("crudes"):
            if not 0 <= c["max_frac"] <= 1:
                errs.append(f"grade {c['grade']}: the max blend fraction must be from 0 to 1.")
        return errs

    def compile(self, ctx: Context, out: Fragment) -> None:
        units = self.rows("units")
        crudes = {str(c["grade"]): c for c in self.rows("crudes")}
        names = [str(u["name"]) for u in units]
        by = {str(u["name"]): u for u in units}
        on0 = 1 if self.cfg.get("initially_on", True) else 0

        out.set("U", names, "Crude units")
        for key, desc in (("min_rate", "Min charge (m3/h)"), ("max_rate", "Max charge (m3/h)"),
                          ("max_sulfur", "Max blend sulfur (wt%)")):
            out.param(key, index="u in {U}", values={n: by[n][key] for n in names}, description=desc)
        for key, desc in (("sulfur", "Crude sulfur (wt%)"), ("margin", "Crude margin ($/m3)"),
                          ("max_frac", "Max fraction of the blend")):
            out.param(key, index=f"g in {GRADES}", values={g: c[key] for g, c in crudes.items()
                                                          if g in ctx.grid.grades}, description=desc)
        out.param("ramp", self.num("ramp"), description="Max charge change between periods (m3/h)")
        out.param("on0", on0, description="1 if the units run at the start")

        out.var("f", f"u in {{U}}, g in {GRADES}, k in {PERIODS}", description="Crude charged in the period (m3)")
        out.var("on", f"u in {{U}}, k in {PERIODS}", domain="Binary", description="1 if the unit runs")
        out.var("start", f"u in {{U}}, k in {PERIODS}", ub="1", description="Start-up in the period")
        out.expr("charge", f"u in {{U}}, k in {PERIODS}", f"sum({{f}}[u, g, k] for g in {GRADES})",
                 description="Charge of the unit in the period (m3)")
        out.expr("feed", f"g in {GRADES}, k in {PERIODS}", "sum({f}[u, g, k] for u in {U})",
                 description="Crude charged to all units by grade (m3)")
        out.con("MinCharge", f"u in {{U}}, k in {PERIODS}",
                "{charge}[u, k] >= {min_rate}[u] * period_h * {on}[u, k]", description="Min charge when running")
        out.con("MaxCharge", f"u in {{U}}, k in {PERIODS}",
                "{charge}[u, k] <= {max_rate}[u] * period_h * {on}[u, k]", description="Max charge; 0 when stopped")
        out.con("Sulfur", f"u in {{U}}, k in {PERIODS}",
                f"sum(({{sulfur}}[g] - {{max_sulfur}}[u]) * {{f}}[u, g, k] for g in {GRADES}) <= 0",
                description="Blend sulfur limit")
        out.con("Fraction", f"u in {{U}}, g in {GRADES}, k in {PERIODS}",
                "{f}[u, g, k] <= {max_frac}[g] * {charge}[u, k]", condition="{max_frac}[g] < 1",
                description="Max fraction of a grade in the blend")
        out.con("RampUp", f"u in {{U}}, k in {PERIODS}",
                "{charge}[u, k] - {charge}[u, k - 1] <= {ramp} * period_h "
                "+ {max_rate}[u] * period_h * (1 - {on}[u, k - 1])",
                condition="k > 1", description="Charge increase limit (start-up excepted)")
        out.con("RampDown", f"u in {{U}}, k in {PERIODS}",
                "{charge}[u, k - 1] - {charge}[u, k] <= {ramp} * period_h "
                "+ {max_rate}[u] * period_h * (1 - {on}[u, k])",
                condition="k > 1", description="Charge decrease limit (shutdown excepted)")
        out.con("StartUp", f"u in {{U}}, k in {PERIODS}",
                "{start}[u, k] >= {on}[u, k] - ({on0} if k == 1 else {on}[u, k - 1])",
                description="Start-up indicator")

        src = ctx.source(CRUDE_SUPPLY.name, self)
        if src:
            out.con("Supply", f"g in {GRADES}, k in {PERIODS}", "{feed}[g, k] == " + src + "[g, k]",
                    description=f"Charge equals the crude sent from the tanks ({src})")
        else:
            out.param("available", index=f"g in {GRADES}",
                      values={g: c["available"] for g, c in crudes.items() if g in ctx.grid.grades},
                      description="Crude availability (m3/h, fallback)")
            out.con("Supply", f"g in {GRADES}, k in {PERIODS}", "{feed}[g, k] <= {available}[g] * period_h",
                    description="Charge within the fixed availability")
            if not any(c["available"] > 0 for c in crudes.values()):
                raise S.SpecError(self.where, "no layer exports crude_supply and all availabilities are 0. "
                                              "Enable a tank layer or give an availability.")

        out.cost(f"{self.num('start_cost'):g} * sum({{start}}[u, k] for u in {{U}} for k in {PERIODS})")
        out.cost(f"-sum({{margin}}[g] * {{feed}}[g, k] for g in {GRADES} for k in {PERIODS})")
