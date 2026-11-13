"""Pyomo engine: build, solve and analyse models described by a spec.

The engine turns a spec (see ``spec.py``) into a Pyomo ``ConcreteModel``:

* sets, parameters, variables, named expressions, constraints and objectives
  become the matching Pyomo components;
* text expressions are Python expressions in Pyomo syntax, evaluated once per
  index with the index names bound (``sum(x[v, b] for b in B) == 1``);
* a stochastic spec becomes a two-stage *extensive form*: one block per
  scenario, non-anticipativity constraints on first-stage variables and an
  expected-value (optionally mean-CVaR) objective;
* ``stochastic_analysis`` computes RP, WS, EV, EEV, EVPI and VSS.

Expressions in a model file are Python code. Open model files only from
sources that you trust.
"""
from __future__ import annotations

import contextlib
import io
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from . import spec as S

try:  # Pyomo is needed to build and solve, not to edit specs.
    import pyomo.environ as pyo
    PYOMO_IMPORT_ERROR: Exception | None = None
except Exception as _exc:  # pragma: no cover - depends on installation
    pyo = None
    PYOMO_IMPORT_ERROR = _exc

LogFn = Callable[[str], None]

GOOD_TERMINATIONS = {"optimal", "globallyOptimal", "locallyOptimal", "feasible"}
LIMIT_TERMINATIONS = {
    "maxTimeLimit", "maxIterations", "maxEvaluations", "userInterrupt", "other",
    "intermediateNonInteger", "resourceInterrupt", "unknown",
}

#: Solvers that the program offers. ``detect_solvers`` finds the ones installed.
SOLVER_CHOICES = [
    "appsi_highs", "highs", "cbc", "glpk", "gurobi", "gurobi_direct", "cplex",
    "cplex_direct", "xpress", "scip", "ipopt", "bonmin", "couenne",
]

#: (time-limit option, relative-MIP-gap option) for each solver.
OPTION_NAMES: dict[str, tuple[str | None, str | None]] = {
    "appsi_highs": ("time_limit", "mip_rel_gap"),
    "highs": ("time_limit", "mip_rel_gap"),
    "cbc": ("seconds", "ratioGap"),
    "glpk": ("tmlim", "mipgap"),
    "gurobi": ("TimeLimit", "MIPGap"),
    "gurobi_direct": ("TimeLimit", "MIPGap"),
    "cplex": ("timelimit", "mipgap"),
    "cplex_direct": ("timelimit", "mipgap"),
    "xpress": ("maxtime", "miprelstop"),
    "scip": ("limits/time", "limits/gap"),
    "ipopt": ("max_cpu_time", None),
    "bonmin": ("bonmin.time_limit", "bonmin.allowable_fraction_gap"),
    "couenne": (None, None),
}

#: Solver suggestions for each problem class.
CLASS_SOLVERS = {
    "LP": ["appsi_highs", "cbc", "glpk", "gurobi", "cplex"],
    "MILP": ["appsi_highs", "cbc", "gurobi", "cplex", "scip", "glpk"],
    "QP": ["gurobi", "cplex", "appsi_highs", "ipopt"],
    "MIQP": ["gurobi", "cplex", "scip"],
    "NLP": ["ipopt", "scip", "couenne"],
    "MINLP": ["scip", "bonmin", "couenne", "gurobi"],
}


class EngineError(Exception):
    """A problem that stops a build or a solve, in plain words."""


class BuildError(EngineError):
    pass


def require_pyomo() -> None:
    if pyo is None:
        raise EngineError(
            "Pyomo is not installed. Install it with:  pip install pyomo highspy\n"
            f"(import error: {PYOMO_IMPORT_ERROR})")


# ---------------------------------------------------------------------------
# Expression environment
# ---------------------------------------------------------------------------

def _keys(comp) -> list:
    return list(comp.keys()) if comp.is_indexed() else [None]


def _items(comp) -> list:
    return list(comp.items()) if comp.is_indexed() else [(None, comp)]


def which(component, *prefix, threshold: float = 0.5):
    """Return the remaining index of the member of *component* that is "on".

    ``which(x, v)`` gives the berth ``b`` with ``x[v, b] > 0.5``. If more than
    one member is on, a list is returned; if none, ``None``.
    """
    pre = tuple(S._flatten(prefix))
    hits = []
    for key in _keys(component):
        k = key if isinstance(key, tuple) else (key,)
        if k[:len(pre)] != pre:
            continue
        val = pyo.value(component[key], exception=False)
        if val is not None and val > threshold:
            hits.append(S.norm_key(k[len(pre):]) if len(k) > len(pre) else key)
    if not hits:
        return None
    return hits[0] if len(hits) == 1 else hits


def num(x) -> float:
    """Numeric value of a Pyomo object or a number."""
    return float(pyo.value(x))


