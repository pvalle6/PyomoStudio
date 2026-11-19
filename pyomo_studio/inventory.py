"""Tank inventory: data from a solved layered model, a process schematic and trends.

The *schematic* shows one period: for each grade, where the crude comes from
(vessels at the berths, or fixed deliveries), the tanks with their levels and
modes, and where the crude goes (crude units, or a fixed demand). A strip at
the bottom shows the charge and blend of each crude unit.

The *trend* shows the stock of each tank over the whole horizon, with the
heel and the capacity, and a cursor at the selected period.

Both follow ISA-101 like the schedule graphic: gray for normal states, color
only for abnormal states, each repeated by a symbol and text.

    warning (amber, 2)  level at or above the high-level fraction of capacity,
                        or at or below the heel plus the low-level margin
    alarm   (red, 1)    level outside heel..capacity, fixed delivery rejected,
                        or fixed demand not met

This module does not import Pyomo or Qt.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from . import spec as S
from .schedule import ISA, Prim, _indicator, _text_width, format_time, nice_ticks, parse_origin, to_svg

HIGH_FRACTION = 0.95        # warning at or above 95 % of capacity
LOW_MARGIN = 0.02           # warning at or below heel + 2 % of capacity
TOL = 1e-6

FILL = "#9A9A9A"            # liquid in a tank (normal)
FLOW_ON = "#2E2E2E"
FLOW_OFF = "#B9B9B9"


@dataclass
class TankSeries:
    name: str
    grade: str
    capacity: float
    heel: float
    initial: float
    inv: list[float]                 # end of period 1..N
    fin: list[float]
    fout: list[float]

    def level(self, k: int) -> float:
        """Stock at the end of period k (k = 0: opening stock)."""
        return self.initial if k <= 0 else self.inv[k - 1]

    def mode(self, k: int) -> str:
        i, o = self.fin[k - 1] > TOL, self.fout[k - 1] > TOL
        return "receiving and sending" if i and o else "receiving" if i else "sending" if o else "standing"

    def state(self, k: int) -> tuple[str, str]:
        lv = self.level(k)
        span = max(self.capacity, 1e-9)
        if lv > self.capacity + 1e-3 or lv < self.heel - 1e-3:
            return "alarm", "level outside heel and capacity"
        if lv >= HIGH_FRACTION * self.capacity - TOL:
            return "warning", f"high level ({lv / span:.0%} of capacity, little ullage)"
        if lv <= self.heel + LOW_MARGIN * self.capacity + TOL:
            return "warning", f"low level (at heel {self.heel:,.0f} m3)"
        return "normal", ""


@dataclass
class Inflow:
    label: str                       # for example "V3 at B1" or "Fixed delivery"
    volume: float                    # m3 in the period
    note: str = ""


@dataclass
class Unit:
    name: str
    charge: list[float]              # m3 per period
    blend: list[dict[str, float]]    # per period: grade -> m3
    running: list[bool]
    max_sulfur: float | None = None
    sulfur: dict[str, float] = field(default_factory=dict)

    def blend_sulfur(self, k: int) -> float | None:
        tot = self.charge[k - 1]
        if tot <= TOL or not self.sulfur:
            return None
        return sum(self.sulfur.get(g, 0.0) * v for g, v in self.blend[k - 1].items()) / tot


@dataclass
class Inventory:
    layer: str
    scenario: str
    periods: int
    period_h: float
    origin: dt.datetime | None
    grades: list[str]
    tanks: list[TankSeries]
    source_kind: str                         # berth | fixed | layer
    source_layer: str | None
    sink_kind: str                           # cdu | fixed | layer
    sink_layer: str | None
    inflows: dict[tuple[str, int], list[Inflow]] = field(default_factory=dict)   # (grade, k)
    reject: dict[tuple[str, int], float] = field(default_factory=dict)
    demand: dict[str, float] = field(default_factory=dict)                       # m3/h
    short: dict[tuple[str, int], float] = field(default_factory=dict)
    units: list[Unit] = field(default_factory=list)

    def tanks_of(self, grade: str) -> list[TankSeries]:
        return [t for t in self.tanks if t.grade == grade]

    def grades_used(self) -> list[str]:
        used = {t.grade for t in self.tanks}
        return [g for g in self.grades if g in used] + sorted(used - set(self.grades))

    def period_text(self, k: int) -> str:
        a, b = (k - 1) * self.period_h, k * self.period_h
        if self.origin:
            return f"period {k} of {self.periods}, {format_time(a, 'h', self.origin, short=True)} to " \
                   f"{format_time(b, 'h', self.origin, short=True)}"
        return f"period {k} of {self.periods}, {a:g} h to {b:g} h"

    def sent(self, grade: str, k: int) -> float:
        return sum(t.fout[k - 1] for t in self.tanks_of(grade))

    def received(self, grade: str, k: int) -> float:
        return sum(t.fin[k - 1] for t in self.tanks_of(grade))

    def counts(self) -> dict[str, int]:
        """Tank-periods in warning and alarm, and periods with a fallback penalty."""
        w = a = 0
        for t in self.tanks:
            for k in range(1, self.periods + 1):
                st, _ = t.state(k)
                w += st == "warning"
                a += st == "alarm"
        a += sum(1 for v in self.reject.values() if v > TOL) + sum(1 for v in self.short.values() if v > TOL)
        return {"warnings": w, "alarms": a}


class InventoryError(Exception):
    pass


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def tank_layers(spec: dict) -> list[str]:
    return [m["id"] for m in spec.get("_layers") or [] if m["type"] == "tank_farm"]


def _link(meta: dict, port: str, direction: str) -> str | None:
    for lk in meta["links"]:
        if lk["port"] == port and lk["direction"] == direction:
            return lk["partner"]
    return None


def _set_elements(spec: dict, name: str) -> list:
    for s in spec["sets"]:
        if s["name"] == name:
            return [tuple(e) if isinstance(e, list) else e for e in s.get("elements", [])]
    return []


def compute(spec: dict, result, scenario: str | None = None, layer: str | None = None) -> Inventory:
    """Read the tank data of one tank-farm layer from a solved result."""
    metas = {m["id"]: m for m in spec.get("_layers") or []}
    ids = tank_layers(spec)
    if not ids:
        raise InventoryError("The model has no enabled tank farm layer.")
    lid = layer if layer in ids else ids[0]
    meta = metas[lid]
    if result is None or not result.ok:
        raise InventoryError("There is no solution.")
    sc = result.scenario(scenario)
    vals = sc.values
    params = _params(spec, result, sc.name)
    grid = spec.get("_grid") or {}
    n = int(grid.get("periods", 0))
    ph = float(grid.get("period_h", 1.0))

    def p(name: str):
        return params[f"{lid}_{name}"]

    tanks = []
    for name, grade in _set_elements(spec, f"{lid}_IG"):
        inv = vals[f"{lid}_inv"]
        tanks.append(TankSeries(
            str(name), str(grade), float(p("capacity")[name]), float(p("heel")[name]), float(p("initial")[name]),
            [float(inv.get((name, k)) or 0.0) for k in range(1, n + 1)],
            [float(vals[f"{lid}_fin"].get((name, k)) or 0.0) for k in range(1, n + 1)],
            [float(vals[f"{lid}_fout"].get((name, k)) or 0.0) for k in range(1, n + 1)]))

    src = _link(meta, "crude_receipt", "in")
    snk = _link(meta, "crude_supply", "out")
    src_type = metas[src]["type"] if src in metas else None
    snk_ids = [x.strip() for x in (snk or "").split(",") if x.strip()]
    cdu = next((x for x in snk_ids if metas.get(x, {}).get("type") == "cdu"), None)
    inv = Inventory(lid, sc.name, n, ph, parse_origin(str(grid.get("start") or "")), list(grid.get("grades") or []),
                    tanks, "berth" if src_type == "berth" else ("layer" if src else "fixed"), src,
                    "cdu" if cdu else ("layer" if snk_ids else "fixed"), cdu or (snk_ids[0] if snk_ids else None))

    if inv.source_kind == "berth":
        _berth_inflows(inv, spec, vals, params, src, n, ph)
    elif inv.source_kind == "fixed":
        deliv = p("delivery")
        for g in inv.grades_used():
            for k in range(1, n + 1):
                v = float(deliv[(g, k)]) if (g, k) in deliv else 0.0
                if v > TOL:
                    inv.inflows[(g, k)] = [Inflow("Fixed delivery", v)]
        inv.reject = {k: float(v or 0.0) for k, v in vals.get(f"{lid}_reject", {}).items()}
    else:
        for g in inv.grades_used():
            for k in range(1, n + 1):
                v = inv.received(g, k)
                if v > TOL:
                    inv.inflows[(g, k)] = [Inflow(f"Layer {src}", v)]

    if inv.sink_kind == "fixed":
        dem = p("demand")
        inv.demand = {g: float(dem[g]) if g in dem else 0.0 for g in inv.grades_used()}
        inv.short = {k: float(v or 0.0) for k, v in vals.get(f"{lid}_short", {}).items()}
    elif inv.sink_kind == "cdu":
        _units(inv, spec, vals, params, cdu, n)
    return inv


def _params(spec: dict, result, scenario: str) -> dict:
    built = getattr(result, "built", None)
    if built is not None and scenario in built.params:
        return built.params[scenario]
    sets = S.resolve_sets(spec)
    return S.resolve_params(spec, sets)


def _berth_inflows(inv: Inventory, spec: dict, vals: dict, params: dict, bid: str, n: int, ph: float) -> None:
    grade = dict(_set_elements(spec, f"{bid}_VG"))
    berth = {}
    for (v, b), x in (vals.get(f"{bid}_x") or {}).items():
        if (x or 0) > 0.5:
            berth[v] = b
    q = vals.get(f"{bid}_q") or {}
    t = vals.get(f"{bid}_t") or {}
    dep = vals.get(f"{bid}_dep") or {}
    hook = float(params.get(f"{bid}_hook", 0.0) or 0.0)
    rel = float(params.get(f"{bid}_rel", 0.0) or 0.0)
    for v, g in grade.items():
        for k in range(1, n + 1):
            vol = float(q.get((v, k)) or 0.0)
            a, b = (k - 1) * ph, k * ph
            if t.get(v) is None or dep.get(v) is None:
                continue
            moored = t[v] < b - TOL and dep[v] > a + TOL
            if vol > TOL:
                inv.inflows.setdefault((g, k), []).append(Inflow(f"{v} at {berth.get(v, '?')}", vol))
            elif moored:
                # Idle inside the pumping window: the vessel waits (for example for tank space).
                idle = a >= t[v] + hook - TOL and b <= dep[v] - rel + TOL
                inv.inflows.setdefault((g, k), []).append(
                    Inflow(f"{v} at {berth.get(v, '?')}", 0.0, "WAITING, not pumping" if idle else "hook-up or release"))


def _units(inv: Inventory, spec: dict, vals: dict, params: dict, cid: str, n: int) -> None:
    f = vals.get(f"{cid}_f") or {}
    on = vals.get(f"{cid}_on") or {}
    sul = params.get(f"{cid}_sulfur")
    smax = params.get(f"{cid}_max_sulfur")
    sulfur = {g: float(sul[g]) for g in inv.grades if sul is not None and g in sul}
    for u in _set_elements(spec, f"{cid}_U"):
        blend = [{g: float(f.get((u, g, k)) or 0.0) for g in inv.grades} for k in range(1, n + 1)]
        inv.units.append(Unit(str(u), [sum(b.values()) for b in blend], blend,
                              [(on.get((u, k)) or 0) > 0.5 for k in range(1, n + 1)],
                              float(smax[u]) if smax is not None and u in smax else None, sulfur))


def compute_all(spec: dict, result) -> list[Inventory]:
    """Every tank layer in every scenario (empty if the model has no tank layer)."""
    out = []
    if result is None or not result.ok:
        return out
    for lid in tank_layers(spec):
        for sc in result.scenarios:
            try:
                out.append(compute(spec, result, sc.name, lid))
            except (InventoryError, KeyError):
                continue
    return out


# ---------------------------------------------------------------------------
# Schematic
# ---------------------------------------------------------------------------

def _fmt(v: float) -> str:
    return f"{v:,.0f}"


def _box(prims, x, y, w, h, title, lines, state="normal", tip=""):
    prims.append(Prim("rect", x, y, w, h, fill="#E6E6E6", stroke=ISA["bar_edge"], width=1, tip=tip))
    prims.append(Prim("text", x + 8, y + 16, text=title, size=12, bold=True))
    yy = y + 32
    for text, dim in lines:
        prims.append(Prim("text", x + 8, yy, text=text, size=11, color=ISA["text_dim"] if dim else ISA["text"]))
        yy += 15
    if state != "normal":
        _indicator(prims, x + w - 20, y + 5, state, None, tip)


def layout_schematic(inv: Inventory, k: int, width: float = 1100, title: str = "") -> tuple[list[Prim], float, float]:
    """The process schematic for period *k* (1..N)."""
    k = max(1, min(inv.periods, k))
    prims: list[Prim] = []
    margin = 16
    src_w, snk_w = 210, 210
    grades = inv.grades_used()
    most = max([len(inv.tanks_of(g)) for g in grades] + [1])
    area_x0 = margin + src_w + 40
    area_x1 = width - margin - snk_w - 40
    pitch = max(96.0, min(150.0, (area_x1 - area_x0) / most))
    tank_w = min(104.0, pitch - 22)
    if area_x0 + pitch * most > area_x1:      # widen the picture for many tanks
        area_x1 = area_x0 + pitch * most
        width = area_x1 + 40 + snk_w + margin
    top = 12
    head = title or f"Tank farm '{inv.layer}'"
    prims.append(Prim("text", margin, top + 14, text=head, size=14, bold=True))
    ptext = inv.period_text(k)
    prims.append(Prim("text", margin, top + 32, text=ptext[:1].upper() + ptext[1:]
                      + (f" - scenario {inv.scenario}" if inv.scenario not in ("base", "") else ""),
                      size=11, color=ISA["text_dim"]))
    y = top + 46
    row_h = 184
    tank_h = 108
    for gi, g in enumerate(grades):
        ry = y + gi * row_h
        if gi % 2:
            prims.append(Prim("rect", 0, ry, width, row_h, fill=ISA["row_alt"]))
        mid_in = ry + 26
        mid_out = ry + row_h - 22
        tanks = inv.tanks_of(g)

        # Source box
        flows = inv.inflows.get((g, k), [])
        pumped = sum(f.volume for f in flows)
        lines = []
        for fl in flows:
            lines.append((f"{fl.label}: {_fmt(fl.volume)} m3" if not fl.note else f"{fl.label}: {fl.note}",
                          bool(fl.note)))
        if not flows:
            lines.append(("no receipt", True))
        rej = inv.reject.get((g, k), 0.0)
        state, tip = "normal", ""
        if rej > TOL:
            state, tip = "alarm", f"ALARM: {_fmt(rej)} m3 of the fixed delivery do not fit the tanks."
            lines.append((f"REJECTED {_fmt(rej)} m3", False))
        if any(fl.note.startswith("WAITING") for fl in flows) and state == "normal":
            state, tip = "warning", ("WARNING: a vessel is at the berth after hook-up but does not pump in this "
                                     "period, for example because the tanks have no space.")
        src_title = {"berth": f"Receipt {g}", "fixed": f"Fixed receipt {g}", "layer": f"Receipt {g}"}[inv.source_kind]
        _box(prims, margin, ry + 10, src_w, row_h - 20, src_title, lines[:8], state, tip or src_title)

        # Inlet header and outlet header
        x_first = area_x0 + (pitch - tank_w) / 2
        x_last = x_first + pitch * max(0, len(tanks) - 1) + tank_w
        prims.append(Prim("line", points=[(margin + src_w, mid_in), (x_last - 18, mid_in)],
                          stroke=FLOW_ON if pumped > TOL else FLOW_OFF, width=2.5 if pumped > TOL else 1.2))
        out_total = inv.sent(g, k)
        prims.append(Prim("line", points=[(x_first + 18, mid_out), (width - margin - snk_w, mid_out)],
                          stroke=FLOW_ON if out_total > TOL else FLOW_OFF, width=2.5 if out_total > TOL else 1.2))
        if pumped > TOL:
            prims.append(Prim("text", margin + src_w + 6, mid_in - 6, text=f"{_fmt(inv.received(g, k))} m3",
                              size=10, color=ISA["text_dim"]))
        if out_total > TOL:
            prims.append(Prim("text", width - margin - snk_w - 6, mid_out - 6, text=f"{_fmt(out_total)} m3",
                              size=10, anchor="end", color=ISA["text_dim"]))

        # Tanks
        for ti, t in enumerate(tanks):
            tx = area_x0 + ti * pitch + (pitch - tank_w) / 2
            ty = ry + 44
            lv = t.level(k)
            frac = max(0.0, min(1.0, lv / t.capacity if t.capacity > 0 else 0.0))
            st, why = t.state(k)
            mode = t.mode(k)
            fin, fout = t.fin[k - 1], t.fout[k - 1]
            # inlet stub (top left) and outlet stub (bottom right)
            prims.append(Prim("line", points=[(tx + 18, mid_in), (tx + 18, ty)],
                              stroke=FLOW_ON if fin > TOL else FLOW_OFF, width=2.5 if fin > TOL else 1.2))
            prims.append(Prim("line", points=[(tx + tank_w - 18, ty + tank_h), (tx + tank_w - 18, mid_out)],
                              stroke=FLOW_ON if fout > TOL else FLOW_OFF, width=2.5 if fout > TOL else 1.2))
            if fin > TOL:
                prims.append(Prim("poly", points=[(tx + 13, ty - 9), (tx + 23, ty - 9), (tx + 18, ty - 2)],
                                  fill=FLOW_ON))
            if fout > TOL:
                yb = ty + tank_h
                prims.append(Prim("poly", points=[(tx + tank_w - 23, yb + 2), (tx + tank_w - 13, yb + 2),
                                                  (tx + tank_w - 18, yb + 9)], fill=FLOW_ON))
            tip = (f"{t.name} ({t.grade}): {_fmt(lv)} of {_fmt(t.capacity)} m3 ({frac:.0%}). Heel {_fmt(t.heel)} m3. "
                   f"In {_fmt(fin)} m3, out {_fmt(fout)} m3 in this period. {mode.capitalize()}."
                   + (f" {st.upper()}: {why}." if st != "normal" else ""))
            prims.append(Prim("rect", tx, ty, tank_w, tank_h, fill="#EFEFEF", stroke=ISA["bar_edge"], width=1.2,
                              tip=tip))
            fh = tank_h * frac
            if fh > 0.5:
                prims.append(Prim("rect", tx + 1, ty + tank_h - fh, tank_w - 2, fh - 1, fill=FILL))
            hy = ty + tank_h * (1 - t.heel / t.capacity) if t.capacity > 0 else ty + tank_h
            prims.append(Prim("line", points=[(tx + 1, hy), (tx + tank_w - 1, hy)], stroke=ISA["text_dim"],
                              width=1, dash=True))
            hiy = ty + tank_h * (1 - HIGH_FRACTION)
            prims.append(Prim("line", points=[(tx + tank_w - 8, hiy), (tx + tank_w, hiy)], stroke=ISA["text_dim"],
                              width=1))
            prims.append(Prim("text", tx + 6, ty + 15, text=t.name, size=11, bold=True))
            prims.append(Prim("text", tx + 6, ty + 29, text=mode.upper() if mode != "receiving and sending"
                              else "IN + OUT", size=9, color=ISA["text_dim"]))
            prims.append(Prim("text", tx + tank_w / 2, ty + 60, text=f"{frac:.0%}", size=13, bold=True,
                              anchor="middle"))
            prims.append(Prim("text", tx + tank_w / 2, ty + 75, text=f"{_fmt(lv)} m3", size=10,
                              anchor="middle"))
            if st != "normal":
                _indicator(prims, tx + tank_w - 18, ty + 4, st, None, f"{st.upper()}: {why}")
                prims.append(Prim("text", tx + tank_w / 2, ty + tank_h + 22, text=st.upper(), size=9, bold=True,
                                  anchor="middle"))

        # Sink box
        sx = width - margin - snk_w
        lines, state, tip = [], "normal", ""
        if inv.sink_kind == "cdu":
            title_s = f"To crude units {g}"
            for u in inv.units:
                v = u.blend[k - 1].get(g, 0.0)
                if v > TOL:
                    lines.append((f"{u.name}: {_fmt(v)} m3", False))
            if not lines:
                lines.append(("no send-out", True))
        elif inv.sink_kind == "fixed":
            title_s = f"Fixed demand {g}"
            need = inv.demand.get(g, 0.0) * inv.period_h
            lines.append((f"demand {_fmt(need)} m3", True))
            lines.append((f"sent {_fmt(out_total)} m3", False))
            sh = inv.short.get((g, k), 0.0)
            if sh > TOL:
                state, tip = "alarm", f"ALARM: {_fmt(sh)} m3 of the fixed demand are not met."
                lines.append((f"SHORT {_fmt(sh)} m3", False))
        else:
            title_s = f"To layer {inv.sink_layer} {g}"
            lines.append((f"sent {_fmt(out_total)} m3", False))
        _box(prims, sx, ry + 10, snk_w, row_h - 20, title_s, lines[:8], state, tip or title_s)

    y_end = y + len(grades) * row_h
    # Crude units strip
    if inv.units:
        y_end += 10
        prims.append(Prim("text", margin, y_end + 14, text="Crude units", size=12, bold=True))
        y_end += 22
        uw = (width - 2 * margin - 12 * (len(inv.units) - 1)) / len(inv.units)
        for ui, u in enumerate(inv.units):
            ux = margin + ui * (uw + 12)
            rate = u.charge[k - 1] / inv.period_h
            s = u.blend_sulfur(k)
            lines = [(f"charge {_fmt(rate)} m3/h" if u.running[k - 1] else "STOPPED", not u.running[k - 1])]
            tot = u.charge[k - 1]
            if tot > TOL:
                lines.append((", ".join(f"{g} {v / tot:.0%}" for g, v in u.blend[k - 1].items() if v > TOL), False))
            if s is not None:
                lim = f" (max {u.max_sulfur:g})" if u.max_sulfur is not None else ""
                lines.append((f"blend sulfur {s:.2f} wt%{lim}", True))
            state = "warning" if not u.running[k - 1] else "normal"
            _box(prims, ux, y_end, uw, 78, u.name, lines, state,
                 f"WARNING: {u.name} is stopped in this period." if state == "warning" else u.name)
        y_end += 88

    # Legend
    ly = y_end + 14
    x = margin
    prims.append(Prim("rect", x, ly - 1, 22, 12, fill=FILL, stroke=ISA["bar_edge"]))
    x += 28
    prims.append(Prim("text", x, ly + 9, text="Stock", size=11, color=ISA["text_dim"]))
    x += 50
    prims.append(Prim("line", points=[(x, ly + 5), (x + 22, ly + 5)], stroke=ISA["text_dim"], dash=True))
    x += 28
    prims.append(Prim("text", x, ly + 9, text="Heel", size=11, color=ISA["text_dim"]))
    x += 44
    prims.append(Prim("line", points=[(x, ly + 5), (x + 22, ly + 5)], stroke=FLOW_ON, width=2.5))
    x += 28
    prims.append(Prim("text", x, ly + 9, text="Flow in this period", size=11, color=ISA["text_dim"]))
    x += _text_width("Flow in this period", 11) + 22
    for state, text in (("warning", f"Warning: level >= {HIGH_FRACTION:.0%} or at heel"),
                        ("alarm", "Alarm: outside limits, rejected or short")):
        _indicator(prims, x, ly - 2, state, None, "")
        x += 22
        prims.append(Prim("text", x, ly + 9, text=text, size=11, color=ISA["text_dim"]))
        x += _text_width(text, 11) + 22
    return prims, width, ly + 24


# ---------------------------------------------------------------------------
# Trends
# ---------------------------------------------------------------------------

@dataclass
class TrendGeometry:
    """Maps x to a period for clicks on the trend."""
    x0: float
    x1: float
    periods: int
    period_h: float

    def period_at(self, x: float) -> int:
        if self.x1 <= self.x0:
            return 1
        t = (x - self.x0) / (self.x1 - self.x0) * self.periods * self.period_h
        return max(1, min(self.periods, int(t // self.period_h) + 1))


def layout_trends(inv: Inventory, k: int | None = None, width: float = 1100,
                  row_h: float = 64) -> tuple[list[Prim], float, float, TrendGeometry]:
    prims: list[Prim] = []
    margin = 16
    left = margin + 120
    right = 70
    x0, x1 = left, width - right
    hz = inv.periods * inv.period_h

    def X(t):
        return x0 + (x1 - x0) * t / hz if hz > 0 else x0

    top = 30
    # time axis
    for tv in nice_ticks(0, hz, max(2, int((x1 - x0) / 110))):
        x = X(tv)
        prims.append(Prim("line", points=[(x, top), (x, top + row_h * len(inv.tanks))], stroke=ISA["grid"]))
        text = format_time(tv, "h", inv.origin, short=True) if inv.origin else f"{tv:g} h"
        prims.append(Prim("text", x, top - 8, text=text, size=10, anchor="middle", color=ISA["text_dim"]))
    prims.append(Prim("line", points=[(x0, top), (x1, top)], stroke=ISA["axis"]))
    for i, t in enumerate(inv.tanks):
        ry = top + i * row_h
        if i % 2:
            prims.append(Prim("rect", 0, ry, width, row_h, fill=ISA["row_alt"]))
        y_top, y_bot = ry + 8, ry + row_h - 8

        def Y(v, t=t, y_top=y_top, y_bot=y_bot):
            return y_bot - (y_bot - y_top) * (v / t.capacity if t.capacity > 0 else 0.0)

        prims.append(Prim("text", margin, ry + row_h / 2 - 2, text=t.name, size=12, bold=True))
        prims.append(Prim("text", margin, ry + row_h / 2 + 13, text=f"{t.grade}, {_fmt(t.capacity)} m3",
                          size=10, color=ISA["text_dim"]))
        prims.append(Prim("line", points=[(x0, Y(t.capacity)), (x1, Y(t.capacity))], stroke=ISA["axis"]))
        prims.append(Prim("line", points=[(x0, Y(t.heel)), (x1, Y(t.heel))], stroke=ISA["text_dim"], dash=True))
        prims.append(Prim("line", points=[(x0, y_bot), (x1, y_bot)], stroke=ISA["grid"]))
        # abnormal periods: amber or red band at the top of the row
        for kk in range(1, inv.periods + 1):
            st, why = t.state(kk)
            if st != "normal":
                color = ISA["warning"] if st == "warning" else ISA["alarm"]
                prims.append(Prim("rect", X((kk - 1) * inv.period_h), ry + 2, X(inv.period_h) - x0, 4,
                                  fill=color, tip=f"{t.name}, {inv.period_text(kk)}: {st.upper()}: {why}"))
        pts = [(X(0), Y(t.initial))] + [(X(kk * inv.period_h), Y(t.inv[kk - 1])) for kk in range(1, inv.periods + 1)]
        prims.append(Prim("path", points=pts, stroke=ISA["text"], width=1.6))
        prims.append(Prim("text", x1 + 6, Y(t.capacity) + 4, text="cap", size=9, color=ISA["text_dim"]))
        prims.append(Prim("text", x1 + 6, Y(t.heel) + 4, text="heel", size=9, color=ISA["text_dim"]))
        for kk in range(1, inv.periods + 1):   # hover targets
            prims.append(Prim("rect", X((kk - 1) * inv.period_h), y_top, X(inv.period_h) - x0, y_bot - y_top,
                              fill="transparent", tip=f"{t.name}, {inv.period_text(kk)}: {_fmt(t.inv[kk - 1])} m3 "
                                  f"({t.inv[kk - 1] / t.capacity:.0%}), {t.mode(kk)}"))
    bottom = top + row_h * len(inv.tanks)
    if k is not None:
        xc = X((k - 0.5) * inv.period_h)
        prims.append(Prim("rect", X((k - 1) * inv.period_h), top, X(inv.period_h) - x0, bottom - top,
                          stroke=ISA["text"], width=1.5))
        prims.append(Prim("text", xc, bottom + 14, text=f"period {k}", size=10, anchor="middle", bold=True))
    return prims, width, bottom + 24, TrendGeometry(x0, x1, inv.periods, inv.period_h)


# ---------------------------------------------------------------------------
# Report helpers
# ---------------------------------------------------------------------------

def schematic_svg(inv: Inventory, k: int, width: float = 1100) -> str:
    prims, w, h = layout_schematic(inv, k, width)
    return to_svg(prims, w, h)


def trends_svg(inv: Inventory, width: float = 1100) -> str:
    prims, w, h, _ = layout_trends(inv, None, width)
    return to_svg(prims, w, h)


def summary_rows(inv: Inventory) -> list[list[Any]]:
    rows = []
    for t in inv.tanks:
        levels = [t.initial] + t.inv
        warn = sum(1 for k in range(1, inv.periods + 1) if t.state(k)[0] == "warning")
        rows.append([t.name, t.grade, _fmt(t.capacity), _fmt(t.heel), _fmt(t.initial), _fmt(min(levels)),
                     _fmt(max(levels)), _fmt(t.inv[-1] if t.inv else t.initial), _fmt(sum(t.fin)), _fmt(sum(t.fout)),
                     str(warn)])
    return rows


SUMMARY_HEADERS = ["Tank", "Grade", "Capacity", "Heel", "Opening", "Min", "Max", "Closing", "Received", "Sent",
                   "Warning periods"]


def inventory_csv(inv: Inventory) -> str:
    lines = ["scenario,tank,grade,period,start_h,end_h,stock_m3,in_m3,out_m3,mode,state"]
    for t in inv.tanks:
        for k in range(1, inv.periods + 1):
            st, _ = t.state(k)
            lines.append(f"{inv.scenario},{t.name},{t.grade},{k},{(k - 1) * inv.period_h:g},{k * inv.period_h:g},"
                         f"{t.inv[k - 1]:.3f},{t.fin[k - 1]:.3f},{t.fout[k - 1]:.3f},{t.mode(k)},{st}")
    return "\n".join(lines) + "\n"
