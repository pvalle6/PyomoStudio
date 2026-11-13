"""Model specification and pure-Python data layer.

A *spec* is the JSON document that Pyomo Studio edits. It is a plain ``dict``
so that it saves and loads without custom serialisation. This module holds
everything that does not need Pyomo:

* the default spec and forward-compatible normalisation,
* parsing of index declarations such as ``"u in V, (i, j) in ARCS"``,
* resolution of sets and parameters into plain Python data,
* scenario changes and expected-value data for stochastic programming,
* structural validation that reports problems in plain words.

The engine (``engine.py``) turns the resolved data into a Pyomo model.
"""
from __future__ import annotations

import copy
import itertools
import json
import keyword
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

SPEC_VERSION = 1

DOMAINS = [
    "Reals",
    "NonNegativeReals",
    "NonPositiveReals",
    "Binary",
    "Integers",
    "NonNegativeIntegers",
    "NonPositiveIntegers",
    "UnitInterval",
]

#: Names that the expression environment already uses. A model component with
#: one of these names would hide a built-in helper, so validation rejects them.
RESERVED_NAMES = {
    "m", "model", "pyo", "value", "quicksum", "sum", "min", "max", "abs",
    "range", "len", "exp", "log", "log10", "sqrt", "sin", "cos", "tan",
    "asin", "acos", "atan", "sinh", "cosh", "tanh", "inequality", "inf",
    "which", "num", "dual", "SCEN", "scen", "nonant", "ef_objective",
    "ef_eta", "ef_excess", "ef_cvar", "enumerate", "zip", "any", "all",
    "sorted", "list", "tuple", "dict", "set", "float", "int", "round", "str",
    "bool", "reversed", "math", "pi",
}

SAFE_BUILTINS: dict[str, Any] = {
    name: __builtins__[name] if isinstance(__builtins__, dict) else getattr(__builtins__, name)
    for name in (
        "abs", "all", "any", "bool", "dict", "enumerate", "float", "int", "len",
        "list", "max", "min", "range", "reversed", "round", "set", "sorted", "str",
        "sum", "tuple", "zip", "True", "False", "None", "isinstance",
    )
}


class SpecError(Exception):
    """A problem in the spec, with the component that caused it."""

    def __init__(self, where: str, message: str):
        super().__init__(f"{where}: {message}")
        self.where = where
        self.message = message


# ---------------------------------------------------------------------------
# Default spec and normalisation
# ---------------------------------------------------------------------------

def default_schedule() -> dict:
    return {
        "type": "none",          # none | gantt | space_time
        "tasks": "",             # index, e.g. "v in V"
        "condition": "",         # optional filter
        "label": "",             # text on the bar
        "resource": "",          # row of the Gantt chart
        "start": "",
        "duration": "",
        "release": "",           # earliest start (arrival)
        "due": "",               # due time (requested departure)
        "position": "",          # space-time: lower edge
        "size": "",              # space-time: height (for example vessel length)
        "space_label": "Position",
        "space_max": "",         # space-time: total space (for example quay length)
        "time_unit": "h",        # min | h | d | (any text)
        "time_origin": "",       # ISO date-time of t = 0, for clock times
        "wait_warning": "",      # wait above this value gives a warning (amber)
        "late_tolerance": "0.001",
    }


def default_solver() -> dict:
    return {
        "name": "appsi_highs",
        "time_limit": 60.0,
        "mip_gap": 0.0001,
        "tee": True,
        "duals": False,
        "options": "",           # extra "key = value" lines
    }


def new_spec(name: str = "Untitled model") -> dict:
    return {
        "version": SPEC_VERSION,
        "name": name,
        "description": "",
        "sets": [],
        "params": [],
        "variables": [],
        "expressions": [],
        "constraints": [],
        "objectives": [],
        "stochastic": {
            "enabled": False,
            "scenarios": [],
            "risk": {"measure": "expected", "alpha": 0.9, "weight": 0.0},
        },
        "schedule": default_schedule(),
        "solver": default_solver(),
        "hook": "",
    }