def expression_env() -> dict:
    require_pyomo()
    funcs = {}
    for name in ("exp", "log", "log10", "sqrt", "sin", "cos", "tan", "asin", "acos",
                 "atan", "sinh", "cosh", "tanh"):
        if hasattr(pyo, name):
            funcs[name] = getattr(pyo, name)
    return S.safe_env({
        "pyo": pyo,
        "value": pyo.value,
        "quicksum": pyo.quicksum,
        "inequality": pyo.inequality,
        "which": which,
        "num": num,
        **funcs,
    })


def _truthy(val) -> bool:
    try:
        return bool(val)
    except Exception:  # Pyomo relational expressions cannot become bool
        raise BuildError("a condition must give True or False from data only. "
                         "Do not use variables in a condition.") from None


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

@dataclass
class Built:
    model: Any
    stochastic: bool
    scenarios: list[str]
    probs: dict[str, float]
    blocks: dict[str, Any]
    regs: dict[str, dict]
    envs: dict[str, dict]
    params: dict[str, dict]
    sets: dict[str, list]
    objective_name: str
    sense: int                      # +1 minimize, -1 maximize
    risk: dict = field(default_factory=dict)
    scen_objective: dict = field(default_factory=dict)
    var_names: list = field(default_factory=list)


class _Evaluator:
    """Evaluates one compiled expression with index names bound."""

    def __init__(self, env: dict, where: str):
        self.env = env
        self.where = where

    def __call__(self, code, bind: dict, key=None):
        local = dict(self.env)
        local.update(bind)
        try:
            return eval(code, local)  # noqa: S307 - trusted model code, see module doc
        except BuildError:
            raise
        except Exception as exc:
            at = f" at index ({S.format_key(key)})" if key is not None else ""
            raise BuildError(f"{self.where}{at}: {type(exc).__name__}: {exc}") from None


def _compile(text: str, where: str):
    try:
        return S.compile_expr(text, where)
    except S.SpecError as exc:
        raise BuildError(str(exc)) from None


def _parse_items(item: dict, where: str, dims: dict) -> tuple[list, list[int]]:
    try:
        items = S.parse_index(item.get("index", ""))
    except S.SpecError as exc:
        raise BuildError(f"{where}: {exc.message}") from None
    for it in items:
        if it.set_name not in dims:
            raise BuildError(f"{where}: set '{it.set_name}' does not exist.")
    return items, [dims[it.set_name] for it in items]


def build_into(blk, spec: dict, sets: dict, dims: dict, params: dict) -> tuple[dict, dict]:
    """Add every component of *spec* to the Pyomo block *blk*.

    Return ``(registry, env)``: the components by name and the expression
    environment that the schedule view and the hook use.
    """
    reg: dict[str, Any] = {}
    env = expression_env()
    env["m"] = blk
    env["model"] = blk

    def add(name: str, comp) -> Any:
        blk.add_component(name, comp)
        obj = getattr(blk, name)
        reg[name] = obj
        env[name] = obj
        return obj

    for s in spec["sets"]:
        add(s["name"], pyo.Set(initialize=list(sets[s["name"]]), ordered=True,
                               dimen=dims[s["name"]]))

    for p in spec["params"]:
        name = p["name"]
        val = params[name]
        if isinstance(val, S.ParamTable):
            kw: dict[str, Any] = {"initialize": dict(val.data), "within": pyo.Reals, "mutable": False}
            if val.default is not None:
                kw["default"] = val.default
            add(name, pyo.Param(*[reg[it.set_name] for it in val.items], **kw))
        else:
            add(name, pyo.Param(initialize=float(val), within=pyo.Reals, mutable=False))
            # Data is a plain number in expressions, so max(), min() and "if" work on it.
            env[name] = float(val)

    for v in spec["variables"]:
        _add_var(v, add, reg, env, dims)

    for e in spec["expressions"]:
        where = f"Expression '{e['name']}'"
        items, idims = _parse_items(e, where, dims)
        code = _compile(e["expr"], where)
        ev = _Evaluator(env, where)
        add(e["name"], pyo.Expression(*[reg[it.set_name] for it in items],
                                      rule=_expr_rule(ev, code, items, idims)))

    for c in spec["constraints"]:
        where = f"Constraint '{c['name']}'"
        items, idims = _parse_items(c, where, dims)
        code = _compile(c["expr"], where)
        cond = _compile(c["condition"], where + " (condition)") if (c.get("condition") or "").strip() else None
        ev = _Evaluator(env, where)
        comp = add(c["name"], pyo.Constraint(*[reg[it.set_name] for it in items],
                                             rule=_con_rule(ev, code, cond, items, idims, where)))
        if not c.get("active", True):
            comp.deactivate()

    for o in spec["objectives"]:
        where = f"Objective '{o['name']}'"
        code = _compile(o["expr"], where)
        ev = _Evaluator(env, where)
        sense = pyo.maximize if o.get("sense") == "maximize" else pyo.minimize
        comp = add(o["name"], pyo.Objective(rule=_obj_rule(ev, code), sense=sense))
        if not o.get("active", True):
            comp.deactivate()

    hook = (spec.get("hook") or "").strip()
    if hook:
        hook_env = dict(env)
        hook_env["__builtins__"] = __builtins__
        hook_env["registry"] = reg
        try:
            exec(compile(hook, "<custom hook>", "exec"), hook_env)  # noqa: S102 - documented
        except Exception as exc:
            raise BuildError(f"Custom hook: {type(exc).__name__}: {exc}") from None
    return reg, env


