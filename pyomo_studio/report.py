"""Plan reports: HTML, Markdown, CSV and JSON.

A report is first made as a list of neutral blocks (heading, paragraph,
key-value list, table, SVG, note). The HTML and Markdown writers render the
same blocks, so both formats always contain the same plan.
"""
from __future__ import annotations

import csv
import datetime as dt
import html
import io
import json
import math
from dataclasses import dataclass, field
from typing import Any

from . import spec as S
from .schedule import Schedule, format_duration, schedule_rows, schedule_svg

MAX_ROWS = 500


def fnum(x: Any, digits: int = 6) -> str:
    if x is None:
        return "-"
    if isinstance(x, str):
        return x
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return str(x)
    if math.isinf(xf):
        return "infinite" if xf > 0 else "-infinite"
    if math.isnan(xf):
        return "-"
    if abs(xf) < 1e-9:
        return "0"
    if abs(xf - round(xf)) < 1e-9 and abs(xf) < 1e12:
        return f"{int(round(xf)):,}"
    return f"{xf:,.{digits}g}"


@dataclass
class Block:
    kind: str                     # h1 h2 h3 p kv table svg note
    text: str = ""
    items: list = field(default_factory=list)
    headers: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    states: list = field(default_factory=list)   # per row: normal|warning|alarm|None
    level: str = "info"                          # note level: info|success|warning|error


def _kv(items) -> Block:
    return Block("kv", items=[(k, v) for k, v in items if v not in (None, "")])


