"""Export a spec as a standalone, readable Pyomo script.

The script needs only Pyomo and a solver. It contains the data, one
``build`` function with the model, the extensive form for a stochastic
model, the solve call and a short printout. Use it to run the model on a
server, to put it in version control or to learn Pyomo from your own model.
"""
from __future__ import annotations

import datetime as dt
import pprint
import textwrap

from . import spec as S
from .engine import OPTION_NAMES, SolverOptions, stage1_vars

HEADER = '''"""{name} - Pyomo model exported by Pyomo Studio on {date}.

{description}
Run:   python {fname}
Needs: pip install pyomo highspy   (or another solver)
"""
import math

import pyomo.environ as pyo
from pyomo.environ import exp, inequality, log, quicksum, sqrt, value  # noqa: F401

'''

HELPERS = '''

def which(component, *prefix, threshold=0.5):
    """Remaining index of the member of `component` that is on (> threshold)."""
    pre = tuple(prefix)
    hits = []
    for key in component.keys():
        k = key if isinstance(key, tuple) else (key,)
        if k[:len(pre)] == pre and (value(component[key], exception=False) or 0) > threshold:
            rest = k[len(pre):]
            hits.append(rest[0] if len(rest) == 1 else rest)
    if not hits:
        return None
    return hits[0] if len(hits) == 1 else hits


def num(x):
    return float(value(x))


def _relation(expr, name):
    """Skip a constraint that is always true; stop on one that is always false."""
    if isinstance(expr, bool):
        if expr:
            return pyo.Constraint.Skip
        raise ValueError(f"Constraint {name} is always false for the data.")
    return expr

'''


def _rule_args(items: list[S.IndexItem], dims: list[int]) -> tuple[str, list[str]]:
    """Return the argument list and the lines that rebuild tuple names."""
    args, pre = [], []
    for n, (it, d) in enumerate(zip(items, dims)):
        if not it.names:
            args.extend(f"_i{n}_{j}" for j in range(d))
        elif len(it.names) == 1 and d > 1:
            parts = [f"_{it.names[0]}_{j}" for j in range(d)]
            args.extend(parts)
            pre.append(f"{it.names[0]} = ({', '.join(parts)})")
        else:
            args.extend(it.names)
    return ", ".join(["_blk"] + args), pre


def _sets_args(items) -> str:
    return ", ".join(it.set_name for it in items)


def _indent(text: str, n: int) -> str:
    return textwrap.indent(text, " " * n)


def _param_literal(val) -> str:
    if isinstance(val, S.ParamTable):
        return pprint.pformat(dict(val.data), width=100, sort_dicts=False)
    return repr(float(val))