def _add_var(v: dict, add, reg: dict, env: dict, dims: dict) -> None:
    where = f"Variable '{v['name']}'"
    items, idims = _parse_items(v, where, dims)
    domain = getattr(pyo, v.get("domain", "Reals"))
    ev = _Evaluator(env, where)
    codes = {}
    for fld in ("lb", "ub", "init"):
        text = str(v.get(fld, "") or "").strip()
        codes[fld] = _compile(text, f"{where} ({fld})") if text else None
    kw: dict[str, Any] = {"domain": domain}
    sets_ = [reg[it.set_name] for it in items]
    if codes["lb"] or codes["ub"]:
        def bounds(_blk, *args, _c=codes):
            bind = S.bind_args(items, idims, args)
            lo = ev(_c["lb"], bind, args) if _c["lb"] else None
            hi = ev(_c["ub"], bind, args) if _c["ub"] else None
            return (None if lo is None else float(pyo.value(lo)),
                    None if hi is None else float(pyo.value(hi)))
        kw["bounds"] = bounds
    if codes["init"]:
        def init(_blk, *args, _c=codes):
            bind = S.bind_args(items, idims, args)
            return float(pyo.value(ev(_c["init"], bind, args)))
        kw["initialize"] = init
    add(v["name"], pyo.Var(*sets_, **kw))


def _expr_rule(ev, code, items, idims):
    def rule(_blk, *args):
        return ev(code, S.bind_args(items, idims, args), args or None)
    return rule


def _con_rule(ev, code, cond, items, idims, where):
    def rule(_blk, *args):
        bind = S.bind_args(items, idims, args)
        key = args or None
        if cond is not None and not _truthy(ev(cond, bind, key)):
            return pyo.Constraint.Skip
        res = ev(code, bind, key)
        if isinstance(res, bool) or type(res).__name__ == "bool_":
            if res:
                return pyo.Constraint.Skip
            at = f" at index ({S.format_key(key)})" if key else ""
            raise BuildError(f"{where}{at}: the constraint is always false for the data. "
                             "The model has no feasible solution.")
        if isinstance(res, (int, float)):
            raise BuildError(f"{where}: the expression gives a number, not a relation. "
                             "Use ==, <= or >=.")
        return res
    return rule


def _obj_rule(ev, code):
    def rule(_blk):
        return ev(code, {}, None)
    return rule


def _active_objective(spec: dict) -> dict:
    active = [o for o in spec["objectives"] if o.get("active", True)]
    if len(active) != 1:
        raise BuildError(f"Exactly 1 objective must be active. Now {len(active)} are active.")
    return active[0]


def stage1_vars(spec: dict) -> list[str]:
    return [v["name"] for v in spec["variables"] if int(v.get("stage", 2)) == 1]


def build(spec: dict, *, params: dict | None = None, deterministic: bool = False,
          risk: dict | None = None) -> Built:
    """Build the Pyomo model for *spec*.

    A stochastic spec gives the extensive form unless *deterministic* is true.
    *params* replaces the base data of a deterministic build (for scenarios,
    expected values and wait-and-see problems).
    """
    require_pyomo()
    try:
        sets = S.resolve_sets(spec)
        dims = S.set_dims(spec, sets)
        obj_spec = _active_objective(spec)
        sense = -1 if obj_spec.get("sense") == "maximize" else 1
        stoch = bool(spec["stochastic"].get("enabled")) and not deterministic
        if not stoch:
            if params is None:
                params = S.resolve_params(spec, sets)
            m = pyo.ConcreteModel(name=spec.get("name") or "model")
            reg, env = build_into(m, spec, sets, dims, params)
            return Built(m, False, ["base"], {"base": 1.0}, {"base": m}, {"base": reg},
                         {"base": env}, {"base": params}, sets, obj_spec["name"], sense,
                         var_names=[v["name"] for v in spec["variables"]])
        scen = S.scenario_data(spec, sets)
    except S.SpecError as exc:
        raise BuildError(str(exc)) from None
    built = _build_ef(spec, sets, dims, scen, obj_spec, sense, risk or spec["stochastic"]["risk"])
    built.var_names = [v["name"] for v in spec["variables"]]
    return built


