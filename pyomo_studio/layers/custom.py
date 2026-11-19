"""Custom layer: components that you make on the model pages.

Set the Layer field of a set, parameter, variable, expression, constraint or
objective to the id of a custom layer. Those components are then in the model
only when the layer is on. Component names are not prefixed.

A custom layer can export a port (name a component that has the port index)
and import a port. Each import makes an expression with the alias name: it is
the exporter's component when the exporter is on, or the fallback expression.
"""
from __future__ import annotations

from .. import spec as S
from .base import Column, Context, Field, Fragment, Grid, Layer, Port, Table, register


@register
class CustomLayer(Layer):
    type_name = "custom"
    title = "Custom"
    default_id = "custom"
    description = ("Components from the model pages whose Layer field is this layer id. "
                   "Can export and import ports.")
    fields = [
        Field("cost", "Cost added to the total objective (optional)", "expr", "",
              "A Pyomo expression that is minimized with the other layer costs. Use a negative sign for a profit."),
    ]
    tables = [
        Table("exports", "Exported ports", [
            Column("port", "Port", "text", ""),
            Column("component", "Component", "text", ""),
            Column("index", "Index", "text", "g in GRADES, k in PERIODS"),
        ], "The component must have the same index as the port.", key_column="port"),
        Table("imports", "Imported ports", [
            Column("port", "Port", "text", ""),
            Column("alias", "Alias (expression name)", "text", ""),
            Column("index", "Index", "text", "g in GRADES, k in PERIODS"),
            Column("fallback", "Fallback expression", "text", "0"),
        ], "The alias is an expression that you can use in your components.", key_column="port"),
    ]

    def exports(self) -> list[str]:
        return [str(r["port"]).strip() for r in self.rows("exports") if str(r["port"]).strip()]

    def imports(self) -> list[str]:
        return [str(r["port"]).strip() for r in self.rows("imports") if str(r["port"]).strip()]

    def export_component(self, port: str) -> str:
        for r in self.rows("exports"):
            if str(r["port"]).strip() == port:
                return str(r["component"]).strip()
        return super().export_component(port)

    def port_defs(self) -> list[Port]:
        out = []
        for key in ("exports", "imports"):
            for r in self.rows(key):
                name = str(r["port"]).strip()
                if name:
                    out.append(Port(name, f"Port of layer {self.id}", str(r["index"]).strip()))
        return out

    def check(self, grid: Grid) -> list[str]:
        errs = super().check(grid)
        for key in ("exports", "imports"):
            for r in self.rows(key):
                try:
                    S.parse_index(str(r["index"]))
                except S.SpecError as exc:
                    errs.append(f"port {r['port']}: {exc.message}")
        for r in self.rows("exports"):
            if not str(r["component"]).strip():
                errs.append(f"exported port {r['port']}: name the component.")
        for r in self.rows("imports"):
            alias = str(r["alias"]).strip()
            if not S._NAME_RE.match(alias):
                errs.append(f"imported port {r['port']}: the alias must be a valid name.")
        return errs

    def compile(self, ctx: Context, out: Fragment) -> None:
        for r in self.rows("imports"):
            port = str(r["port"]).strip()
            items = S.parse_index(str(r["index"]))
            src = ctx.source(port, self)
            if src:
                keys = ", ".join(", ".join(it.names) for it in items)
                text = f"{src}[{keys}]" if keys else src
            else:
                text = str(r.get("fallback") or "0").strip() or "0"
            item = S.new_item("expressions", str(r["alias"]).strip())
            item.update(index=str(r["index"]), expr=text, layer=self.id,
                        description=f"Port {port} " + (f"from {ctx.providers[port].id}" if src else "(fallback)"))
            out.items["expressions"].append(item)
        cost = str(self.cfg.get("cost") or "").strip()
        if cost:
            out.costs.append(cost)
