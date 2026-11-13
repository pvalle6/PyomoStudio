"""Schedule view: turn a solved model into a plan, and draw it.

The *schedule view* in a spec maps model results to tasks:

    tasks     "v in V"                      one task per vessel
    resource  "which(x, v)"                 the berth (Gantt row)
    start     "t[v]"
    duration  "sum(p[v, b] * x[v, b] for b in B)"
    release   "a[v]"                        arrival (earliest start)
    due       "d[v]"                        requested departure

Each field is a Python expression in the same language as the model.

The graphic follows ISA-101 (high-performance HMI): a gray background,
gray bars for normal tasks and color only for abnormal states. Red with a
priority-1 square shows an alarm (late task or overlap); amber with a
priority-2 triangle shows a warning (wait above the warning limit). Text
labels repeat every state, so the plan does not depend on color.

The layout code makes renderer-neutral primitives. ``to_svg`` writes them as
SVG for reports; the desktop interface paints the same primitives with Qt.
"""
from __future__ import annotations

import datetime as dt
import html
import math
from dataclasses import dataclass, field
from typing import Any, Callable

from . import spec as S

# ISA-101 display palette. Color is kept for abnormal states only.
ISA = {
    "bg": "#DCDCDC",
    "row_alt": "#D3D3D3",
    "grid": "#C4C4C4",
    "axis": "#5E5E5E",
    "text": "#1A1A1A",
    "text_dim": "#474747",
    "bar": "#B4B4B4",
    "bar_edge": "#5A5A5A",
    "wait": "#6E6E6E",
    "marker": "#3F3F3F",
    "alarm": "#E00012",
    "alarm_text": "#FFFFFF",
    "warning": "#F2B400",
    "warning_text": "#1A1A1A",
}
FONT = "Segoe UI Variable Text, Segoe UI, Arial, sans-serif"


class ScheduleError(Exception):
    pass


@dataclass
class Task:
    key: Any
    label: str
    resource: str
    start: float
    duration: float
    release: float | None = None
    due: float | None = None
    position: float | None = None
    size: float | None = None
    state: str = "normal"            # normal | warning | alarm
    reasons: list[str] = field(default_factory=list)

    @property
    def end(self) -> float:
        return self.start + self.duration

    @property
    def wait(self) -> float | None:
        return None if self.release is None else _clean(self.start - self.release)

    @property
    def tardiness(self) -> float | None:
        return None if self.due is None else _clean(self.end - self.due)


def _clean(x: float) -> float:
    """Clip solver noise: negative or tiny values become 0."""
    return 0.0 if x < 1e-7 else x


@dataclass
class Schedule:
    kind: str
    tasks: list[Task]
    resources: list[str]
    unit: str
    origin: dt.datetime | None
    space_label: str = "Position"
    space_max: float | None = None
    kpis: dict = field(default_factory=dict)
    resource_kpis: dict = field(default_factory=dict)
    messages: list[str] = field(default_factory=list)

    def clock(self, t: float | None) -> str:
        return format_time(t, self.unit, self.origin)

    def by_resource(self) -> dict[str, list[Task]]:
        out: dict[str, list[Task]] = {r: [] for r in self.resources}
        for t in sorted(self.tasks, key=lambda x: (x.start, x.label)):
            out.setdefault(t.resource, []).append(t)
        return out


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------

_UNIT_SECONDS = {"s": 1, "sec": 1, "min": 60, "h": 3600, "hr": 3600, "hour": 3600,
                 "d": 86400, "day": 86400}


