"""Layer framework: switchable sub-models that compile into the flat model format.

A layer is a polymorphic object. Each subclass of :class:`Layer` knows its
configuration schema (scalar fields and data tables), the ports it exports
and imports, and how to write its sets, parameters, variables, expressions,
constraints and cost terms. :func:`compose` turns a spec with layers into an
ordinary flat spec, so the rest of the program (validation, build, stochastic
analysis, results, reports, script export) does not need to know about layers.

Ports connect layers. A port has an index (for example ``g in GRADES, k in
PERIODS``) and a unit. One enabled layer may export a port; any number of
layers may import it. When the exporter is off, each importer uses its own
fallback data, and when no importer is on, the exporter can apply its own
fallback (for example a fixed demand). So every layer also solves alone.

This module does not import Pyomo.
"""
from __future__ import annotations

import copy
import keyword
import re
from dataclasses import dataclass, field
from typing import Any, ClassVar

from .. import spec as S

# Names of the shared grid components.
PERIODS = "PERIODS"
GRADES = "GRADES"
PERIOD_H = "period_h"
SHARED_NAMES = {PERIODS, GRADES, PERIOD_H}
TOTAL_OBJECTIVE = "TotalCost"

_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")
_IDENT_RE = re.compile(r"[A-Za-z_]\w*")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

@dataclass
class Field:
    """A scalar setting of a layer."""
    key: str
    label: str
    kind: str = "float"          # float | int | bool | text | expr
    default: Any = 0.0
    help: str = ""
    minimum: float | None = None
    maximum: float | None = None
    unit: str = ""


@dataclass
class Column:
    key: str
    label: str
    kind: str = "float"          # float | int | text | grade
    default: Any = 0.0
    unit: str = ""


@dataclass
class Table:
    """A data table of a layer. Rows are dicts keyed by column key."""
    key: str
    label: str
    columns: list[Column]
    help: str = ""
    key_column: str | None = None    # values in this column must be unique names


@dataclass(frozen=True)
class Port:
    name: str
    label: str
    index: str                   # index text, for example "g in GRADES, k in PERIODS"
    unit: str = ""


# Built-in ports. Custom layers can declare more.
PORTS: dict[str, Port] = {}


def register_port(port: Port) -> Port:
    PORTS[port.name] = port
    return port


CRUDE_RECEIPT = register_port(Port(
    "crude_receipt", "Crude discharged from vessels into the terminal", f"g in {GRADES}, k in {PERIODS}",
    "m3 per period"))
CRUDE_SUPPLY = register_port(Port(
    "crude_supply", "Crude sent from the tank farm to the crude units", f"g in {GRADES}, k in {PERIODS}",
    "m3 per period"))


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

LAYER_TYPES: dict[str, type["Layer"]] = {}


def register(cls: type["Layer"]) -> type["Layer"]:
    """Class decorator: make a layer type available by its ``type_name``."""
    if not cls.type_name:
        raise ValueError(f"{cls.__name__} has no type_name")
    LAYER_TYPES[cls.type_name] = cls
    return cls


def layer_class(type_name: str) -> type["Layer"]:
    try:
        return LAYER_TYPES[type_name]
    except KeyError:
        raise S.SpecError("Layers", f"unknown layer type '{type_name}'. Known types: "
                          f"{', '.join(sorted(LAYER_TYPES))}.") from None


# ---------------------------------------------------------------------------
# Fragment: the components one layer writes
# ---------------------------------------------------------------------------

class _Prefixed(dict):
    """Template names: ``{x}`` becomes ``<id>_x``; shared names stay as they are."""

    def __init__(self, prefix: str, extra: dict | None = None):
        super().__init__(extra or {})
        self.prefix = prefix

    def __missing__(self, key: str) -> str:
        if key in SHARED_NAMES:
            return key
        return f"{self.prefix}{key}"