def build_blocks(spec: dict, result, schedules: dict[str, Schedule | None],
                 analysis: dict | None = None, source: str = "") -> list[Block]:
    b: list[Block] = []
    name = spec.get("name") or "Model"
    b.append(Block("h1", f"Plan: {name}"))
    meta = f"Made {dt.datetime.now():%Y-%m-%d %H:%M} with Pyomo Studio"
    if source:
        meta += f" from {source}"
    b.append(Block("p", meta + "."))
    if spec.get("description"):
        b.append(Block("p", spec["description"]))

    b.append(Block("h2", "1. Summary"))
    level = "success" if result.ok and result.termination in ("optimal", "globallyOptimal") else (
        "warning" if result.ok else "error")
    b.append(Block("note", result.message, level=level))
    st = result.stats
    sense = "minimize" if result.sense == 1 else "maximize"
    obj_label = f"{result.objective_name} ({sense}{', expected value' if result.stochastic else ''})"
    b.append(_kv([
        ("Objective", f"{obj_label}: {fnum(result.objective)}" if result.ok else "no solution"),
        ("Best bound", fnum(result.best_bound) if result.best_bound is not None else None),
        ("Relative MIP gap", f"{result.gap:.4%}" if result.gap is not None else None),
        ("Solver", f"{result.solver}, {result.wall_time:.2f} s, termination '{result.termination}'"),
        ("Problem class", st.get("class")),
        ("Variables", f"{st['variables']:,} ({st['continuous']:,} continuous, {st['binary']:,} binary, "
                      f"{st['integer']:,} integer)"),
        ("Constraints", f"{st['constraints']:,}"),
        ("Scenarios", str(st.get("scenarios", 1)) if result.stochastic else None),
        ("Largest constraint violation", fnum(result.max_violation) if result.max_violation is not None else None),
    ]))
    if not result.ok:
        b.append(Block("p", "There is no plan because the solver found no solution. Read the solver log "
                            "and examine the constraints and the data."))
        b.extend(_formulation(spec))
        return b

    other = [o["name"] for o in spec["objectives"] if o["name"] != result.objective_name]
    if other:
        b.append(Block("h3", "Other objectives (reported, not optimized)"))
        headers = ["Scenario"] + other if result.stochastic else ["Measure", "Value"]
        rows = []
        if result.stochastic:
            for sc in result.scenarios:
                rows.append([sc.name] + [fnum(sc.kpis.get(o)) for o in other])
        else:
            rows = [[o, fnum(result.scenarios[0].kpis.get(o))] for o in other]
        b.append(Block("table", headers=headers, rows=rows))

    sec = 2
    if result.stochastic:
        b.append(Block("h2", f"{sec}. Decision under uncertainty"))
        sec += 1
        b.append(Block("p", "First-stage decisions are made now and are the same in all scenarios. "
                            "Second-stage decisions change with the scenario."))
        b.append(Block("h3", "First-stage plan (here and now)"))
        rows = []
        for vname, vals in result.first_stage.items():
            on = [(k, v) for k, v in vals.items() if v is not None and abs(v) > 1e-9]
            if not on:
                continue
            if all(abs(v - 1) < 1e-6 for _, v in on):
                text = ", ".join(f"({S.format_key(k)})" for k, _ in on[:120])
            else:
                text = ", ".join(f"{S.format_key(k)} = {fnum(v)}" for k, v in on[:120])
            if len(on) > 120:
                text += f", ... ({len(on) - 120} more)"
            rows.append([vname, str(len(on)), text])
        b.append(Block("table", headers=["Variable", "Not 0", "Index values (value 1 unless shown)"], rows=rows)
                 if rows else Block("p", "All first-stage variables are 0."))
        b.append(Block("h3", "Scenarios"))
        rows, states = [], []
        for sc in result.scenarios:
            sched = schedules.get(sc.name)
            k = sched.kpis if sched else {}
            alarms = k.get("alarms")
            state = "alarm" if alarms else ("warning" if k.get("warnings") else "normal")
            text = {"alarm": f"ALARM: {alarms} alarm(s)", "warning": f"WARNING: {k.get('warnings')} warning(s)",
                    "normal": "NORMAL"}[state]
            rows.append([sc.name, f"{sc.probability:.4g}", fnum(sc.objective),
                         fnum(k.get("late_count")), fnum(k.get("tardiness_total")),
                         fnum(k.get("wait_total")), fnum(k.get("warnings")), text if sched else "-"])
            states.append(state if sched else None)
        b.append(Block("table", headers=["Scenario", "Probability", "Objective", "Late tasks",
                                         "Total lateness", "Total wait", "Warnings", "State"],
                       rows=rows, states=states))
        r = result.risk
        b.append(_kv([
            ("Expected objective", fnum(result.objective)),
            (f"CVaR at alpha = {r.get('alpha', 0.9):g}", fnum(r.get("cvar"))),
            ("Worst scenario", fnum(r.get("worst"))),
            ("Best scenario", fnum(r.get("best"))),
            ("Optimized measure", "expected value" if r.get("measure") != "cvar" or not r.get("weight")
             else f"(1 - {r['weight']:g}) x expected + {r['weight']:g} x CVaR = {fnum(r.get('optimized_value'))}"),
        ]))
        if analysis:
            b.extend(_analysis_blocks(analysis))

    for sc in result.scenarios:
        sched = schedules.get(sc.name)
        if sched is None:
            continue
        title = "Schedule" + (f" - scenario {sc.name}" if result.stochastic else "")
        b.append(Block("h2", f"{sec}. {title}"))
        sec += 1
        b.extend(_schedule_blocks(sched))

    b.append(Block("h2", f"{sec}. Decision variables"))
    sec += 1
    b.append(Block("p", "The table shows values that are not 0."))
    b.extend(_values_block(spec, result))
    if spec["expressions"]:
        b.append(Block("h2", f"{sec}. Named expressions"))
        sec += 1
        b.extend(_values_block(spec, result, kind="expressions"))
    b.append(Block("h2", f"{sec}. Binding constraints"))
    sec += 1
    b.extend(_binding_block(result))
    b.extend(_formulation(spec, number=sec))
    return b