def _build_ef(spec, sets, dims, scen, obj_spec, sense, risk) -> Built:
    m = pyo.ConcreteModel(name=f"{spec.get('name') or 'model'} (extensive form)")
    names = [n for n, _, _ in scen]
    probs = {n: p for n, p, _ in scen}
    m.SCEN = pyo.Set(initialize=names, ordered=True)
    m.scen = pyo.Block(m.SCEN)
    regs, envs, pars = {}, {}, {}
    for name, _, params in scen:
        blk = m.scen[name]
        regs[name], envs[name] = build_into(blk, spec, sets, dims, params)
        pars[name] = params
    obj_name = obj_spec["name"]
    scen_obj = {}
    for name in names:
        scen_obj[name] = regs[name][obj_name].expr
        for o in spec["objectives"]:
            regs[name][o["name"]].deactivate()
    # Non-anticipativity: first-stage decisions are the same in all scenarios.
    m.nonant = pyo.ConstraintList()
    first = names[0]
    for vname in stage1_vars(spec):
        base = regs[first][vname]
        for other in names[1:]:
            comp = regs[other][vname]
            for k in _keys(base):
                m.nonant.add(comp[k] == base[k] if k is not None else comp == base)
    cost = {n: sense * scen_obj[n] for n in names}
    expected = sum(probs[n] * cost[n] for n in names)
    measure = (risk or {}).get("measure", "expected")
    weight = float((risk or {}).get("weight", 0.0) or 0.0)
    alpha = float((risk or {}).get("alpha", 0.9) or 0.9)
    if measure == "cvar" and weight > 0:
        m.ef_eta = pyo.Var(domain=pyo.Reals)
        m.ef_excess = pyo.Var(m.SCEN, domain=pyo.NonNegativeReals)
        m.ef_cvar = pyo.Constraint(m.SCEN, rule=lambda mm, s: mm.ef_excess[s] >= cost[s] - mm.ef_eta)
        cvar = m.ef_eta + (1.0 / (1.0 - alpha)) * sum(probs[n] * m.ef_excess[n] for n in names)
        m.ef_objective = pyo.Objective(expr=(1 - weight) * expected + weight * cvar, sense=pyo.minimize)
    else:
        m.ef_objective = pyo.Objective(expr=expected, sense=pyo.minimize)
    return Built(m, True, names, probs, {n: m.scen[n] for n in names}, regs, envs, pars,
                 sets, obj_name, sense, dict(risk or {}), scen_obj)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def _degree(expr) -> int | None:
    fn = getattr(expr, "polynomial_degree", None)
    if fn is None:
        return 0
    try:
        return fn()
    except Exception:
        return None


def model_stats(built: Built, spec: dict) -> dict:
    n_cont = n_bin = n_int = n_con = 0
    max_deg = 0
    nonlinear = False
    for name in built.scenarios:
        reg = built.regs[name]
        for v in spec["variables"]:
            for _, vd in _items(reg[v["name"]]):
                if vd.is_binary():
                    n_bin += 1
                elif vd.is_integer():
                    n_int += 1
                else:
                    n_cont += 1
        for c in spec["constraints"]:
            comp = reg[c["name"]]
            if not comp.active:
                continue
            for _, cd in _items(comp):
                n_con += 1
                d = _degree(cd.body)
                if d is None:
                    nonlinear = True
                else:
                    max_deg = max(max_deg, d)
        obj = reg[built.objective_name]
        d = _degree(obj.expr)
        if d is None:
            nonlinear = True
        else:
            max_deg = max(max_deg, d)
    if built.stochastic:
        n_con += len(built.model.nonant)
        if hasattr(built.model, "ef_cvar"):
            n_con += len(built.model.ef_cvar)
            n_cont += 1 + len(built.scenarios)
    discrete = (n_bin + n_int) > 0
    if nonlinear or max_deg > 2:
        cls = "MINLP" if discrete else "NLP"
    elif max_deg == 2:
        cls = "MIQP" if discrete else "QP"
    else:
        cls = "MILP" if discrete else "LP"
    return {
        "class": cls, "continuous": n_cont, "binary": n_bin, "integer": n_int,
        "variables": n_cont + n_bin + n_int, "constraints": n_con,
        "scenarios": len(built.scenarios) if built.stochastic else 1,
    }


# ---------------------------------------------------------------------------
# Solve
# ---------------------------------------------------------------------------