class Fragment:
    """Collects the components that one layer adds to the model."""

    def __init__(self, layer: "Layer"):
        self.layer = layer
        self.items: dict[str, list[dict]] = {k: [] for k in S.COMPONENT_KINDS}
        self.costs: list[str] = []

    # name helpers --------------------------------------------------------
    def n(self, local: str) -> str:
        return self.layer.name_of(local)

    def f(self, template: str, **extra) -> str:
        """Format *template*: ``{name}`` gives the prefixed component name."""
        return template.format_map(_Prefixed(self.layer.prefix, extra))

    def _add(self, component_kind: str, local: str, **fields) -> dict:
        item = S.new_item(component_kind, self.n(local) if local else "")
        item.update(fields)
        item["layer"] = self.layer.id
        self.items[component_kind].append(item)
        return item

    # component helpers -----------------------------------------------------
    def set(self, local: str, elements: list, description: str = "") -> str:
        dimen = len(elements[0]) if elements and isinstance(elements[0], tuple) else 1
        self._add("sets", local, kind="list", elements=list(elements), dimen=dimen,
                  description=description)
        return self.n(local)

    def param(self, local: str, value: Any = 0.0, *, index: str = "", values: dict | None = None,
              default: Any = 0.0, description: str = "") -> str:
        rows = []
        for k, v in (values or {}).items():
            key = list(k) if isinstance(k, tuple) else [k]
            rows.append(key + [v])
        self._add("params", local, index=self.f(index), value=value, values=rows,
                  default="" if default is None else default, description=description)
        return self.n(local)

    def var(self, local: str, index: str = "", *, domain: str = "NonNegativeReals", lb: str = "",
            ub: str = "", stage: int = 2, description: str = "") -> str:
        self._add("variables", local, index=self.f(index), domain=domain, lb=self.f(lb), ub=self.f(ub),
                  stage=stage, description=description)
        return self.n(local)

    def expr(self, local: str, index: str, expr: str, description: str = "") -> str:
        self._add("expressions", local, index=self.f(index), expr=self.f(expr), description=description)
        return self.n(local)

    def con(self, local: str, index: str, expr: str, *, condition: str = "", description: str = "") -> str:
        self._add("constraints", local, index=self.f(index), expr=self.f(expr),
                  condition=self.f(condition), description=description)
        return self.n(local)

    def cost(self, expr: str) -> None:
        """Add a cost term (minimized). Use a negative term for a profit."""
        self.costs.append(self.f(expr))


# ---------------------------------------------------------------------------
# Context: what a layer can see of the other layers
# ---------------------------------------------------------------------------

@dataclass
class Grid:
    periods: int
    period_h: float
    grades: list[str]
    start: str = ""

    @property
    def horizon(self) -> float:
        return self.periods * self.period_h


@dataclass
class Link:
    port: str
    direction: str          # "in" | "out"
    partner: str | None     # layer id at the other end, None = fallback
    component: str | None   # the exported component name (for "in": the source)


def _index_sets(text: str) -> list[str]:
    return [it.set_name for it in S.parse_index(text)]


class Context:
    def __init__(self, grid: Grid, layers: list["Layer"]):
        self.grid = grid
        self.layers = layers
        self.providers: dict[str, "Layer"] = {}
        self.consumers: dict[str, list["Layer"]] = {}
        self.ports: dict[str, Port] = dict(PORTS)
        for lay in layers:
            for port in lay.port_defs():
                known = self.ports.get(port.name)
                if known is not None and _index_sets(known.index) != _index_sets(port.index):
                    raise S.SpecError(f"Layer '{lay.id}'",
                                      f"port '{port.name}' has index '{port.index}', "
                                      f"but the port is defined as '{known.index}'.")
                self.ports.setdefault(port.name, port)
            for p in lay.exports():
                if p in self.providers:
                    raise S.SpecError(f"Layer '{lay.id}'",
                                      f"port '{p}' is also exported by layer '{self.providers[p].id}'. "
                                      "Only one enabled layer can export a port.")
                self.providers[p] = lay
            for p in lay.imports():
                self.consumers.setdefault(p, []).append(lay)

    def source(self, port: str, me: "Layer | None" = None) -> str | None:
        """The component that supplies *port*, or None if no enabled layer exports it."""
        prov = self.providers.get(port)
        if prov is None or prov is me:
            return None
        return prov.export_component(port)

    def consumed(self, port: str, me: "Layer | None" = None) -> bool:
        return any(c is not me for c in self.consumers.get(port, []))

    def links(self, lay: "Layer") -> list[Link]:
        out = []
        for p in lay.imports():
            prov = self.providers.get(p)
            ok = prov is not None and prov is not lay
            out.append(Link(p, "in", prov.id if ok else None, prov.export_component(p) if ok else None))
        for p in lay.exports():
            cons = [c.id for c in self.consumers.get(p, []) if c is not lay]
            out.append(Link(p, "out", ", ".join(cons) or None, lay.export_component(p)))
        return out