def _analysis_blocks(a: dict) -> list[Block]:
    out = [Block("h3", "Value of the stochastic solution")]
    out.append(_kv([
        ("RP - recourse problem (stochastic plan)", fnum(a.get("RP"))),
        ("WS - wait and see (perfect information)", fnum(a.get("WS"))),
        ("EV - expected-value problem (mean data)", fnum(a.get("EV"))),
        ("EEV - mean-data plan in the real scenarios", fnum(a.get("EEV"))),
        ("EVPI - value of perfect information", fnum(a.get("EVPI"))),
        ("VSS - value of the stochastic solution", fnum(a.get("VSS"))),
    ]))
    out.append(Block("p", "EVPI is the most you can pay for a perfect forecast. VSS is what you gain "
                          "when you plan with the scenarios and not with mean data."))
    rows = [[r["scenario"], f"{r['probability']:.4g}", fnum(r.get("rp")), fnum(r.get("ws")),
             fnum(r.get("eev"))] for r in a.get("per_scenario", [])]
    out.append(Block("table", headers=["Scenario", "Probability", "RP", "WS", "EEV"], rows=rows))
    for n in a.get("notes", []):
        out.append(Block("note", n, level="warning"))
    return out


def _schedule_blocks(sched: Schedule) -> list[Block]:
    out = []
    k = sched.kpis
    u = sched.unit
    out.append(_kv([
        ("Tasks", fnum(k.get("tasks"))),
        ("First event", sched.clock(k.get("first_event"))),
        ("Plan end", sched.clock(k.get("plan_end"))),
        ("Span", format_duration(k.get("span"), u)),
        ("Total wait", format_duration(k.get("wait_total"), u) if "wait_total" in k else None),
        ("Mean wait", format_duration(k.get("wait_mean"), u) if "wait_mean" in k else None),
        ("Longest wait", format_duration(k.get("wait_max"), u) if "wait_max" in k else None),
        ("Late tasks", fnum(k.get("late_count")) if "late_count" in k else None),
        ("Total lateness", format_duration(k.get("tardiness_total"), u) if "tardiness_total" in k else None),
        ("Space-time use", f"{k['space_time_utilization']:.1%}" if "space_time_utilization" in k else None),
        ("Alarms / warnings", f"{k.get('alarms', 0)} / {k.get('warnings', 0)}"),
    ]))
    out.append(Block("svg", schedule_svg(sched, 1100)))
    exc = [t for t in sched.tasks if t.state != "normal"]
    out.append(Block("h3", "Exceptions"))
    if exc:
        exc.sort(key=lambda t: (t.state != "alarm", t.start))
        out.append(Block("table", headers=["Priority", "Task", "Resource", "Condition"],
                         rows=[["1 - Alarm" if t.state == "alarm" else "2 - Warning", t.label, t.resource,
                                "; ".join(t.reasons)] for t in exc],
                         states=[t.state for t in exc]))
    else:
        out.append(Block("note", "No abnormal conditions. All tasks are on time and in limits.", level="success"))
    out.append(Block("h3", "Plan by resource"))
    rk = sched.resource_kpis
    out.append(Block("table", headers=["Resource", "Tasks", "Busy", "Utilization", "First start", "Last end"],
                     rows=[[r, fnum(v["tasks"]), format_duration(v["busy"], u), f"{v['utilization']:.1%}",
                            sched.clock(v["first"]), sched.clock(v["last"])] for r, v in rk.items()]))
    space = sched.kind == "space_time"
    for res, lst in sched.by_resource().items():
        if not lst:
            continue
        if len(sched.resources) > 1 or sched.resources[0] != "All":
            out.append(Block("h3", f"{res}"))
        headers = ["#", "Task", "Start", "End", "Duration"]
        if space:
            headers += [sched.space_label, "Size"]
        headers += ["Release", "Wait", "Due", "Late by", "State"]
        rows, states = [], []
        for i, t in enumerate(lst, 1):
            row = [str(i), t.label, sched.clock(t.start), sched.clock(t.end), format_duration(t.duration, u)]
            if space:
                row += [fnum(t.position), fnum(t.size)]
            row += [sched.clock(t.release), format_duration(t.wait, u), sched.clock(t.due),
                    format_duration(t.tardiness, u),
                    t.state.upper() + (": " + "; ".join(t.reasons) if t.reasons else "")]
            rows.append(row)
            states.append(t.state)
        out.append(Block("table", headers=headers, rows=rows, states=states))
    return out