@dataclass
class SolverOptions:
    name: str = "appsi_highs"
    time_limit: float | None = 60.0
    mip_gap: float | None = 1e-4
    tee: bool = True
    duals: bool = False
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_spec(cls, d: dict) -> "SolverOptions":
        def opt_float(x):
            try:
                return float(x) if str(x).strip() != "" else None
            except (TypeError, ValueError):
                return None
        return cls(
            name=str(d.get("name") or "appsi_highs"),
            time_limit=opt_float(d.get("time_limit")),
            mip_gap=opt_float(d.get("mip_gap")),
            tee=bool(d.get("tee", True)),
            duals=bool(d.get("duals", False)),
            extra=parse_option_lines(d.get("options", "")),
        )


def parse_option_lines(text: str) -> dict:
    out = {}
    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if "=" not in line:
            raise EngineError(f"Solver option '{line}' has no '='. Write 'name = value'.")
        k, v = line.split("=", 1)
        out[k.strip()] = S.parse_scalar(v)
    return out


class _LineWriter(io.TextIOBase):
    def __init__(self, fn: LogFn | None):
        self.fn = fn
        self.buf = ""
        self.all = io.StringIO()

    def write(self, s: str) -> int:
        self.all.write(s)
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            if self.fn:
                self.fn(line)
        return len(s)

    def flush(self) -> None:
        if self.buf and self.fn:
            self.fn(self.buf)
        self.buf = ""


class _LogHandler(logging.Handler):
    def __init__(self, writer: _LineWriter):
        super().__init__(logging.WARNING)
        self.writer = writer

    def emit(self, record):
        self.writer.write(f"[{record.levelname}] {record.getMessage()}\n")


@contextlib.contextmanager
def _capture(fn: LogFn | None):
    writer = _LineWriter(fn)
    handler = _LogHandler(writer)
    logger = logging.getLogger("pyomo")
    logger.addHandler(handler)
    try:
        with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
            yield writer
    finally:
        writer.flush()
        logger.removeHandler(handler)


def _make_solver(name: str):
    """Create a Pyomo solver, or None when it is not installed.

    Pyomo logs a full traceback on ``pyomo.opt`` when an executable-based
    solver (bonmin, couenne, ...) is missing; that is expected here, so it
    is muted while the solver object is created.
    """
    logger = logging.getLogger("pyomo.opt")
    old = logger.disabled
    logger.disabled = True
    try:
        opt = pyo.SolverFactory(name)
        return opt if opt is not None and opt.available(exception_flag=False) else None
    except Exception:
        return None
    finally:
        logger.disabled = old


def detect_solvers() -> dict[str, bool]:
    """Return ``{solver name: available}``."""
    require_pyomo()
    with _capture(None):
        return {name: _make_solver(name) is not None for name in SOLVER_CHOICES}


@dataclass
class RunInfo:
    ok: bool
    termination: str
    status: str
    message: str
    wall_time: float
    lower_bound: float | None = None
    upper_bound: float | None = None
    log: str = ""


def _finite(x) -> float | None:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def run_solver(built: Built, opts: SolverOptions, log: LogFn | None = None) -> RunInfo:
    require_pyomo()
    m = built.model
    opt = _make_solver(opts.name)
    if opt is None:
        hint = "  For HiGHS:  pip install highspy" if "highs" in opts.name else ""
        raise EngineError(f"Solver '{opts.name}' is not available. Install it or select "
                          f"a different solver on the Solve page.{hint}")
    tl_name, gap_name = OPTION_NAMES.get(opts.name, (None, None))
    if opts.time_limit and tl_name:
        opt.options[tl_name] = int(math.ceil(opts.time_limit)) if opts.name == "glpk" else opts.time_limit
    if opts.mip_gap is not None and gap_name:
        opt.options[gap_name] = opts.mip_gap
    for k, v in opts.extra.items():
        opt.options[k] = v
    if opts.duals and m.component("dual") is None:
        m.dual = pyo.Suffix(direction=pyo.Suffix.IMPORT)
    t0 = time.perf_counter()
    with _capture(log) as writer:
        try:
            results = opt.solve(m, tee=opts.tee)
        except Exception as exc:
            wall = time.perf_counter() - t0
            text = str(exc)
            if "feasible solution was not found" in text or "no solution" in text.lower():
                msg = "The solver found no feasible solution. The model can be infeasible, or the time limit is too short."
                return RunInfo(False, "noSolution", "warning", msg, wall, log=writer.all.getvalue())
            return RunInfo(False, "error", "error", f"{type(exc).__name__}: {text}", wall,
                           log=writer.all.getvalue())
    wall = time.perf_counter() - t0
    term = str(results.solver.termination_condition)
    status = str(results.solver.status)
    lb = _finite(getattr(results.problem, "lower_bound", None))
    ub = _finite(getattr(results.problem, "upper_bound", None))
    if term in GOOD_TERMINATIONS:
        ok, msg = True, _TERM_TEXT.get(term, term)
    elif term in LIMIT_TERMINATIONS:
        ok = _has_values(built)
        msg = ("The solver stopped at a limit with a feasible solution. The solution can be not optimal."
               if ok else "The solver stopped at a limit before it found a feasible solution.")
    else:
        ok, msg = False, _TERM_TEXT.get(term, f"The solver stopped: {term}.")
    return RunInfo(ok, term, status, msg, wall, lb, ub, log=writer.all.getvalue())