ITEM_DEFAULTS: dict[str, dict] = {
    "sets": {"name": "", "kind": "list", "elements": [], "start": 1, "stop": 1,
             "step": 1, "expr": "", "dimen": 1, "description": ""},
    "params": {"name": "", "index": "", "value": 0.0, "default": 0.0,
               "values": [], "formula": "", "description": ""},
    "variables": {"name": "", "index": "", "domain": "NonNegativeReals",
                  "lb": "", "ub": "", "init": "", "stage": 2, "description": ""},
    "expressions": {"name": "", "index": "", "expr": "", "description": ""},
    "constraints": {"name": "", "index": "", "condition": "", "expr": "",
                    "active": True, "description": ""},
    "objectives": {"name": "", "sense": "minimize", "expr": "", "active": True,
                   "description": ""},
}

COMPONENT_KINDS = ["sets", "params", "variables", "expressions", "constraints", "objectives"]
KIND_LABEL = {
    "sets": "Set", "params": "Parameter", "variables": "Variable",
    "expressions": "Expression", "constraints": "Constraint", "objectives": "Objective",
}


def new_item(kind: str, name: str) -> dict:
    item = copy.deepcopy(ITEM_DEFAULTS[kind])
    item["name"] = name
    return item


def normalize(spec: dict) -> dict:
    """Return a copy of *spec* with every key that newer versions expect."""
    base = new_spec()
    out = copy.deepcopy(spec)
    for key, val in base.items():
        out.setdefault(key, copy.deepcopy(val))
    for kind in COMPONENT_KINDS:
        items = []
        for item in out.get(kind) or []:
            full = copy.deepcopy(ITEM_DEFAULTS[kind])
            full.update(item)
            items.append(full)
        out[kind] = items
    sched = default_schedule()
    sched.update(out.get("schedule") or {})
    out["schedule"] = sched
    solver = default_solver()
    solver.update(out.get("solver") or {})
    out["solver"] = solver
    st = out["stochastic"]
    st.setdefault("enabled", False)
    st.setdefault("scenarios", [])
    risk = {"measure": "expected", "alpha": 0.9, "weight": 0.0}
    risk.update(st.get("risk") or {})
    st["risk"] = risk
    for sc in st["scenarios"]:
        sc.setdefault("name", "S")
        sc.setdefault("probability", 0.0)
        sc.setdefault("changes", [])
    # JSON stores tuples as lists; sets keep tuples in memory.
    for s in out["sets"]:
        s["elements"] = [tuple(e) if isinstance(e, list) else e for e in s.get("elements", [])]
    return out