def _values_block(spec: dict, result, kind: str = "variables") -> list[Block]:
    names = [v["name"] for v in spec[kind]]
    scen = result.scenarios
    multi = result.stochastic
    headers = ["Name", "Index"] + ([s.name for s in scen] if multi else ["Value"])
    rows = []
    for n in names:
        src = [(s.values if kind == "variables" else s.expressions).get(n, {}) for s in scen]
        keys = list(src[0].keys()) if src else []
        for k in keys:
            vals = [d.get(k) for d in src]
            if all(v is None or abs(v) < 1e-9 for v in vals):
                continue
            rows.append([n, S.format_key(k)] + [fnum(v) for v in (vals if multi else vals[:1])])
    if not rows:
        return [Block("p", "All values are 0.")]
    out = [Block("table", headers=headers, rows=rows[:MAX_ROWS])]
    if len(rows) > MAX_ROWS:
        out.append(Block("note", f"The table shows the first {MAX_ROWS} of {len(rows)} rows. "
                                 "Export the values to CSV to see all rows.", level="info"))
    return out


def _binding_block(result) -> list[Block]:
    rows = []
    multi = result.stochastic
    for sc in result.scenarios:
        for r in sc.constraints:
            if r["active"] and r["slack"] is not None and abs(r["slack"]) <= 1e-6:
                row = ([sc.name] if multi else []) + [r["name"], S.format_key(r["index"]), fnum(r["body"]),
                                                      fnum(r["lower"]), fnum(r["upper"])]
                if r["dual"] is not None:
                    row.append(fnum(r["dual"]))
                rows.append(row)
    if not rows:
        return [Block("p", "No constraint is binding.")]
    headers = (["Scenario"] if multi else []) + ["Constraint", "Index", "Activity", "Lower", "Upper"]
    if len(rows[0]) > len(headers):
        headers.append("Dual")
    out = [Block("p", f"{len(rows)} constraints are binding (slack is 0). They limit the solution.")]
    out.append(Block("table", headers=headers, rows=rows[:MAX_ROWS]))
    return out


def _formulation(spec: dict, number: int | None = None) -> list[Block]:
    title = "Model formulation" if number is None else f"{number}. Model formulation"
    out = [Block("h2", title)]
    try:
        sets = S.resolve_sets(spec)
    except S.SpecError:
        sets = {}
    out.append(Block("table", headers=["Set", "Size", "Elements"],
                     rows=[[s["name"], str(len(sets.get(s["name"], []))),
                            _short(", ".join(S.format_element(e) if not isinstance(e, tuple)
                                             else f"({S.format_element(e)})" for e in sets.get(s["name"], [])))]
                           for s in spec["sets"]]))
    out.append(Block("table", headers=["Parameter", "Index", "Description"],
                     rows=[[p["name"], p.get("index") or "-", p.get("description", "")] for p in spec["params"]]))
    out.append(Block("table", headers=["Variable", "Index", "Domain", "Stage", "Description"],
                     rows=[[v["name"], v.get("index") or "-", v.get("domain", ""),
                            "1st" if int(v.get("stage", 2)) == 1 else "2nd", v.get("description", "")]
                           for v in spec["variables"]]))
    out.append(Block("table", headers=["Constraint", "For all", "Condition", "Expression"],
                     rows=[[c["name"] + ("" if c.get("active", True) else " (off)"), c.get("index") or "-",
                            c.get("condition") or "-", c["expr"]] for c in spec["constraints"]]))
    out.append(Block("table", headers=["Objective", "Sense", "Expression"],
                     rows=[[o["name"] + (" (active)" if o.get("active", True) else ""), o.get("sense"), o["expr"]]
                           for o in spec["objectives"]]))
    return out


def _short(text: str, n: int = 160) -> str:
    return text if len(text) <= n else text[:n - 3] + "..."


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