_TERM_TEXT = {
    "optimal": "Optimal solution found.",
    "globallyOptimal": "Globally optimal solution found.",
    "locallyOptimal": "Locally optimal solution found. A better solution can exist.",
    "feasible": "Feasible solution found. It can be not optimal.",
    "infeasible": "The model is infeasible. No solution satisfies all constraints.",
    "unbounded": "The model is unbounded. The objective can improve without limit.",
    "infeasibleOrUnbounded": "The model is infeasible or unbounded.",
    "error": "The solver had an error. Read the log.",
}


def _has_values(built: Built) -> bool:
    for name in built.scenarios:
        reg = built.regs[name]
        for vname in built.var_names:
            for _, vd in _items(reg[vname]):
                if vd.value is not None:
                    return True
    return False


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

@dataclass
class ScenarioResult:
    name: str
    probability: float
    objective: float | None
    kpis: dict[str, float | None]
    values: dict[str, dict]
    expressions: dict[str, dict]
    constraints: list[dict]


@dataclass
class SolveResult:
    ok: bool
    termination: str
    status: str
    message: str
    solver: str
    wall_time: float
    sense: int
    objective_name: str
    objective: float | None          # deterministic: value; stochastic: expected value
    best_bound: float | None
    gap: float | None
    stats: dict
    stochastic: bool
    scenarios: list[ScenarioResult]
    risk: dict = field(default_factory=dict)
    max_violation: float | None = None
    first_stage: dict = field(default_factory=dict)
    log: str = ""
    built: Built | None = None
    analysis: dict | None = None
    label: str = ""

    def scenario(self, name: str | None) -> ScenarioResult:
        for sc in self.scenarios:
            if sc.name == name:
                return sc
        return self.scenarios[0]


def _val(x):
    try:
        return pyo.value(x, exception=False)
    except Exception:
        return None


def _collect(built: Built, spec: dict, run: RunInfo, opts: SolverOptions) -> SolveResult:
    stats = model_stats(built, spec)
    scen_results = []
    max_viol = 0.0 if run.ok else None
    has_duals = run.ok and built.model.component("dual") is not None
    for name in built.scenarios:
        reg = built.regs[name]
        values = {}
        exprs = {}
        rows = []
        kpis = {}
        if run.ok:
            for v in spec["variables"]:
                values[v["name"]] = {k: vd.value for k, vd in _items(reg[v["name"]])}
            for e in spec["expressions"]:
                exprs[e["name"]] = {k: _val(ed) for k, ed in _items(reg[e["name"]])}
            for o in spec["objectives"]:
                kpis[o["name"]] = _val(reg[o["name"]].expr)
            for c in spec["constraints"]:
                comp = reg[c["name"]]
                for k, cd in _items(comp):
                    body = _val(cd.body)
                    lo = _val(cd.lower) if cd.has_lb() else None
                    up = _val(cd.upper) if cd.has_ub() else None
                    slack = None
                    if body is not None:
                        cand = []
                        if lo is not None:
                            cand.append(body - lo)
                        if up is not None:
                            cand.append(up - body)
                        slack = min(cand) if cand else None
                        if comp.active and slack is not None and max_viol is not None:
                            max_viol = max(max_viol, -slack)
                    dual = None
                    if has_duals:
                        dual = built.model.dual.get(cd)
                    rows.append({"name": c["name"], "index": k, "body": body, "lower": lo,
                                 "upper": up, "slack": slack, "dual": dual,
                                 "active": bool(comp.active)})
        obj = kpis.get(built.objective_name) if run.ok else None
        scen_results.append(ScenarioResult(name, built.probs[name], obj, kpis, values, exprs, rows))

    objective = None
    risk_info = {}
    if run.ok:
        if built.stochastic:
            objective = sum(s.probability * (s.objective or 0.0) for s in scen_results)
            costs = [built.sense * (s.objective or 0.0) for s in scen_results]
            probs = [s.probability for s in scen_results]
            alpha = float(built.risk.get("alpha", 0.9) or 0.9)
            cv = cvar(costs, probs, alpha)
            risk_info = {
                "measure": built.risk.get("measure", "expected"),
                "alpha": alpha,
                "weight": float(built.risk.get("weight", 0.0) or 0.0),
                "cvar": built.sense * cv,
                "worst": max(costs) * built.sense,
                "best": min(costs) * built.sense,
                "optimized_value": _val(built.model.ef_objective),
            }
        else:
            objective = scen_results[0].objective
    bound = None
    if built.stochastic:
        b = run.lower_bound
        bound = None if b is None else b * built.sense
    else:
        bound = run.lower_bound if built.sense == 1 else run.upper_bound
    gap = None
    if objective is not None and bound is not None and stats["binary"] + stats["integer"] > 0:
        incumbent = objective if not built.stochastic else _val(built.model.ef_objective)
        ref = bound if not built.stochastic else run.lower_bound
        if incumbent is not None and ref is not None:
            gap = abs(incumbent - ref) / max(1e-10, abs(incumbent))
    first_stage = {}
    if run.ok and built.stochastic:
        s0 = scen_results[0]
        first_stage = {v: s0.values[v] for v in stage1_vars(spec)}
    return SolveResult(
        ok=run.ok, termination=run.termination, status=run.status, message=run.message,
        solver=opts.name, wall_time=run.wall_time, sense=built.sense,
        objective_name=built.objective_name, objective=objective, best_bound=bound, gap=gap,
        stats=stats, stochastic=built.stochastic, scenarios=scen_results, risk=risk_info,
        max_violation=max_viol, first_stage=first_stage, log=run.log, built=built,
    )