def generate(spec: dict, fname: str = "model.py") -> str:
    sets = S.resolve_sets(spec)
    dims = S.set_dims(spec, sets)
    base = S.resolve_params(spec, sets)
    stoch = bool(spec["stochastic"].get("enabled"))
    lines = [HEADER.format(name=spec.get("name", "Model"), date=f"{dt.date.today():%Y-%m-%d}",
                           description=(spec.get("description") or "").strip(), fname=fname)]
    lines.append("# " + "-" * 74 + "\n# Data\n# " + "-" * 74)
    lines.append("SETS = " + pprint.pformat({k: list(v) for k, v in sets.items()}, width=100, sort_dicts=False))
    lines.append("")
    lines.append("DEFAULTS = " + repr({n: v.default for n, v in base.items() if isinstance(v, S.ParamTable)}))
    lines.append("")
    lines.append("PARAMS = {")
    for n, v in base.items():
        lines.append(f"    {n!r}: " + _indent(_param_literal(v), 4).lstrip() + ",")
    lines.append("}")
    if stoch:
        lines.append("")
        lines.append("# Each scenario: (name, probability, parameter values that differ from PARAMS)")
        lines.append("SCENARIOS = [")
        for name, prob, params in S.scenario_data(spec, sets):
            diff = {}
            for n, v in params.items():
                bv = base[n]
                if isinstance(v, S.ParamTable):
                    if v.dense(sets) != bv.dense(sets):
                        diff[n] = v.dense(sets)
                elif v != bv:
                    diff[n] = v
            lines.append(f"    ({name!r}, {prob!r}, " + _indent(pprint.pformat(diff, width=90, sort_dicts=False), 8).lstrip() + "),")
        lines.append("]")
        lines.append(f"FIRST_STAGE = {stage1_vars(spec)!r}")
        risk = spec["stochastic"]["risk"]
        lines.append(f"RISK = {risk!r}")
    lines.append(HELPERS)
    lines.append("# " + "-" * 74 + "\n# Model\n# " + "-" * 74)
    lines.append("def build(_blk, _DATA):")
    lines.append('    """Add the model to block `_blk` with parameter data `_DATA`."""')
    lines.append("    m = model = _blk  # noqa: F841")
    if spec["sets"]:
        lines.append("    # Sets")
    for s in spec["sets"]:
        n = s["name"]
        doc = f"  # {s['description']}" if s.get("description") else ""
        lines.append(f"    _blk.{n} = pyo.Set(initialize=SETS[{n!r}], ordered=True, dimen={dims[n]}){doc}")
        lines.append(f"    {n} = _blk.{n}")
    if spec["params"]:
        lines.append("    # Parameters")
    for p in spec["params"]:
        n = p["name"]
        val = base[n]
        doc = f"  # {p['description']}" if p.get("description") else ""
        if isinstance(val, S.ParamTable):
            d = f", default=DEFAULTS[{n!r}]" if val.default is not None else ""
            lines.append(f"    _blk.{n} = pyo.Param({_sets_args(val.items)}, initialize=_DATA[{n!r}]{d}, "
                         f"within=pyo.Reals){doc}")
        else:
            lines.append(f"    _blk.{n} = pyo.Param(initialize=_DATA[{n!r}], within=pyo.Reals){doc}")
            lines.append(f"    {n} = float(_DATA[{n!r}])  # data is a plain number in expressions")
            continue
        lines.append(f"    {n} = _blk.{n}")
    if spec["variables"]:
        lines.append("    # Variables")
    for v in spec["variables"]:
        n = v["name"]
        items = S.parse_index(v.get("index", ""))
        idims = [dims[it.set_name] for it in items]
        args, pre = _rule_args(items, idims)
        extra = ""
        lb, ub, init = (str(v.get(k, "") or "").strip() for k in ("lb", "ub", "init"))
        if lb or ub:
            lines.append(f"    def {n}_bounds({args}):")
            for ln in pre:
                lines.append(f"        {ln}")
            lines.append(f"        return ({f'value({lb})' if lb else 'None'}, {f'value({ub})' if ub else 'None'})")
            extra += f", bounds={n}_bounds"
        if init:
            lines.append(f"    def {n}_init({args}):")
            for ln in pre:
                lines.append(f"        {ln}")
            lines.append(f"        return value({init})")
            extra += f", initialize={n}_init"
        idx = _sets_args(items) + ", " if items else ""
        stage = f"  # stage {v.get('stage', 2)}" if stoch else ""
        doc = f"  # {v['description']}" if v.get("description") else stage
        lines.append(f"    _blk.{n} = pyo.Var({idx}domain=pyo.{v.get('domain', 'Reals')}{extra}){doc}")
        lines.append(f"    {n} = _blk.{n}")
    for kind, label in (("expressions", "Expressions"), ("constraints", "Constraints")):
        if spec[kind]:
            lines.append(f"    # {label}")
        for c in spec[kind]:
            n = c["name"]
            items = S.parse_index(c.get("index", ""))
            idims = [dims[it.set_name] for it in items]
            args, pre = _rule_args(items, idims)
            if c.get("description"):
                lines.append(f"    # {c['description']}")
            lines.append(f"    def {n}_rule({args}):")
            for ln in pre:
                lines.append(f"        {ln}")
            if kind == "constraints":
                cond = (c.get("condition") or "").strip()
                if cond:
                    lines.append(f"        if not ({cond}):")
                    lines.append("            return pyo.Constraint.Skip")
                lines.append(f"        return _relation({c['expr'].strip()}, {n!r})")
                comp = "Constraint"
            else:
                lines.append(f"        return {c['expr'].strip()}")
                comp = "Expression"
            idx = _sets_args(items) + ", " if items else ""
            lines.append(f"    _blk.{n} = pyo.{comp}({idx}rule={n}_rule)")
            lines.append(f"    {n} = _blk.{n}")
            if kind == "constraints" and not c.get("active", True):
                lines.append(f"    _blk.{n}.deactivate()")
    if spec["objectives"]:
        lines.append("    # Objectives (only the active one is optimized)")
    for o in spec["objectives"]:
        n = o["name"]
        sense = "pyo.maximize" if o.get("sense") == "maximize" else "pyo.minimize"
        lines.append(f"    _blk.{n} = pyo.Objective(expr={o['expr'].strip()}, sense={sense})")
        if not o.get("active", True):
            lines.append(f"    _blk.{n}.deactivate()")
    hook = (spec.get("hook") or "").strip()
    if hook:
        lines.append("    # Custom hook")
        lines.append(_indent(hook, 4))
    lines.append("    return _blk")
    lines.append("")

    active = [o for o in spec["objectives"] if o.get("active", True)]
    obj_name = active[0]["name"] if active else None
    lines.append("")
    lines.append("# " + "-" * 74 + "\n# Solve\n# " + "-" * 74)
    if stoch:
        lines.append(textwrap.dedent(f'''\
        def build_extensive_form():
            m = pyo.ConcreteModel(name={spec.get('name', 'model')!r} + " (extensive form)")
            names = [s[0] for s in SCENARIOS]
            prob = {{s[0]: s[1] for s in SCENARIOS}}
            m.SCEN = pyo.Set(initialize=names, ordered=True)
            m.scen = pyo.Block(m.SCEN)
            for name, _p, diff in SCENARIOS:
                build(m.scen[name], {{**PARAMS, **diff}})
            sense = -1 if m.scen[names[0]].{obj_name}.sense == pyo.maximize else 1
            cost = {{}}
            for name in names:
                blk = m.scen[name]
                cost[name] = sense * blk.{obj_name}.expr
                for obj in blk.component_objects(pyo.Objective):
                    obj.deactivate()
            m.nonant = pyo.ConstraintList()   # first-stage decisions are equal in all scenarios
            first = m.scen[names[0]]
            for vname in FIRST_STAGE:
                base = first.component(vname)
                for other in names[1:]:
                    comp = m.scen[other].component(vname)
                    for k in base:
                        m.nonant.add(comp[k] == base[k])
            expected = sum(prob[n] * cost[n] for n in names)
            if RISK.get("measure") == "cvar" and float(RISK.get("weight", 0)) > 0:
                a, w = float(RISK["alpha"]), float(RISK["weight"])
                m.ef_eta = pyo.Var()
                m.ef_excess = pyo.Var(m.SCEN, domain=pyo.NonNegativeReals)
                m.ef_cvar = pyo.Constraint(m.SCEN, rule=lambda mm, s: mm.ef_excess[s] >= cost[s] - mm.ef_eta)
                cvar = m.ef_eta + sum(prob[n] * m.ef_excess[n] for n in names) / (1 - a)
                m.ef_objective = pyo.Objective(expr=(1 - w) * expected + w * cvar)
            else:
                m.ef_objective = pyo.Objective(expr=expected)
            return m, names, prob
        '''))
    opts = SolverOptions.from_spec(spec["solver"])
    tl, gp = OPTION_NAMES.get(opts.name, (None, None))
    lines.append("")
    lines.append('if __name__ == "__main__":')
    if stoch:
        lines.append("    m, names, prob = build_extensive_form()")
    else:
        lines.append(f"    m = build(pyo.ConcreteModel(name={spec.get('name', 'model')!r}), PARAMS)")
    lines.append(f"    opt = pyo.SolverFactory({opts.name!r})")
    if tl and opts.time_limit:
        lines.append(f"    opt.options[{tl!r}] = {opts.time_limit!r}")
    if gp and opts.mip_gap is not None:
        lines.append(f"    opt.options[{gp!r}] = {opts.mip_gap!r}")
    for k, v in opts.extra.items():
        lines.append(f"    opt.options[{k!r}] = {v!r}")
    lines.append("    results = opt.solve(m, tee=True)")
    lines.append('    print("Termination:", results.solver.termination_condition)')
    if stoch:
        lines.append("    for name in names:")
        lines.append(f'        print(f"Scenario {{name}} (p = {{prob[name]}}): {obj_name} =", value(m.scen[name].{obj_name}.expr))')
        lines.append("    blocks = [m.scen[n] for n in names]")
    else:
        lines.append(f'    print("{obj_name} =", value(m.{obj_name}))')
        lines.append("    blocks = [m]")
    var_names = [v["name"] for v in spec["variables"]]
    lines.append("    for blk in blocks:")
    lines.append(f"        for vname in {var_names!r}:")
    lines.append("            for k, vd in blk.component(vname).items():")
    lines.append("                if vd.value is not None and abs(vd.value) > 1e-9:")
    lines.append('                    print(f"  {blk.name}.{vname}[{k}] = {vd.value:.6g}")')
    lines.append("")
    return "\n".join(lines)