def load_spec(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return normalize(json.load(fh))


def save_spec(spec: dict, path: str | Path) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(spec, fh, indent=2, default=_json_default)
        fh.write("\n")


def _json_default(obj: Any) -> Any:
    if isinstance(obj, tuple):
        return list(obj)
    raise TypeError(f"Cannot save value of type {type(obj).__name__}")


def dumps(spec: dict) -> str:
    return json.dumps(spec, indent=2, default=_json_default)


# ---------------------------------------------------------------------------
# Elements and keys
# ---------------------------------------------------------------------------

_INT_RE = re.compile(r"^[+-]?\d+$")


def parse_scalar(token: str) -> Any:
    """Turn one text token into an int, a float or a string."""
    tok = token.strip()
    if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "'\"":
        return tok[1:-1]
    if _INT_RE.match(tok):
        return int(tok)
    try:
        val = float(tok)
    except ValueError:
        return tok
    if math.isfinite(val):
        return val
    return tok


def parse_elements(text: str) -> list:
    """One element per line. A comma inside a line makes a tuple element.

    Blank lines and lines that start with ``#`` are ignored.
    """
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "," in line:
            out.append(tuple(parse_scalar(p) for p in line.split(",")))
        else:
            out.append(parse_scalar(line))
    return out


def format_element(e: Any) -> str:
    if isinstance(e, tuple):
        return ", ".join(format_element(x) for x in e)
    if isinstance(e, float) and e.is_integer():
        return repr(e)
    return str(e)


def format_elements(elements: Iterable) -> str:
    return "\n".join(format_element(e) for e in elements)


def parse_key(text: str) -> Any:
    """Parse an index written as text (``"V3, B1"``) into a key."""
    parts = [parse_scalar(p) for p in split_top(text)] if text.strip() else []
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else tuple(parts)


def format_key(key: Any) -> str:
    if key is None:
        return ""
    if isinstance(key, tuple):
        return ", ".join(format_element(k) for k in key)
    return format_element(key)


def norm_key(parts: Iterable) -> Any:
    """Make a flat key: a scalar for one part, else a tuple."""
    parts = tuple(parts)
    return parts[0] if len(parts) == 1 else parts


def to_num(x: Any) -> float:
    if isinstance(x, bool):
        return float(int(x))
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        val = parse_scalar(x)
        if isinstance(val, (int, float)):
            return float(val)
    # Pyomo numeric objects support float().
    return float(x)


# ---------------------------------------------------------------------------
# Index declarations
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IndexItem:
    names: tuple[str, ...]   # bound names; empty for an anonymous item
    set_name: str


_ITEM_RE = re.compile(
    r"^\s*(?:\(?\s*(?P<names>[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*\)?\s+in\s+)?"
    r"(?P<set>[A-Za-z_]\w*)\s*$"
)


def split_top(text: str) -> list[str]:
    """Split on commas that are not inside brackets or quotes."""
    parts, depth, cur, quote = [], 0, [], None
    for ch in text:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    if "".join(cur).strip():
        parts.append("".join(cur))
    return [p.strip() for p in parts]


def parse_index(text: str) -> list[IndexItem]:
    """Parse ``"v in V, (i, j) in A, B"`` into index items."""
    text = (text or "").strip()
    if not text:
        return []
    items = []
    for part in split_top(text):
        mt = _ITEM_RE.match(part)
        if not mt:
            raise SpecError("Index", f"cannot read '{part}'. Write 'name in SET', for example 'v in V'.")
        names = tuple(n.strip() for n in mt.group("names").split(",")) if mt.group("names") else ()
        for n in names:
            if keyword.iskeyword(n):
                raise SpecError("Index", f"'{n}' is a Python keyword and cannot be an index name.")
        items.append(IndexItem(names, mt.group("set")))
    return items


def index_text(items: list[IndexItem]) -> str:
    out = []
    for it in items:
        if not it.names:
            out.append(it.set_name)
        elif len(it.names) == 1:
            out.append(f"{it.names[0]} in {it.set_name}")
        else:
            out.append(f"({', '.join(it.names)}) in {it.set_name}")
    return ", ".join(out)


def set_dimen(elements: list, declared: int = 1) -> int:
    for e in elements:
        return len(e) if isinstance(e, tuple) else 1
    return max(1, int(declared or 1))


def iter_index(items: list[IndexItem], sets: dict[str, list]) -> Iterator[tuple[Any, dict]]:
    """Yield ``(flat_key, binding)`` for the cross product of *items*.

    ``flat_key`` matches the key that Pyomo uses for the component. ``binding``
    maps each index name to its value.
    """
    lists = []
    for it in items:
        if it.set_name not in sets:
            raise SpecError("Index", f"set '{it.set_name}' does not exist.")
        lists.append(sets[it.set_name])
    for combo in itertools.product(*lists):
        flat: list = []
        bind: dict = {}
        for it, el in zip(items, combo):
            parts = el if isinstance(el, tuple) else (el,)
            flat.extend(parts)
            if len(it.names) == 1:
                bind[it.names[0]] = el
            elif len(it.names) > 1:
                if len(it.names) != len(parts):
                    raise SpecError(
                        "Index",
                        f"'{index_text([it])}' has {len(it.names)} names but set '{it.set_name}' "
                        f"has {len(parts)} positions.")
                bind.update(zip(it.names, parts))
        yield norm_key(flat), bind


def bind_args(items: list[IndexItem], dims: list[int], args: tuple) -> dict:
    """Map flat Pyomo rule arguments back to index names."""
    bind: dict = {}
    pos = 0
    for it, d in zip(items, dims):
        chunk = args[pos:pos + d]
        pos += d
        if len(it.names) == 1:
            bind[it.names[0]] = chunk[0] if d == 1 else tuple(chunk)
        elif len(it.names) > 1:
            bind.update(zip(it.names, chunk))
    return bind


# ---------------------------------------------------------------------------
# Data resolution
# ---------------------------------------------------------------------------

class ParamTable:
    """Indexed parameter data with a default value.

    Supports ``p[v]`` and ``p[v, b]`` in formulas, like a Pyomo ``Param``.
    """

    def __init__(self, name: str, items: list[IndexItem], data: dict, default: float | None):
        self.name = name
        self.items = items
        self.data = data
        self.default = default

    def __getitem__(self, key):
        if isinstance(key, tuple):
            key = norm_key(_flatten(key))
        if key in self.data:
            return self.data[key]
        if self.default is None:
            raise KeyError(f"parameter '{self.name}' has no value for index {format_key(key)}")
        return self.default

    def __contains__(self, key):
        return key in self.data

    def keys(self):
        return self.data.keys()

    def values(self):
        return self.data.values()

    def items_(self):
        return self.data.items()

    def __iter__(self):
        return iter(self.data)

    def __len__(self):
        return len(self.data)

    def dense(self, sets: dict[str, list]) -> dict:
        return {k: self[k] for k, _ in iter_index(self.items, sets)}

    def copy(self) -> "ParamTable":
        return ParamTable(self.name, self.items, dict(self.data), self.default)


def _flatten(key: tuple) -> list:
    out = []
    for k in key:
        if isinstance(k, tuple):
            out.extend(k)
        else:
            out.append(k)
    return out


def safe_env(extra: dict | None = None) -> dict:
    env = {"__builtins__": SAFE_BUILTINS, "math": math, "inf": math.inf, "pi": math.pi}
    if extra:
        env.update(extra)
    return env


def compile_expr(text: str, where: str):
    """Compile one expression. An expression can use more than one line."""
    src = text.strip()
    try:
        return compile(src, f"<{where}>", "eval")
    except SyntaxError as exc:
        if "\n" in src:
            try:
                return compile("(\n" + src + "\n)", f"<{where}>", "eval")
            except SyntaxError:
                pass
        raise SpecError(where, f"syntax error: {exc.msg} (line {exc.lineno}, column {exc.offset})") from None


def resolve_sets(spec: dict) -> dict[str, list]:
    """Evaluate every set into a Python list (order is kept)."""
    sets: dict[str, list] = {}
    for s in spec["sets"]:
        name = s["name"]
        where = f"Set '{name}'"
        kind = s.get("kind", "list")
        if kind == "list":
            elements = [tuple(e) if isinstance(e, list) else e for e in s.get("elements", [])]
        elif kind == "range":
            try:
                start, stop = int(s.get("start", 1)), int(s.get("stop", 1))
                step = int(s.get("step", 1) or 1)
            except (TypeError, ValueError):
                raise SpecError(where, "start, stop and step must be integers.") from None
            if step == 0:
                raise SpecError(where, "step cannot be 0.")
            elements = list(range(start, stop + (1 if step > 0 else -1), step))
        elif kind == "expression":
            code = compile_expr(s.get("expr", ""), where)
            env = safe_env({k: list(v) for k, v in sets.items()})
            try:
                elements = list(eval(code, env))  # noqa: S307 - documented trusted model code
            except Exception as exc:
                raise SpecError(where, f"{type(exc).__name__}: {exc}") from None
            elements = [tuple(e) if isinstance(e, list) else e for e in elements]
        else:
            raise SpecError(where, f"unknown kind '{kind}'.")
        seen = set()
        for e in elements:
            if e in seen:
                raise SpecError(where, f"element {format_element(e)} occurs more than one time.")
            seen.add(e)
        dims = {len(e) if isinstance(e, tuple) else 1 for e in elements}
        if len(dims) > 1:
            raise SpecError(where, "all elements must have the same number of positions.")
        sets[name] = elements
    return sets


def set_dims(spec: dict, sets: dict[str, list]) -> dict[str, int]:
    return {s["name"]: set_dimen(sets.get(s["name"], []), s.get("dimen", 1)) for s in spec["sets"]}


def _default_of(p: dict) -> float | None:
    d = p.get("default", 0.0)
    if d is None or (isinstance(d, str) and not d.strip()):
        return None
    return to_num(d)


def resolve_params(spec: dict, sets: dict[str, list], changes: Iterable[dict] = ()) -> dict[str, Any]:
    """Evaluate every parameter. Scalars become floats; indexed ones ParamTable."""
    changes = list(changes)
    params: dict[str, Any] = {}
    for p in spec["params"]:
        name = p["name"]
        where = f"Parameter '{name}'"
        try:
            items = parse_index(p.get("index", ""))
        except SpecError as exc:
            raise SpecError(where, exc.message) from None
        formula = (p.get("formula") or "").strip()
        env_base = safe_env({**{k: list(v) for k, v in sets.items()}, **params})
        if not items:
            if formula:
                code = compile_expr(formula, where)
                try:
                    val = to_num(eval(code, env_base))  # noqa: S307
                except Exception as exc:
                    raise SpecError(where, f"{type(exc).__name__}: {exc}") from None
            else:
                try:
                    val = to_num(p.get("value", 0.0))
                except (TypeError, ValueError):
                    raise SpecError(where, "value is not a number.") from None
            params[name] = val
        else:
            for it in items:
                if it.set_name not in sets:
                    raise SpecError(where, f"set '{it.set_name}' does not exist.")
            default = _default_of(p)
            data: dict = {}
            if formula:
                code = compile_expr(formula, where)
                for key, bind in iter_index(items, sets):
                    env = dict(env_base)
                    env.update(bind)
                    try:
                        data[key] = to_num(eval(code, env))  # noqa: S307
                    except Exception as exc:
                        raise SpecError(where, f"index {format_key(key)}: {type(exc).__name__}: {exc}") from None
            else:
                valid = {k for k, _ in iter_index(items, sets)}
                ndim = sum(set_dimen(sets[it.set_name]) for it in items)
                for row in p.get("values", []):
                    if len(row) != ndim + 1:
                        raise SpecError(where, f"row {row} must have {ndim} index values and 1 value.")
                    key = norm_key(tuple(row[:-1]))
                    if key not in valid:
                        raise SpecError(where, f"index {format_key(key)} is not in the index sets.")
                    try:
                        data[key] = to_num(row[-1])
                    except (TypeError, ValueError):
                        raise SpecError(where, f"value for {format_key(key)} is not a number.") from None
            params[name] = ParamTable(name, items, data, default)
        _apply_changes(name, params, sets, [c for c in changes if c.get("param") == name])
    return params


def _apply_one(old: float, op: str, val: float) -> float:
    if op == "set":
        return val
    if op == "add":
        return old + val
    if op == "scale":
        return old * val
    raise SpecError("Scenario change", f"unknown operation '{op}'. Use set, add or scale.")


def _apply_changes(name: str, params: dict, sets: dict, changes: list[dict]) -> None:
    for ch in changes:
        where = f"Scenario change on '{name}'"
        op = ch.get("op", "set")
        try:
            val = to_num(ch.get("value", 0.0))
        except (TypeError, ValueError):
            raise SpecError(where, "value is not a number.") from None
        target = params[name]
        idx_text = str(ch.get("index", "") or "").strip()
        if not isinstance(target, ParamTable):
            if idx_text:
                raise SpecError(where, "the parameter has no index. Make the index field empty.")
            params[name] = _apply_one(target, op, val)
            continue
        if idx_text in ("", "*"):
            dense = target.dense(sets)
            target.data = {k: _apply_one(v, op, val) for k, v in dense.items()}
        else:
            key = parse_key(idx_text)
            valid = {k for k, _ in iter_index(target.items, sets)}
            if key not in valid:
                raise SpecError(where, f"index {idx_text} is not in the index sets.")
            target.data[key] = _apply_one(target[key], op, val)


def scenario_data(spec: dict, sets: dict) -> list[tuple[str, float, dict]]:
    """Return ``(name, probability, params)`` for each scenario."""
    out = []
    for sc in spec["stochastic"]["scenarios"]:
        params = resolve_params(spec, sets, sc.get("changes", []))
        out.append((str(sc["name"]), float(sc.get("probability", 0.0)), params))
    return out


def expected_params(spec: dict, sets: dict, scen: list[tuple[str, float, dict]]) -> dict:
    """Probability-weighted mean of every parameter (for the EV problem)."""
    if not scen:
        return resolve_params(spec, sets)
    total = sum(p for _, p, _ in scen) or 1.0
    out: dict = {}
    first = scen[0][2]
    for name, val in first.items():
        if isinstance(val, ParamTable):
            keys = [k for k, _ in iter_index(val.items, sets)]
            data = {k: sum(p * d[name][k] for _, p, d in scen) / total for k in keys}
            dflt = None if val.default is None else sum(
                p * (d[name].default or 0.0) for _, p, d in scen) / total
            out[name] = ParamTable(name, val.items, data, dflt)
        else:
            out[name] = sum(p * d[name] for _, p, d in scen) / total
    return out


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

@dataclass
class Issue:
    level: str        # "error" | "warning"
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.level.upper()}: {self.where}: {self.message}"