def cvar(costs: list[float], probs: list[float], alpha: float) -> float:
    """Exact CVaR of a discrete cost distribution (Rockafellar-Uryasev)."""
    if not costs:
        return float("nan")
    best = math.inf
    for eta in costs:
        val = eta + sum(p * max(0.0, c - eta) for c, p in zip(costs, probs)) / (1.0 - alpha)
        best = min(best, val)
    return best


def fix_values(built: Built, fixed: dict[str, dict]) -> None:
    """Fix variables (by name and key) in every scenario of *built*."""
    for name in built.scenarios:
        reg = built.regs[name]
        for vname, vals in fixed.items():
            comp = reg[vname]
            for k, vd in _items(comp):
                val = vals.get(k)
                if val is None:
                    continue
                if vd.is_binary() or vd.is_integer():
                    val = round(val)
                vd.fix(val)


def validate_or_raise(spec: dict) -> None:
    rep = S.validate(spec)
    if not rep.ok:
        raise EngineError("The model has errors:\n" + "\n".join(f"  - {i.where}: {i.message}" for i in rep.errors))


def solve(spec: dict, opts: SolverOptions | None = None, log: LogFn | None = None, *,
          deterministic: bool = False, params: dict | None = None,
          fixed: dict | None = None, risk: dict | None = None, label: str = "") -> SolveResult:
    """Validate, build and solve *spec*. Raise ``EngineError`` on problems."""
    validate_or_raise(spec)
    opts = opts or SolverOptions.from_spec(spec["solver"])
    if log:
        log(f"Building model '{spec.get('name')}'{' - ' + label if label else ''} ...")
    t0 = time.perf_counter()
    built = build(spec, params=params, deterministic=deterministic, risk=risk)
    if fixed:
        fix_values(built, fixed)
    stats = model_stats(built, spec)
    if log:
        log(f"Model built in {time.perf_counter() - t0:.2f} s: {stats['class']}, "
            f"{stats['variables']} variables ({stats['binary']} binary, {stats['integer']} integer), "
            f"{stats['constraints']} constraints, {stats['scenarios']} scenario(s).")
        log(f"Solving with {opts.name} ...")
    run = run_solver(built, opts, log)
    res = _collect(built, spec, run, opts)
    res.label = label
    if log:
        log(f"{run.message} ({run.termination}, {run.wall_time:.2f} s)")
        if res.objective is not None:
            log(f"Objective {res.objective_name} = {res.objective:.6g}")
    return res


def build_summary(spec: dict, pprint_limit: int = 200_000) -> tuple[dict, str]:
    """Build the model without a solve. Return statistics and a model listing."""
    validate_or_raise(spec)
    built = build(spec)
    stats = model_stats(built, spec)
    buf = io.StringIO()
    try:
        built.model.pprint(ostream=buf)
    except Exception as exc:  # pragma: no cover
        buf.write(f"(model listing not available: {exc})")
    text = buf.getvalue()
    if len(text) > pprint_limit:
        text = text[:pprint_limit] + f"\n... listing cut at {pprint_limit} characters ..."
    return stats, text


def write_model_file(spec: dict, path: str) -> None:
    """Write the built model to an LP, MPS, NL or GMS file (by extension)."""
    validate_or_raise(spec)
    built = build(spec)
    built.model.write(path, io_options={"symbolic_solver_labels": True})