CSS = """
:root{--bg:#f3f3f3;--card:#ffffffb3;--stroke:#0000000f;--text:#1a1a1a;--text2:#5d5d5d;
--accent:#005fb8;--div:#00000014;--ok-bg:#dff6dd;--ok-fg:#0f7b0f;--warn-bg:#fff4ce;--warn-fg:#9d5d00;
--err-bg:#fde7e9;--err-fg:#c42b1c;--info-bg:#f6f6f6;--alarm:#e00012;--warning:#f2b400}
@media (prefers-color-scheme:dark){:root{--bg:#202020;--card:#ffffff0d;--stroke:#00000033;--text:#fff;
--text2:#cfcfcf;--accent:#60cdff;--div:#ffffff15;--ok-bg:#393d1b;--ok-fg:#6ccb5f;--warn-bg:#433519;
--warn-fg:#fce100;--err-bg:#442726;--err-fg:#ff99a4;--info-bg:#2b2b2b}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
font:14px/20px "Segoe UI Variable Text","Segoe UI",system-ui,sans-serif}
main{max-width:1180px;margin:0 auto;padding:28px 24px 64px}
h1{font:600 28px/36px "Segoe UI Variable Display","Segoe UI",system-ui,sans-serif;margin:0 0 4px}
h2{font:600 20px/28px "Segoe UI Variable Display","Segoe UI",system-ui,sans-serif;margin:32px 0 12px}
h3{font:600 14px/20px "Segoe UI Variable Text","Segoe UI",system-ui,sans-serif;margin:20px 0 8px}
p{margin:6px 0 10px;color:var(--text2)}
.card{background:var(--card);border:1px solid var(--stroke);border-radius:8px;padding:12px 16px;margin:8px 0}
dl{display:grid;grid-template-columns:max-content 1fr;gap:6px 24px;margin:0}
dt{color:var(--text2)}dd{margin:0;font-variant-numeric:tabular-nums}
.tbl{overflow-x:auto;background:var(--card);border:1px solid var(--stroke);border-radius:8px;margin:8px 0}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th{text-align:left;font-weight:600;color:var(--text2);padding:8px 12px;border-bottom:1px solid var(--div);white-space:nowrap}
td{padding:6px 12px;border-bottom:1px solid var(--div);vertical-align:top}
tr:last-child td{border-bottom:0}
td.st-alarm{background:var(--alarm);color:#fff;font-weight:600}
td.st-warning{background:var(--warning);color:#1a1a1a;font-weight:600}
td.st-normal{color:var(--text2)}
.note{border-radius:4px;padding:10px 14px;margin:8px 0;border:1px solid var(--stroke)}
.note.success{background:var(--ok-bg)}.note.success b{color:var(--ok-fg)}
.note.warning{background:var(--warn-bg)}.note.warning b{color:var(--warn-fg)}
.note.error{background:var(--err-bg)}.note.error b{color:var(--err-fg)}
.note.info{background:var(--info-bg)}
.svg{overflow-x:auto;border-radius:8px;border:1px solid var(--stroke);margin:8px 0;background:#dcdcdc}
.svg svg{display:block;max-width:100%;height:auto}
@media print{body{background:#fff;color:#000}.card,.tbl{background:#fff}main{max-width:none}}
"""

_NOTE_LABEL = {"success": "Done", "warning": "Caution", "error": "Error", "info": "Note"}