_NAME_RE = re.compile(r"^[A-Za-z_]\w*$")


@dataclass
class ValidationReport:
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, level: str, where: str, message: str) -> None:
        self.issues.append(Issue(level, where, message))


def validate(spec: dict) -> ValidationReport:
    """Find problems that stop a model build. Data is resolved as a test."""
    rep = ValidationReport()
    seen: dict[str, str] = {}
    for kind in COMPONENT_KINDS:
        for item in spec[kind]:
            name = item.get("name", "")
            where = f"{KIND_LABEL[kind]} '{name}'"
            if not _NAME_RE.match(name or "") or keyword.iskeyword(name):
                rep.add("error", where, "the name must start with a letter or '_' and contain only letters, digits and '_'.")
            elif name in RESERVED_NAMES:
                rep.add("error", where, "the program uses this name. Use a different name.")
            elif name in seen:
                rep.add("error", where, f"the name is also used by {seen[name]}.")
            else:
                seen[name] = where
            for fld in ("expr", "condition", "formula", "lb", "ub", "init"):
                text = (item.get(fld) or "") if isinstance(item.get(fld), str) else ""
                if kind == "sets" and fld == "expr" and item.get("kind") != "expression":
                    continue
                if text.strip():
                    try:
                        compile_expr(text, where)
                    except SpecError as exc:
                        rep.add("error", f"{where} ({fld})", exc.message)
            if "index" in item:
                try:
                    for it in parse_index(item.get("index", "")):
                        if it.set_name not in {s["name"] for s in spec["sets"]}:
                            rep.add("error", where, f"index set '{it.set_name}' does not exist.")
                except SpecError as exc:
                    rep.add("error", where, exc.message)
    for kind in ("constraints", "objectives", "expressions"):
        for item in spec[kind]:
            if not (item.get("expr") or "").strip():
                rep.add("error", f"{KIND_LABEL[kind]} '{item['name']}'", "the expression is empty.")
    active = [o for o in spec["objectives"] if o.get("active", True)]
    if len(active) != 1:
        rep.add("error", "Objectives", f"exactly 1 objective must be active. Now {len(active)} are active.")
    st = spec["stochastic"]
    if st.get("enabled"):
        scen = st.get("scenarios", [])
        if len(scen) < 2:
            rep.add("error", "Uncertainty", "a stochastic model needs 2 or more scenarios.")
        names = [str(s.get("name")) for s in scen]
        if len(set(names)) != len(names):
            rep.add("error", "Uncertainty", "scenario names must be different.")
        probs = [float(s.get("probability", 0) or 0) for s in scen]
        if any(p < 0 for p in probs):
            rep.add("error", "Uncertainty", "a probability cannot be less than 0.")
        if scen and abs(sum(probs) - 1.0) > 1e-6:
            rep.add("error", "Uncertainty", f"the probabilities must add to 1. Now they add to {sum(probs):.6g}.")
        if not any(int(v.get("stage", 2)) == 1 for v in spec["variables"]):
            rep.add("warning", "Uncertainty",
                    "no variable is first stage. Each scenario then has its own plan and the result is not one plan.")
        risk = st.get("risk", {})
        if risk.get("measure") == "cvar":
            a = float(risk.get("alpha", 0.9))
            w = float(risk.get("weight", 0.0))
            if not 0 < a < 1:
                rep.add("error", "Uncertainty", "the CVaR level alpha must be more than 0 and less than 1.")
            if not 0 <= w <= 1:
                rep.add("error", "Uncertainty", "the CVaR weight must be from 0 to 1.")
    if not rep.errors:
        try:
            sets = resolve_sets(spec)
            resolve_params(spec, sets)
            if st.get("enabled"):
                scenario_data(spec, sets)
        except SpecError as exc:
            rep.add("error", exc.where, exc.message)
    for v in spec["variables"]:
        if v.get("domain") not in DOMAINS:
            rep.add("error", f"Variable '{v['name']}'", f"unknown domain '{v.get('domain')}'.")
    return rep


def component_names(spec: dict) -> list[str]:
    return [item["name"] for kind in COMPONENT_KINDS for item in spec[kind]]


def unique_name(spec: dict, stem: str) -> str:
    names = set(component_names(spec))
    if stem not in names:
        return stem
    for i in itertools.count(2):
        cand = f"{stem}{i}"
        if cand not in names:
            return cand
    raise AssertionError("unreachable")