# ---------------------------------------------------------------------------
# Layer base class
# ---------------------------------------------------------------------------

class Layer:
    """Base class. Subclasses set the class attributes and implement :meth:`compile`."""

    type_name: ClassVar[str] = ""
    title: ClassVar[str] = ""
    description: ClassVar[str] = ""
    fields: ClassVar[list[Field]] = []
    tables: ClassVar[list[Table]] = []
    export_ports: ClassVar[list[str]] = []
    import_ports: ClassVar[list[str]] = []
    default_id: ClassVar[str] = "layer"

    def __init__(self, data: dict):
        self.data = data
        self.id: str = str(data.get("id", ""))
        self.cfg: dict = self.defaults()
        self.cfg.update(data.get("config") or {})
        for t in self.tables:
            self.cfg[t.key] = [self._row(t, r) for r in (self.cfg.get(t.key) or [])]

    # schema helpers ----------------------------------------------------------
    @classmethod
    def defaults(cls) -> dict:
        cfg = {f.key: copy.deepcopy(f.default) for f in cls.fields}
        for t in cls.tables:
            cfg[t.key] = []
        return cfg

    @classmethod
    def example_config(cls) -> dict:
        """A configuration with sample data, used when a layer is added in the interface."""
        return cls.defaults()

    @staticmethod
    def _row(t: Table, row: dict) -> dict:
        out = {}
        for c in t.columns:
            val = row.get(c.key, c.default)
            if c.kind in ("float", "int"):
                try:
                    val = S.to_num(val)
                    if c.kind == "int":
                        val = int(round(val))
                except (TypeError, ValueError):
                    pass   # check() reports it
            out[c.key] = val
        return out

    # names -------------------------------------------------------------------
    @property
    def prefix(self) -> str:
        return f"{self.id}_"

    def name_of(self, local: str) -> str:
        return f"{self.prefix}{local}"

    @property
    def where(self) -> str:
        return f"Layer '{self.id}'"

    # ports -------------------------------------------------------------------
    def exports(self) -> list[str]:
        return list(self.export_ports)

    def imports(self) -> list[str]:
        return list(self.import_ports)

    def export_component(self, port: str) -> str:
        """Name of the indexed expression (or variable) that carries an exported port."""
        return self.name_of(port)

    def port_defs(self) -> list[Port]:
        """Ports that this layer defines (custom layers)."""
        return []

    # checks ------------------------------------------------------------------
    def check(self, grid: Grid) -> list[str]:
        """Return error messages for the configuration."""
        errs = []
        for f in self.fields:
            val = self.cfg.get(f.key)
            if f.kind in ("float", "int"):
                try:
                    x = S.to_num(val)
                except (TypeError, ValueError):
                    errs.append(f"{f.label}: write a number.")
                    continue
                if f.minimum is not None and x < f.minimum:
                    errs.append(f"{f.label}: the value must be {f.minimum:g} or more.")
                if f.maximum is not None and x > f.maximum:
                    errs.append(f"{f.label}: the value must be {f.maximum:g} or less.")
        for t in self.tables:
            seen = set()
            for i, row in enumerate(self.cfg[t.key], start=1):
                for c in t.columns:
                    val = row.get(c.key)
                    if c.kind in ("float", "int") and not isinstance(val, (int, float)):
                        errs.append(f"{t.label}, row {i}: {c.label} must be a number.")
                    elif c.kind == "grade" and str(val) not in grid.grades:
                        errs.append(f"{t.label}, row {i}: grade '{val}' is not in the shared grades "
                                    f"({', '.join(grid.grades) or 'none'}).")
                if t.key_column:
                    name = str(row.get(t.key_column, "")).strip()
                    if not name:
                        errs.append(f"{t.label}, row {i}: the name is empty.")
                    elif name in seen:
                        errs.append(f"{t.label}: the name '{name}' occurs more than one time.")
                    seen.add(name)
        return errs

    def num(self, key: str) -> float:
        return float(S.to_num(self.cfg[key]))

    def rows(self, key: str) -> list[dict]:
        return self.cfg[key]

    # compile -------------------------------------------------------------------
    def compile(self, ctx: Context, out: Fragment) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def schedule(self, grid: Grid) -> dict | None:
        """A default schedule view for this layer, or None."""
        return None