def to_html(blocks: list[Block], title: str = "Plan") -> str:
    out = ["<!doctype html><html lang='en'><head><meta charset='utf-8'>",
           "<meta name='viewport' content='width=device-width,initial-scale=1'>",
           f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body><main>"]
    for b in blocks:
        if b.kind in ("h1", "h2", "h3"):
            out.append(f"<{b.kind}>{html.escape(b.text)}</{b.kind}>")
        elif b.kind == "p":
            out.append(f"<p>{html.escape(b.text)}</p>")
        elif b.kind == "note":
            out.append(f"<div class='note {b.level}'><b>{_NOTE_LABEL.get(b.level, 'Note')}:</b> "
                       f"{html.escape(b.text)}</div>")
        elif b.kind == "kv":
            items = "".join(f"<dt>{html.escape(str(k))}</dt><dd>{html.escape(str(v))}</dd>" for k, v in b.items)
            out.append(f"<div class='card'><dl>{items}</dl></div>")
        elif b.kind == "svg":
            out.append(f"<div class='svg'>{b.text}</div>")
        elif b.kind == "table":
            head = "".join(f"<th>{html.escape(str(h))}</th>" for h in b.headers)
            body = []
            for i, row in enumerate(b.rows):
                st = b.states[i] if i < len(b.states) else None
                cells = []
                for j, c in enumerate(row):
                    cls = f" class='st-{st}'" if st and j == len(row) - 1 and _is_state_col(b.headers) else ""
                    cells.append(f"<td{cls}>{html.escape(str(c))}</td>")
                body.append("<tr>" + "".join(cells) + "</tr>")
            out.append(f"<div class='tbl'><table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>")
    out.append("</main></body></html>")
    return "\n".join(out)


def _is_state_col(headers: list) -> bool:
    return bool(headers) and str(headers[-1]) in ("State", "Condition")


def to_markdown(blocks: list[Block]) -> str:
    out = []
    for b in blocks:
        if b.kind == "h1":
            out.append(f"# {b.text}\n")
        elif b.kind == "h2":
            out.append(f"## {b.text}\n")
        elif b.kind == "h3":
            out.append(f"### {b.text}\n")
        elif b.kind == "p":
            out.append(b.text + "\n")
        elif b.kind == "note":
            out.append(f"> **{_NOTE_LABEL.get(b.level, 'Note')}:** {b.text}\n")
        elif b.kind == "kv":
            out.append("\n".join(f"- **{k}:** {v}" for k, v in b.items) + "\n")
        elif b.kind == "svg":
            out.append("*(The schedule graphic is in the HTML report.)*\n")
        elif b.kind == "table":
            esc = lambda s: str(s).replace("|", "\\|")  # noqa: E731
            out.append("| " + " | ".join(esc(h) for h in b.headers) + " |")
            out.append("|" + "|".join("---" for _ in b.headers) + "|")
            for row in b.rows:
                out.append("| " + " | ".join(esc(c) for c in row) + " |")
            out.append("")
    return "\n".join(out)


def schedule_csv(schedules: dict[str, Schedule | None]) -> str:
    buf = io.StringIO()
    rows = []
    for name, sched in schedules.items():
        if sched is None:
            continue
        for r in schedule_rows(sched):
            rows.append({"scenario": name, **r})
    if not rows:
        return ""
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def values_csv(spec: dict, result) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["scenario", "kind", "name", "index", "value"])
    for sc in result.scenarios:
        for kind, src in (("variable", sc.values), ("expression", sc.expressions)):
            for name, vals in src.items():
                for k, v in vals.items():
                    w.writerow([sc.name, kind, name, S.format_key(k), "" if v is None else repr(float(v))])
    return buf.getvalue()


def result_json(result, schedules: dict | None = None) -> str:
    def key(k):
        return S.format_key(k)
    data = {
        "ok": result.ok, "termination": result.termination, "message": result.message,
        "solver": result.solver, "wall_time": result.wall_time, "objective_name": result.objective_name,
        "objective": result.objective, "best_bound": result.best_bound, "gap": result.gap,
        "stats": result.stats, "stochastic": result.stochastic, "risk": result.risk,
        "scenarios": [{
            "name": sc.name, "probability": sc.probability, "objective": sc.objective, "kpis": sc.kpis,
            "values": {n: {key(k): v for k, v in vals.items()} for n, vals in sc.values.items()},
            "expressions": {n: {key(k): v for k, v in vals.items()} for n, vals in sc.expressions.items()},
        } for sc in result.scenarios],
    }
    if result.analysis:
        data["analysis"] = {k: v for k, v in result.analysis.items() if k not in ("rp_result", "ev_first_stage")}
    if schedules:
        data["schedules"] = {n: schedule_rows(s) for n, s in schedules.items() if s is not None}
    return json.dumps(data, indent=2, default=str)


def make_report(spec: dict, result, schedules: dict, analysis: dict | None = None,
                source: str = "") -> tuple[str, str]:
    """Return ``(html, markdown)`` for one solve."""
    blocks = build_blocks(spec, result, schedules, analysis, source)
    return to_html(blocks, f"Plan - {spec.get('name', 'model')}"), to_markdown(blocks)