# ---------------------------------------------------------------------------
# Stochastic analysis
# ---------------------------------------------------------------------------

def stochastic_analysis(spec: dict, opts: SolverOptions | None = None,
                        log: LogFn | None = None) -> dict:
    """Compute RP, WS, EV, EEV, EVPI and VSS (risk-neutral definitions).

    RP   recourse problem (extensive form, expected value)
    WS   wait-and-see: each scenario solved with perfect information
    EV   expected-value problem (mean data, one scenario)
    EEV  expected result of the EV first-stage plan in the real scenarios
    EVPI = RP - WS  (value of perfect information)
    VSS  = EEV - RP (value of the stochastic solution)
    (signs flip for a maximisation so that EVPI and VSS are not negative)
    """
    validate_or_raise(spec)
    if not spec["stochastic"].get("enabled"):
        raise EngineError("Turn on the stochastic model on the Uncertainty page first.")
    opts = opts or SolverOptions.from_spec(spec["solver"])
    sets = S.resolve_sets(spec)
    scen = S.scenario_data(spec, sets)
    stage1 = stage1_vars(spec)
    notes = []
    say = log or (lambda _s: None)

    say("== Step 1 of 4: recourse problem (RP), risk-neutral extensive form ==")
    neutral = {**spec["stochastic"].get("risk", {}), "measure": "expected", "weight": 0.0}
    rp = solve(spec, opts, log, risk=neutral, label="RP")
    if not rp.ok:
        raise EngineError(f"The recourse problem has no solution: {rp.message}")
    sense = rp.sense

    say("== Step 2 of 4: wait-and-see problems (WS) ==")
    ws_rows = []
    for name, prob, params in scen:
        r = solve(spec, opts, log, deterministic=True, params=params, label=f"WS {name}")
        ws_rows.append((name, prob, r.objective if r.ok else None, r.message))
    if any(o is None for _, _, o, _ in ws_rows):
        notes.append("One or more wait-and-see problems have no solution. WS and EVPI are not available.")
        ws = None
    else:
        ws = sum(p * o for _, p, o, _ in ws_rows)

    say("== Step 3 of 4: expected-value problem (EV) ==")
    ev_params = S.expected_params(spec, sets, scen)
    ev = solve(spec, opts, log, deterministic=True, params=ev_params, label="EV")
    ev_first = {}
    if ev.ok:
        ev_first = {v: ev.scenarios[0].values[v] for v in stage1}
    else:
        notes.append(f"The EV problem has no solution: {ev.message}")

    say("== Step 4 of 4: expected result of the EV plan (EEV) ==")
    eev_rows = []
    eev = None
    if ev.ok:
        if not stage1:
            notes.append("No first-stage variables: EEV is equal to WS by definition.")
        infeasible = False
        for name, prob, params in scen:
            r = solve(spec, opts, log, deterministic=True, params=params, fixed=ev_first,
                      label=f"EEV {name}")
            eev_rows.append((name, prob, r.objective if r.ok else None, r.message))
            if not r.ok:
                infeasible = True
        if infeasible:
            notes.append("The EV plan is infeasible in one or more scenarios: EEV is infinite "
                         "and the stochastic solution is necessary.")
            eev = math.inf * sense
        else:
            eev = sum(p * o for _, p, o, _ in eev_rows)

    rp_val = rp.objective
    evpi = None if ws is None else sense * (rp_val - ws)
    vss = None if eev is None else sense * (eev - rp_val)
    if (opts.mip_gap or 0) > 0 and rp.stats["binary"] + rp.stats["integer"] > 0:
        notes.append(f"The MIP gap is {opts.mip_gap:g}. Small negative EVPI or VSS values can come from the gap.")
    per = []
    ws_map = {n: o for n, _, o, _ in ws_rows}
    eev_map = {n: o for n, _, o, _ in eev_rows}
    for sc in rp.scenarios:
        per.append({"scenario": sc.name, "probability": sc.probability,
                    "rp": sc.objective, "ws": ws_map.get(sc.name), "eev": eev_map.get(sc.name)})
    out = {
        "RP": rp_val, "WS": ws, "EV": ev.objective if ev.ok else None, "EEV": eev,
        "EVPI": evpi, "VSS": vss, "sense": sense, "per_scenario": per,
        "ev_first_stage": ev_first, "notes": notes, "rp_result": rp,
    }
    rp.analysis = out
    say(f"RP = {_fmt(rp_val)}, WS = {_fmt(ws)}, EEV = {_fmt(eev)}, EVPI = {_fmt(evpi)}, VSS = {_fmt(vss)}")
    return out


def _fmt(x) -> str:
    if x is None:
        return "n/a"
    try:
        return f"{x:.6g}"
    except (TypeError, ValueError):
        return str(x)