# ---------------------------------------------------------------------------
# Spec helpers
# ---------------------------------------------------------------------------

def default_layers() -> dict:
    return {
        "grid": {"periods": 24, "period_h": 1.0, "grades": [], "start": ""},
        "items": [],
        "objective": {"name": TOTAL_OBJECTIVE, "include_base": True},
    }


def normalize_layers(spec: dict) -> dict:
    """Fill missing keys of ``spec['layers']`` (in place) and return it."""
    base = default_layers()
    lay = spec.get("layers")
    if not isinstance(lay, dict):
        lay = {}
    grid = dict(base["grid"])
    grid.update(lay.get("grid") or {})
    if isinstance(grid.get("grades"), str):
        grid["grades"] = [g.strip() for g in grid["grades"].split(",") if g.strip()]
    obj = dict(base["objective"])
    obj.update(lay.get("objective") or {})
    items = lay.get("items")
    if not isinstance(items, list):
        items = []
    for it in items:
        it.setdefault("id", "layer")
        it.setdefault("type", "custom")
        it.setdefault("name", "")
        it.setdefault("enabled", True)
        it.setdefault("weight", 1.0)
        it.setdefault("config", {})
    if spec.get("layers") is not lay:
        spec["layers"] = lay
    # Update in place, so that references that callers keep stay valid.
    lay["grid"], lay["objective"] = grid, obj
    lay["items"] = items
    return lay


def new_layer(spec: dict, type_name: str) -> dict:
    """Make a new layer entry (with sample data) that has a unique id."""
    cls = layer_class(type_name)
    used = {str(it.get("id")) for it in normalize_layers(spec)["items"]} | set(S.component_names(spec))
    stem = cls.default_id
    lid = stem
    i = 2
    while lid in used:
        lid = f"{stem}{i}"
        i += 1
    return {"id": lid, "type": type_name, "name": cls.title, "enabled": True, "weight": 1.0,
            "config": cls.example_config()}


def instantiate(item: dict) -> Layer:
    return layer_class(item.get("type", "custom"))(item)


def _grid(lay: dict) -> Grid:
    g = lay["grid"]
    try:
        periods = int(S.to_num(g.get("periods", 24)))
        period_h = float(S.to_num(g.get("period_h", 1.0)))
    except (TypeError, ValueError):
        raise S.SpecError("Layers: time grid", "periods and period length must be numbers.") from None
    if periods < 1:
        raise S.SpecError("Layers: time grid", "the number of periods must be 1 or more.")
    if period_h <= 0:
        raise S.SpecError("Layers: time grid", "the period length must be more than 0.")
    grades = [str(x).strip() for x in g.get("grades") or [] if str(x).strip()]
    if len(set(grades)) != len(grades):
        raise S.SpecError("Layers: time grid", "each grade name must be different.")
    return Grid(periods, period_h, grades, str(g.get("start") or ""))


def active_layers(spec: dict) -> list[dict]:
    lay = spec.get("layers") or {}
    return [it for it in lay.get("items") or [] if it.get("enabled", True)]


def has_layers(spec: dict) -> bool:
    lay = spec.get("layers") or {}
    return bool(lay.get("items"))


# ---------------------------------------------------------------------------
# Ordering: a component must come after the components its text uses
# ---------------------------------------------------------------------------