def parse_origin(text: str) -> dt.datetime | None:
    text = (text or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ScheduleError(f"Time origin '{text}' is not a date. Write it as 2026-11-12 06:00.")


def format_time(t: float | None, unit: str, origin: dt.datetime | None, short: bool = False) -> str:
    if t is None:
        return ""
    if origin is not None and unit in _UNIT_SECONDS:
        when = origin + dt.timedelta(seconds=t * _UNIT_SECONDS[unit])
        return when.strftime("%a %H:%M" if short else "%a %d %b %H:%M")
    return f"{t:.4g} {unit}".strip()


def format_duration(d: float | None, unit: str) -> str:
    if d is None:
        return ""
    if abs(d) < 1e-6:
        d = 0.0
    return f"{d:.4g} {unit}".strip()


# ---------------------------------------------------------------------------
# Compute
# ---------------------------------------------------------------------------

def _num(x) -> float:
    from . import engine
    return float(engine.pyo.value(x))


def compute_schedule(spec: dict, built, scenario: str | None = None) -> Schedule | None:
    """Evaluate the schedule view for one scenario of a solved model."""
    sv = spec.get("schedule") or {}
    kind = sv.get("type", "none")
    if kind not in ("gantt", "space_time"):
        return None
    scen = scenario if scenario in built.envs else built.scenarios[0]
    env = built.envs[scen]
    sets = built.sets
    try:
        items = S.parse_index(sv.get("tasks", ""))
    except S.SpecError as exc:
        raise ScheduleError(f"Schedule view tasks: {exc.message}") from None
    if not items:
        raise ScheduleError("Schedule view: write the task index, for example 'v in V'.")

    def comp(field_name: str, required: bool = False):
        text = str(sv.get(field_name, "") or "").strip()
        if not text:
            if required:
                raise ScheduleError(f"Schedule view: the field '{field_name}' is empty.")
            return None
        try:
            return S.compile_expr(text, f"schedule {field_name}")
        except S.SpecError as exc:
            raise ScheduleError(str(exc)) from None

    codes = {f: comp(f, f in ("start", "duration")) for f in
             ("condition", "label", "resource", "start", "duration", "release", "due", "position", "size")}
    if kind == "space_time":
        for f in ("position", "size"):
            if codes[f] is None:
                raise ScheduleError(f"Schedule view: a space-time view needs the field '{f}'.")

    def ev(code, bind, what, key):
        local = dict(env)
        local.update(bind)
        try:
            return eval(code, local)  # noqa: S307 - trusted model code
        except Exception as exc:
            raise ScheduleError(f"Schedule {what} at task ({S.format_key(key)}): "
                                f"{type(exc).__name__}: {exc}") from None

    tasks: list[Task] = []
    for key, bind in S.iter_index(items, sets):
        if codes["condition"] is not None and not ev(codes["condition"], bind, "condition", key):
            continue
        label = ev(codes["label"], bind, "label", key) if codes["label"] else S.format_key(key)
        res = ev(codes["resource"], bind, "resource", key) if codes["resource"] else "All"
        if res is None:
            continue  # task not scheduled in this solution
        if isinstance(res, list):
            res = res[0]
        t = Task(key=key, label=str(label), resource=S.format_key(res) if not isinstance(res, str) else res,
                 start=_num(ev(codes["start"], bind, "start", key)),
                 duration=_num(ev(codes["duration"], bind, "duration", key)))
        for f in ("release", "due", "position", "size"):
            if codes[f] is not None:
                setattr(t, f, _num(ev(codes[f], bind, f, key)))
        tasks.append(t)

    origin = parse_origin(sv.get("time_origin", ""))
    space_max = None
    if str(sv.get("space_max", "") or "").strip():
        code = comp("space_max")
        space_max = _num(ev(code, {}, "space_max", None))
    sched = Schedule(kind, tasks, _resource_order(tasks, sets), sv.get("time_unit", "h") or "",
                     origin, sv.get("space_label", "Position") or "Position", space_max)
    _assess(sched, sv)
    return sched


def _resource_order(tasks: list[Task], sets: dict) -> list[str]:
    used = {t.resource for t in tasks}
    best = None
    for elements in sets.values():
        labels = [S.format_key(e) if not isinstance(e, str) else e for e in elements]
        if used and used.issubset(labels) and len(labels) <= 200:
            if best is None or len(labels) < len(best):
                best = labels
    if best:
        return best
    return sorted(used, key=_natural)


def _natural(s: str):
    import re
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", s)]


def _to_float(text, default=None):
    try:
        return float(text) if str(text).strip() != "" else default
    except (TypeError, ValueError):
        return default


def _assess(sched: Schedule, sv: dict) -> None:
    """Find abnormal states and compute KPIs."""
    wait_warn = _to_float(sv.get("wait_warning"))
    late_tol = _to_float(sv.get("late_tolerance"), 1e-3) or 1e-3
    unit = sched.unit
    for t in sched.tasks:
        t.state, t.reasons = "normal", []
        if t.tardiness is not None and t.tardiness > late_tol:
            t.state = "alarm"
            t.reasons.append(f"Late by {format_duration(t.tardiness, unit)}")
        if wait_warn is not None and t.wait is not None and t.wait > wait_warn + 1e-9:
            if t.state != "alarm":
                t.state = "warning"
            t.reasons.append(f"Waits {format_duration(t.wait, unit)} (limit {format_duration(wait_warn, unit)})")
    # Overlap check (a model error, so an alarm).
    eps = 1e-6
    if sched.kind == "gantt":
        for res, lst in sched.by_resource().items():
            for a, b in zip(lst, lst[1:]):
                if b.start < a.end - eps:
                    for x, y in ((a, b), (b, a)):
                        x.state = "alarm"
                        x.reasons.append(f"Overlaps {y.label} on {res}")
    else:
        ts = sched.tasks
        for i, a in enumerate(ts):
            for b in ts[i + 1:]:
                if (a.start < b.end - eps and b.start < a.end - eps and
                        a.position < b.position + b.size - eps and b.position < a.position + a.size - eps):
                    for x, y in ((a, b), (b, a)):
                        x.state = "alarm"
                        x.reasons.append(f"Overlaps {y.label} in time and space")
    if not sched.tasks:
        sched.kpis = {"tasks": 0}
        return
    first = min(min(t.start for t in sched.tasks),
                min((t.release for t in sched.tasks if t.release is not None), default=math.inf))
    last = max(t.end for t in sched.tasks)
    span = max(last - first, 1e-9)
    waits = [t.wait for t in sched.tasks if t.wait is not None]
    tard = [t.tardiness for t in sched.tasks if t.tardiness is not None]
    k = {
        "tasks": len(sched.tasks),
        "first_event": first,
        "plan_end": last,
        "span": last - first,
        "busy_total": sum(t.duration for t in sched.tasks),
        "alarms": sum(t.state == "alarm" for t in sched.tasks),
        "warnings": sum(t.state == "warning" for t in sched.tasks),
    }
    if waits:
        k.update(wait_total=sum(waits), wait_mean=sum(waits) / len(waits), wait_max=max(waits))
    if tard:
        k.update(late_count=sum(x > late_tol for x in tard), tardiness_total=sum(tard),
                 tardiness_max=max(tard))
    sched.kpis = k
    rk = {}
    for res, lst in sched.by_resource().items():
        busy = sum(t.duration for t in lst)
        rk[res] = {"tasks": len(lst), "busy": busy, "utilization": busy / span,
                   "first": min((t.start for t in lst), default=None),
                   "last": max((t.end for t in lst), default=None)}
    sched.resource_kpis = rk
    if sched.kind == "space_time" and sched.space_max:
        area = sum(t.duration * (t.size or 0) for t in sched.tasks)
        k["space_time_utilization"] = area / (span * sched.space_max)
        for v in rk.values():  # many tasks share the space: use the area, not the busy time
            v["utilization"] = k["space_time_utilization"]


# ---------------------------------------------------------------------------
# Layout primitives
# ---------------------------------------------------------------------------

@dataclass
class Prim:
    kind: str                        # rect | line | poly | text
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    points: list = field(default_factory=list)
    fill: str | None = None
    stroke: str | None = None
    width: float = 1.0
    dash: bool = False
    text: str = ""
    size: float = 12.0
    bold: bool = False
    anchor: str = "start"            # start | middle | end
    color: str = ISA["text"]
    tip: str = ""
    task: int | None = None


def nice_ticks(lo: float, hi: float, target: int) -> list[float]:
    if hi <= lo:
        return [lo]
    raw = (hi - lo) / max(1, target)
    mag = 10 ** math.floor(math.log10(raw))
    step = mag
    for f in (1, 2, 2.5, 5, 10):
        if raw <= f * mag:
            step = f * mag
            break
    start = math.ceil(lo / step) * step
    out = []
    v = start
    while v <= hi + 1e-9 * step:
        out.append(round(v, 10))
        v += step
    return out


def _time_ticks(lo, hi, plot_w, sched: Schedule) -> list[float]:
    target = max(2, int(plot_w / 95))
    if sched.origin is not None and sched.unit in ("h", "hr", "hour"):
        # Align to whole hours: 1, 2, 3, 4, 6, 12, 24, 48 ...
        span = hi - lo
        for step in (1, 2, 3, 4, 6, 12, 24, 48, 72, 168):
            if span / step <= target:
                break
        offset = sched.origin.hour + sched.origin.minute / 60
        start = math.ceil((lo + offset) / step) * step - offset
        out, v = [], start
        while v <= hi + 1e-9:
            out.append(v)
            v += step
        return out
    return nice_ticks(lo, hi, target)


def _tooltip(t: Task, sched: Schedule) -> str:
    u = sched.unit
    lines = [t.label, f"Resource: {t.resource}",
             f"Start: {sched.clock(t.start)}", f"End: {sched.clock(t.end)}",
             f"Duration: {format_duration(t.duration, u)}"]
    if t.release is not None:
        lines.append(f"Release: {sched.clock(t.release)}  (wait {format_duration(t.wait, u)})")
    if t.due is not None:
        lines.append(f"Due: {sched.clock(t.due)}  (late {format_duration(t.tardiness, u)})")
    if t.position is not None:
        lines.append(f"{sched.space_label}: {t.position:.4g} to {t.position + (t.size or 0):.4g}")
    lines.append("State: " + t.state.upper() + (" - " + "; ".join(t.reasons) if t.reasons else ""))
    return "\n".join(lines)


def _text_width(text: str, size: float) -> float:
    return len(text) * size * 0.56


def _indicator(prims: list, x: float, y: float, state: str, task: int | None, tip: str) -> None:
    """ISA-101 alarm indicator: red square '1' (alarm), amber triangle '2' (warning)."""
    if state == "alarm":
        prims.append(Prim("rect", x, y, 14, 14, fill=ISA["alarm"], stroke=ISA["text"], width=1, task=task, tip=tip))
        prims.append(Prim("text", x + 7, y + 11, text="1", size=10, bold=True, anchor="middle",
                          color=ISA["alarm_text"], task=task))
    elif state == "warning":
        pts = [(x + 7, y), (x + 15, y + 14), (x - 1, y + 14)]
        prims.append(Prim("poly", points=pts, fill=ISA["warning"], stroke=ISA["text"], width=1, task=task, tip=tip))
        prims.append(Prim("text", x + 7, y + 12.5, text="2", size=9, bold=True, anchor="middle",
                          color=ISA["warning_text"], task=task))


def layout(sched: Schedule, width: float = 1100, row_h: float = 38,
           title: str = "") -> tuple[list[Prim], float, float]:
    if sched.kind == "space_time":
        return layout_space_time(sched, width, title=title)
    return layout_gantt(sched, width, row_h, title=title)


def _time_range(sched: Schedule) -> tuple[float, float]:
    lo = min([t.start for t in sched.tasks] + [t.release for t in sched.tasks if t.release is not None] or [0.0])
    hi = max([t.end for t in sched.tasks] + [t.due for t in sched.tasks if t.due is not None] or [1.0])
    if hi <= lo:
        hi = lo + 1.0
    pad = (hi - lo) * 0.02
    return lo - pad, hi + pad


def _axis(prims, sched, x0, x1, y_top, y_bottom, lo, hi, X) -> None:
    for tv in _time_ticks(lo, hi, x1 - x0, sched):
        x = X(tv)
        if x < x0 - 0.5 or x > x1 + 0.5:
            continue
        prims.append(Prim("line", points=[(x, y_top), (x, y_bottom)], stroke=ISA["grid"], width=1))
        prims.append(Prim("line", points=[(x, y_top - 5), (x, y_top)], stroke=ISA["axis"], width=1))
        label = format_time(tv, sched.unit, sched.origin, short=True) if sched.origin else f"{tv:g}"
        prims.append(Prim("text", x, y_top - 9, text=label, size=11, anchor="middle", color=ISA["text_dim"]))
    prims.append(Prim("line", points=[(x0, y_top), (x1, y_top)], stroke=ISA["axis"], width=1))


def _legend(prims, x, y, sched: Schedule) -> float:
    items = [("normal", "Normal"), ("warning", "Warning: long wait"),
             ("alarm", "Alarm: late or overlap")]
    for state, text in items:
        if state == "normal":
            prims.append(Prim("rect", x, y, 22, 12, fill=ISA["bar"], stroke=ISA["bar_edge"]))
            x += 28
        else:
            _indicator(prims, x, y - 1, state, None, "")
            x += 22
        prims.append(Prim("text", x, y + 10, text=text, size=11, color=ISA["text_dim"]))
        x += _text_width(text, 11) + 22
    unit = f"Time unit: {sched.unit}" if not sched.origin else f"Times from {sched.origin:%a %d %b %Y %H:%M}"
    prims.append(Prim("text", x, y + 10, text=unit, size=11, color=ISA["text_dim"]))
    return y + 18


def layout_gantt(sched: Schedule, width: float = 1100, row_h: float = 38,
                 title: str = "") -> tuple[list[Prim], float, float]:
    prims: list[Prim] = []
    left = 16 + max([_text_width(r, 12) for r in sched.resources] + [60]) + 14
    right = 24
    top = 30 + (24 if title else 0)
    rows = sched.resources or ["All"]
    height = top + row_h * len(rows) + 46
    prims.append(Prim("rect", 0, 0, width, height, fill=ISA["bg"]))
    if title:
        prims.append(Prim("text", 16, 22, text=title, size=14, bold=True))
    x0, x1 = left, width - right
    lo, hi = _time_range(sched)

    def X(t: float) -> float:
        return x0 + (t - lo) / (hi - lo) * (x1 - x0)

    for i, r in enumerate(rows):
        y = top + i * row_h
        if i % 2:
            prims.append(Prim("rect", 0, y, width, row_h, fill=ISA["row_alt"]))
        prims.append(Prim("text", 16, y + row_h / 2 + 4, text=r, size=12, bold=True))
    _axis(prims, sched, x0, x1, top, top + row_h * len(rows), lo, hi, X)
    row_of = {r: i for i, r in enumerate(rows)}
    bar_h = row_h * 0.58
    for idx, t in enumerate(sched.tasks):
        i = row_of.get(t.resource, 0)
        yb = top + i * row_h + (row_h - bar_h) / 2
        tip = _tooltip(t, sched)
        xs, xe = X(t.start), X(t.end)
        if t.release is not None and t.release < t.start - 1e-9:
            wait_color = ISA["warning"] if t.state == "warning" else ISA["wait"]
            prims.append(Prim("line", points=[(X(t.release), yb + bar_h / 2), (xs, yb + bar_h / 2)],
                              stroke=wait_color, width=2 if t.state == "warning" else 1.2, dash=True,
                              task=idx, tip=tip))
        if t.release is not None:
            xr = X(t.release)
            prims.append(Prim("poly", points=[(xr, yb + bar_h - 7), (xr + 5, yb + bar_h + 1), (xr - 5, yb + bar_h + 1)],
                              fill=ISA["marker"], task=idx, tip=tip))
        edge = ISA["alarm"] if t.state == "alarm" else ISA["bar_edge"]
        prims.append(Prim("rect", xs, yb, max(1.5, xe - xs), bar_h, fill=ISA["bar"], stroke=edge,
                          width=2 if t.state == "alarm" else 1, task=idx, tip=tip))
        if t.tardiness and t.tardiness > 0 and t.due is not None:
            xd = max(X(t.due), xs)
            prims.append(Prim("rect", xd, yb + bar_h - 5, max(1.5, xe - xd), 5, fill=ISA["alarm"], task=idx, tip=tip))
        if t.due is not None:
            xd = X(t.due)
            prims.append(Prim("line", points=[(xd, yb - 4), (xd, yb + bar_h + 4)],
                              stroke=ISA["alarm"] if t.state == "alarm" and (t.tardiness or 0) > 0 else ISA["marker"],
                              width=2, task=idx, tip=tip))
        label = t.label
        tw = _text_width(label, 11.5)
        ind_w = 18 if t.state != "normal" else 0
        if tw + ind_w + 8 <= xe - xs:
            if ind_w:
                _indicator(prims, xs + 4, yb + (bar_h - 14) / 2, t.state, idx, tip)
            prims.append(Prim("text", xs + 5 + ind_w, yb + bar_h / 2 + 4, text=label, size=11.5,
                              color=ISA["text"], task=idx, tip=tip))
        else:
            xl = xe + 5
            if ind_w:
                _indicator(prims, xl, yb + (bar_h - 14) / 2, t.state, idx, tip)
            prims.append(Prim("text", xl + ind_w, yb + bar_h / 2 + 4, text=label, size=11.5,
                              color=ISA["text"], task=idx, tip=tip))
    _legend(prims, 16, height - 30, sched)
    return prims, width, height


def layout_space_time(sched: Schedule, width: float = 1100, plot_h: float = 420,
                      title: str = "") -> tuple[list[Prim], float, float]:
    prims: list[Prim] = []
    left, right = 70, 24
    top = 48 + (24 if title else 0)
    height = top + plot_h + 50
    prims.append(Prim("rect", 0, 0, width, height, fill=ISA["bg"]))
    if title:
        prims.append(Prim("text", 16, 22, text=title, size=14, bold=True))
    x0, x1 = left, width - right
    y0, y1 = top, top + plot_h
    lo, hi = _time_range(sched)
    smax = sched.space_max or max([(t.position or 0) + (t.size or 0) for t in sched.tasks] + [1.0])

    def X(t):
        return x0 + (t - lo) / (hi - lo) * (x1 - x0)

    def Y(s):
        return y0 + s / smax * (y1 - y0)

    prims.append(Prim("rect", x0, y0, x1 - x0, y1 - y0, fill=ISA["row_alt"], stroke=ISA["axis"]))
    _axis(prims, sched, x0, x1, y0, y1, lo, hi, X)
    for sv in nice_ticks(0, smax, 8):
        y = Y(sv)
        prims.append(Prim("line", points=[(x0 - 5, y), (x0, y)], stroke=ISA["axis"]))
        prims.append(Prim("text", x0 - 8, y + 4, text=f"{sv:g}", size=11, anchor="end", color=ISA["text_dim"]))
    prims.append(Prim("text", 16, y0 - 30, text=sched.space_label, size=11, bold=True, color=ISA["text_dim"]))
    for idx, t in enumerate(sched.tasks):
        tip = _tooltip(t, sched)
        xs, xe = X(t.start), X(t.end)
        ya, yb = Y(t.position or 0), Y((t.position or 0) + (t.size or 0))
        if t.release is not None and t.release < t.start - 1e-9:
            ym = (ya + yb) / 2
            prims.append(Prim("line", points=[(X(t.release), ym), (xs, ym)],
                              stroke=ISA["warning"] if t.state == "warning" else ISA["wait"],
                              width=2 if t.state == "warning" else 1.2, dash=True, task=idx, tip=tip))
        edge = ISA["alarm"] if t.state == "alarm" else ISA["bar_edge"]
        prims.append(Prim("rect", xs, ya, max(1.5, xe - xs), max(1.5, yb - ya), fill=ISA["bar"], stroke=edge,
                          width=2 if t.state == "alarm" else 1, task=idx, tip=tip))
        if t.tardiness and t.tardiness > 0 and t.due is not None:
            xd = max(X(t.due), xs)
            prims.append(Prim("rect", xd, yb - 6, max(1.5, xe - xd), 5, fill=ISA["alarm"], task=idx, tip=tip))
            if xs < X(t.due) < xe:  # due line only inside the vessel's own rectangle
                prims.append(Prim("line", points=[(X(t.due), ya), (X(t.due), yb)], stroke=ISA["alarm"],
                                  width=2, task=idx, tip=tip))
        ind_w = 18 if t.state != "normal" else 0
        if ind_w:
            _indicator(prims, xs + 4, ya + 4, t.state, idx, tip)
        prims.append(Prim("text", xs + 5 + ind_w, ya + 15, text=t.label, size=11.5, task=idx, tip=tip))
    _legend(prims, 16, height - 28, sched)
    return prims, width, height


# ---------------------------------------------------------------------------
# SVG
# ---------------------------------------------------------------------------

def to_svg(prims: list[Prim], width: float, height: float) -> str:
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" '
           f'width="{width:.0f}" height="{height:.0f}" font-family="{FONT}" role="img">']
    for p in prims:
        tip = f"<title>{html.escape(p.tip)}</title>" if p.tip else ""
        common = []
        if p.stroke:
            common.append(f'stroke="{p.stroke}" stroke-width="{p.width:g}"')
        if p.dash:
            common.append('stroke-dasharray="5 4"')
        style = " ".join(common)
        if p.kind == "rect":
            fill = p.fill or "none"
            out.append(f'<rect x="{p.x:.1f}" y="{p.y:.1f}" width="{p.w:.1f}" height="{p.h:.1f}" '
                       f'fill="{fill}" {style}>{tip}</rect>')
        elif p.kind == "line":
            (xa, ya), (xb, yb) = p.points[0], p.points[1]
            out.append(f'<line x1="{xa:.1f}" y1="{ya:.1f}" x2="{xb:.1f}" y2="{yb:.1f}" {style}>{tip}</line>')
        elif p.kind == "poly":
            pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in p.points)
            out.append(f'<polygon points="{pts}" fill="{p.fill or "none"}" {style}>{tip}</polygon>')
        elif p.kind == "text":
            weight = ' font-weight="600"' if p.bold else ""
            out.append(f'<text x="{p.x:.1f}" y="{p.y:.1f}" font-size="{p.size:g}" fill="{p.color}" '
                       f'text-anchor="{p.anchor}"{weight}>{html.escape(p.text)}{tip}</text>')
    out.append("</svg>")
    return "\n".join(out)


def schedule_svg(sched: Schedule, width: float = 1100, title: str = "") -> str:
    prims, w, h = layout(sched, width, title=title)
    return to_svg(prims, w, h)


def schedule_rows(sched: Schedule) -> list[dict]:
    """Flat rows for tables and CSV."""
    out = []
    for res, lst in sched.by_resource().items():
        for seq, t in enumerate(lst, 1):
            out.append({
                "resource": res, "sequence": seq, "task": t.label,
                "start": t.start, "end": t.end, "duration": t.duration,
                "start_time": sched.clock(t.start) if sched.origin else "",
                "end_time": sched.clock(t.end) if sched.origin else "",
                "release": t.release, "wait": t.wait, "due": t.due, "tardiness": t.tardiness,
                "position": t.position, "size": t.size,
                "state": t.state, "notes": "; ".join(t.reasons),
            })
    return out


Formatter = Callable[[Any], str]