def _refs(item: dict, fields_: tuple[str, ...]) -> set[str]:
    out: set[str] = set()
    for fld in fields_:
        text = item.get(fld)
        if isinstance(text, str):
            out.update(_IDENT_RE.findall(text))
    return out


def _toposort(items: list[dict], fields_: tuple[str, ...]) -> list[dict]:
    """Stable topological order by name references. Cycles keep the list order."""
    names = {it["name"]: i for i, it in enumerate(items)}
    deps = {i: {names[r] for r in _refs(it, fields_) if r in names and names[r] != i}
            for i, it in enumerate(items)}
    done: list[int] = []
    state: dict[int, int] = {}

    def visit(i: int) -> None:
        if state.get(i) == 2:
            return
        if state.get(i) == 1:   # cycle: let the build report it
            return
        state[i] = 1
        for d in sorted(deps[i]):
            visit(d)
        state[i] = 2
        done.append(i)

    for i in range(len(items)):
        visit(i)
    return [items[i] for i in done]


# ---------------------------------------------------------------------------
# Compose
# ---------------------------------------------------------------------------

@dataclass
class LayerInfo:
    id: str
    type: str
    title: str
    enabled: bool
    links: list[Link] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    names: dict[str, list[str]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def _check_items(lay: dict) -> None:
    seen = set()
    for it in lay["items"]:
        lid = str(it.get("id", ""))
        where = f"Layer '{lid}'"
        if not _ID_RE.match(lid) or keyword.iskeyword(lid):
            raise S.SpecError(where, "the layer id must start with a letter and contain only letters and digits.")
        if lid in seen:
            raise S.SpecError(where, "another layer has this id.")
        seen.add(lid)
        layer_class(it.get("type", "custom"))


def compose(spec: dict, *, info: list | None = None) -> dict:
    """Return the flat spec for *spec*: base components plus every enabled layer.

    The result has ``_composed = True`` and composing it again returns it as it is.
    If *info* is a list, a :class:`LayerInfo` for each layer is added to it.
    """
    if spec.get("_composed"):
        return spec
    out = copy.deepcopy(spec)
    out["_composed"] = True
    if not has_layers(out):
        out.pop("layers", None)
        return out
    lay = normalize_layers(out)
    _check_items(lay)
    grid = _grid(lay)
    enabled_ids = {str(it["id"]) for it in lay["items"] if it.get("enabled", True)}
    all_ids = {str(it["id"]) for it in lay["items"]}

    # Base components that belong to a layer stay only when the layer is on.
    for kind in S.COMPONENT_KINDS:
        kept = []
        for it in out[kind]:
            tag = (it.get("layer") or "").strip()
            if tag and tag not in all_ids:
                raise S.SpecError(f"{S.KIND_LABEL[kind]} '{it.get('name')}'",
                                  f"the component belongs to layer '{tag}', but that layer does not exist.")
            if not tag or tag in enabled_ids:
                kept.append(it)
        out[kind] = kept

    layers = [instantiate(it) for it in lay["items"] if it.get("enabled", True)]
    ctx = Context(grid, layers)

    shared: dict[str, list[dict]] = {k: [] for k in S.COMPONENT_KINDS}
    shared["sets"].append({**S.new_item("sets", PERIODS), "kind": "range", "start": 1,
                           "stop": grid.periods, "step": 1,
                           "description": f"Time periods of {grid.period_h:g} h"})
    shared["sets"].append({**S.new_item("sets", GRADES), "kind": "list", "elements": list(grid.grades),
                           "description": "Crude grades (shared by the layers)"})
    shared["params"].append({**S.new_item("params", PERIOD_H), "value": grid.period_h,
                             "description": "Length of one period (h)"})

    frags: list[tuple[Layer, Fragment]] = []
    for layer in layers:
        errs = layer.check(grid)
        if errs:
            raise S.SpecError(layer.where, errs[0] + (f" (and {len(errs) - 1} more)" if len(errs) > 1 else ""))
        frag = Fragment(layer)
        layer.compile(ctx, frag)
        frags.append((layer, frag))

    for kind in S.COMPONENT_KINDS:
        merged = shared[kind] + [it for _, fr in frags for it in fr.items[kind]] + out[kind]
        if kind == "sets":
            merged = _toposort(merged, ("expr",))
        elif kind == "params":
            merged = _toposort(merged, ("formula",))
        elif kind == "expressions":
            merged = _toposort(merged, ("expr",))
        out[kind] = merged

    # Objective: the weighted sum of the layer costs (+ the base objective).
    weights = {str(it["id"]): float(S.to_num(it.get("weight", 1.0) or 0.0)) for it in lay["items"]}
    terms = []
    for layer, frag in frags:
        if not frag.costs:
            continue
        cname = layer.name_of("cost")
        out["expressions"].append({**S.new_item("expressions", cname), "expr": " + ".join(f"({c})" for c in frag.costs),
                                   "description": f"Cost of layer {layer.id}", "layer": layer.id})
        out["objectives"].append({**S.new_item("objectives", f"Cost_{layer.id}"), "expr": cname,
                                  "active": False, "description": f"Cost of layer {layer.id} (measure)",
                                  "layer": layer.id})
        w = weights.get(layer.id, 1.0)
        terms.append(cname if w == 1.0 else f"{w:g} * {cname}")
    if terms:
        base_active = [o for o in out["objectives"] if o.get("active", True)]
        if lay["objective"].get("include_base", True):
            for o in base_active:
                sign = "-" if o.get("sense") == "maximize" else ""
                terms.append(f"{sign}({o['expr']})")
        for o in out["objectives"]:
            o["active"] = False
        name = lay["objective"].get("name") or TOTAL_OBJECTIVE
        out["objectives"].insert(0, {**S.new_item("objectives", name), "sense": "minimize",
                                     "expr": " + ".join(terms), "active": True,
                                     "description": "Weighted sum of the costs of the enabled layers", "layer": ""})

    sched = out.get("schedule") or {}
    if sched.get("type", "none") == "none":
        for layer in layers:
            view = layer.schedule(grid)
            if view:
                merged = S.default_schedule()
                merged.update(view)
                out["schedule"] = merged
                break

    if info is not None:
        frag_of = {l.id: fr for l, fr in frags}
        for it in lay["items"]:
            cls = LAYER_TYPES.get(it.get("type"))
            li = LayerInfo(str(it["id"]), str(it.get("type")), cls.title if cls else "?",
                           bool(it.get("enabled", True)))
            fr = frag_of.get(li.id)
            if fr is not None:
                layer = fr.layer
                li.links = ctx.links(layer)
                li.counts = {k: len(v) for k, v in fr.items.items()}
                li.names = {k: [x["name"] for x in v] for k, v in fr.items.items()}
            info.append(li)
    out.pop("layers", None)
    out["_layer_ids"] = sorted(all_ids)
    # What the result views (for example the tank schematic) need to know about the layers.
    out["_grid"] = {"periods": grid.periods, "period_h": grid.period_h, "grades": list(grid.grades),
                    "start": grid.start}
    out["_layers"] = [{"id": layer.id, "type": layer.type_name,
                       "links": [{"port": lk.port, "direction": lk.direction, "partner": lk.partner,
                                  "component": lk.component} for lk in ctx.links(layer)]}
                      for layer in layers]
    return out


def describe(spec: dict) -> tuple[list[LayerInfo], str]:
    """Layer information for the interface: ``(infos, error_text)``.

    Disabled layers are shown with their links as if they were on, so that the
    user can see what switching them on would connect.
    """
    infos: list[LayerInfo] = []
    try:
        compose(spec, info=infos)
    except S.SpecError as exc:
        return infos, str(exc)
    # Links of disabled layers: compose a copy with all layers on.
    if any(not li.enabled for li in infos):
        probe = copy.deepcopy(spec)
        for it in probe["layers"]["items"]:
            it["enabled"] = True
        all_on: list[LayerInfo] = []
        try:
            compose(probe, info=all_on)
            by_id = {li.id: li for li in all_on}
            for li in infos:
                if not li.enabled and li.id in by_id:
                    li.links = by_id[li.id].links
                    li.counts = by_id[li.id].counts
                    li.names = by_id[li.id].names
        except S.SpecError:
            pass
    return infos, ""
