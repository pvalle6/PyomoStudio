"""Random instance generator: crude terminal and refinery models with layers.

``generate(GenOptions(seed=7, preset="small"))`` returns a spec with a berth,
a tank-farm and a crude-unit layer and random data. The same seed and options
always give the same model.

The data is made to be feasible:

* every vessel fits at least one berth, and the berth work fits the horizon
  with spare time;
* each grade has tank capacity for its opening stock plus its cargoes, less
  a part of the expected send-out (the *tightness* sets how large a part);
* the crude units can stop, so they never make the model infeasible, and
  their sulfur limits allow a blend of the generated grades;
* the fallback tables (fixed deliveries, demand and availability) follow
  the same cargoes and rates, so each layer also solves alone.

*Congestion* moves the vessel arrivals closer together. *Tightness* reduces
the tank space. ``scenarios > 0`` adds equally likely arrival-delay scenarios
(a two-stage stochastic model with the berth plan as the first stage).

This module does not import Pyomo.
"""
from __future__ import annotations

import copy
import random
from dataclasses import asdict, dataclass, fields

from . import layers as L
from . import spec as S

# name, sulfur (wt%), margin ($/m3), max blend fraction
CRUDES = [
    ("LSW", 0.35, 22.0, 1.0),    # light sweet
    ("BRT", 0.45, 21.0, 1.0),    # North Sea type
    ("CPC", 0.60, 20.0, 1.0),
    ("MED", 1.20, 19.0, 1.0),
    ("URL", 1.60, 18.5, 1.0),
    ("ARL", 1.90, 18.0, 1.0),    # Arab Light type
    ("HSR", 2.90, 26.0, 0.40),   # heavy sour, cheap
    ("MAY", 3.30, 28.0, 0.30),   # Maya type
]

# Solve times with HiGHS (gap 0.5 %) were measured over seeds and congestion/tightness settings.
# The tank "no receive and send in one period" binaries make medium and large models much harder,
# so those presets use 4 h periods without them.
PRESETS: dict[str, dict] = {
    "tiny":   {"vessels": 3, "berths": 1, "grades": 2, "tanks_per_grade": 2, "cdus": 1, "periods": 24,
               "period_h": 2.0, "tank_modes": True},       # < 1 s
    "small":  {"vessels": 5, "berths": 2, "grades": 3, "tanks_per_grade": 2, "cdus": 2, "periods": 36,
               "period_h": 2.0, "tank_modes": True},       # 1 to 10 s
    "medium": {"vessels": 8, "berths": 3, "grades": 4, "tanks_per_grade": 2, "cdus": 2, "periods": 24,
               "period_h": 4.0, "tank_modes": False},      # often < 30 s; some instances take minutes
    "large":  {"vessels": 12, "berths": 4, "grades": 5, "tanks_per_grade": 3, "cdus": 3, "periods": 30,
               "period_h": 4.0, "tank_modes": False},      # benchmark: often reaches the time limit
}


@dataclass
class GenOptions:
    seed: int = 1
    preset: str = "small"
    vessels: int | None = None
    berths: int | None = None
    grades: int | None = None
    tanks_per_grade: int | None = None
    cdus: int | None = None
    periods: int | None = None
    period_h: float | None = None
    tank_modes: bool | None = None   # tanks cannot receive and send in one period (binary variables)
    congestion: float = 0.5          # 0 = arrivals spread out, 1 = arrivals close together
    tightness: float = 0.5           # 0 = tanks hold all cargoes, 1 = tanks need the send-out
    scenarios: int = 0               # 0 = deterministic; else arrival-delay scenarios
    max_delay_h: float = 12.0

    def resolved(self) -> "GenOptions":
        """A copy with the preset values filled in and the values checked."""
        if self.preset not in PRESETS:
            raise ValueError(f"unknown preset '{self.preset}'. Use one of: {', '.join(PRESETS)}.")
        out = copy.copy(self)
        for key, val in PRESETS[self.preset].items():
            if getattr(out, key) is None:
                setattr(out, key, val)
        checks = [("vessels", 1, 40), ("berths", 1, 10), ("grades", 1, len(CRUDES)), ("tanks_per_grade", 1, 6),
                  ("cdus", 1, 6), ("periods", 6, 400)]
        for key, lo, hi in checks:
            v = int(getattr(out, key))
            if not lo <= v <= hi:
                raise ValueError(f"{key} must be from {lo} to {hi}.")
            setattr(out, key, v)
        out.period_h = float(out.period_h)
        out.tank_modes = bool(out.tank_modes)
        if out.period_h <= 0:
            raise ValueError("period_h must be more than 0.")
        for key in ("congestion", "tightness"):
            if not 0.0 <= float(getattr(out, key)) <= 1.0:
                raise ValueError(f"{key} must be from 0 to 1.")
        if out.scenarios < 0 or out.scenarios == 1 or out.scenarios > 50:
            raise ValueError("scenarios must be 0 (none) or from 2 to 50.")
        return out


def _r(rng: random.Random, lo: float, hi: float, step: float = 1.0) -> float:
    return round(rng.uniform(lo, hi) / step) * step


def generate(opts: GenOptions | None = None) -> dict:
    o = (opts or GenOptions()).resolved()
    rng = random.Random(o.seed)
    horizon = o.periods * o.period_h
    hook, rel = 2.0, 1.0

    # Grades: a random subset, kept in library order (light to heavy).
    picked = sorted(rng.sample(range(len(CRUDES)), o.grades))
    crudes = []
    for i in picked:
        name, sul, margin, frac = CRUDES[i]
        crudes.append({"grade": name, "sulfur": round(sul * rng.uniform(0.9, 1.1), 2),
                       "margin": round(margin + rng.uniform(-1.5, 1.5), 1), "max_frac": frac})
    grades = [c["grade"] for c in crudes]
    if len(crudes) == 1:
        crudes[0]["max_frac"] = 1.0

    # Crude units. Total charge sets the scale of everything else.
    units = []
    for u in range(o.cdus):
        mx = _r(rng, 700, 1500, 50)
        units.append({"name": f"CDU{u + 1}", "min_rate": _r(rng, 0.40 * mx, 0.55 * mx, 10), "max_rate": mx,
                      "max_sulfur": 0.0})
    s_lo = min(c["sulfur"] for c in crudes)
    s_hi = max(c["sulfur"] for c in crudes)
    for u in units:      # between the lightest and the heaviest grade: blending matters
        u["max_sulfur"] = round(s_lo + (s_hi - s_lo) * rng.uniform(0.45, 0.85) + 0.05, 2) if s_hi > s_lo \
            else round(s_hi + 0.2, 2)
    rate_total = sum(u["max_rate"] for u in units)
    consumption = 0.8 * rate_total * horizon          # crude the units can take in the horizon

    # Berths: the first berth takes the longest vessels.
    berths = []
    for b in range(o.berths):
        berths.append({"name": f"B{b + 1}", "open": 0.0,
                       "max_rate": _r(rng, 4000, 7000, 500) if b else 7000.0,
                       "max_length": 330.0 if b == 0 else _r(rng, 220, 300, 10)})

    # Cargo: about the consumption, split over the vessels.
    cargo_total = consumption * rng.uniform(0.75, 0.95)
    weights = [rng.uniform(0.7, 1.3) for _ in range(o.vessels)]
    vols = [cargo_total * w / sum(weights) for w in weights]
    # The berth work must fit the horizon with spare time.
    pump = [_r(rng, 3500, 6000, 500) for _ in range(o.vessels)]
    service = [hook + rel + v / min(p, 7000.0) for v, p in zip(vols, pump)]
    budget = 0.55 * o.berths * (horizon - 2 * o.period_h)
    if sum(service) > budget:
        scale = (budget - (hook + rel) * o.vessels) / max(1e-9, sum(service) - (hook + rel) * o.vessels)
        vols = [v * max(0.2, scale) for v in vols]
    vols = [max(5000.0, round(v, -3)) for v in vols]
    service = [hook + rel + v / min(p, 7000.0) for v, p in zip(vols, pump)]

    # Arrivals: spread over a window that congestion makes short.
    last_service = max(service)
    window = max(o.period_h, (horizon - last_service - 3 * o.period_h - o.max_delay_h * (o.scenarios > 0))
                 * (1.0 - 0.6 * o.congestion))
    arrivals = sorted(_r(rng, 0, window, 0.5) for _ in range(o.vessels))
    arrivals[0] = 0.0
    vessels = []
    grade_of = [grades[i % len(grades)] for i in range(o.vessels)]
    rng.shuffle(grade_of)
    for i in range(o.vessels):
        length = _r(rng, 180, 320, 10)
        vessels.append({"name": f"V{i + 1:02d}" if o.vessels > 9 else f"V{i + 1}", "grade": grade_of[i],
                        "volume": vols[i], "arrival": arrivals[i],
                        "due": round(arrivals[i] + service[i] + rng.uniform(4, 12), 1),
                        "pump_rate": pump[i], "length": length,
                        "cost_h": _r(rng, 1000, 2000, 50), "late_cost": _r(rng, 3000, 5000, 250)})

    # Tanks: capacity per grade from the opening stock, the cargoes and the tightness.
    cargo = {g: sum(v["volume"] for v in vessels if v["grade"] == g) for g in grades}
    share = {g: cargo[g] / max(1e-9, sum(cargo.values())) for g in grades}
    tanks, demand, deliveries = [], [], []
    for g in grades:
        cons_g = consumption * share[g] if cargo[g] > 0 else consumption / len(grades) * 0.3
        opening = max(0.25 * cons_g, 15000.0 * o.tanks_per_grade)
        biggest = max([v["volume"] for v in vessels if v["grade"] == g] + [0.0])
        need = opening + cargo[g] - o.tightness * 0.6 * cons_g
        need = max(need, opening + biggest * 1.15)
        heel = 0.06
        cap = need / (1.0 - heel) / o.tanks_per_grade
        cap = max(20000.0, round(cap * rng.uniform(1.0, 1.08), -3))
        split = [rng.uniform(0.6, 1.4) for _ in range(o.tanks_per_grade)]
        for j in range(o.tanks_per_grade):
            init = min(cap * 0.9, max(cap * heel + 1000, opening * split[j] / sum(split)))
            tanks.append({"name": f"T{grades.index(g) + 1}{j + 1:02d}", "grade": g, "capacity": cap,
                          "heel": round(cap * heel, -2), "initial": round(init, -2),
                          "in_rate": 7000.0, "out_rate": _r(rng, 1200, 2000, 100)})
        demand.append({"grade": g, "rate": round(0.8 * rate_total * share[g], -1) if cargo[g] > 0
                       else round(0.1 * rate_total, -1)})
    for v, s in zip(vessels, service):     # fixed deliveries follow the cargoes
        first = min(o.periods, int((v["arrival"] + hook) // o.period_h) + 2)
        last = min(o.periods, first + max(1, int(s * 1.6 // o.period_h)))
        deliveries.append({"grade": v["grade"], "first": first, "last": last, "volume": v["volume"]})
    for c in crudes:
        c["available"] = round(0.6 * rate_total * share[c["grade"]], -1) or round(0.1 * rate_total, -1)

    sp = S.new_spec(f"Random terminal - {o.preset}, seed {o.seed}")
    sp["description"] = (f"Generated instance: {_n(o.vessels, 'vessel')}, {_n(o.berths, 'berth')}, "
                         f"{_n(o.grades, 'grade')}, {_n(o.grades * o.tanks_per_grade, 'tank')}, "
                         f"{_n(o.cdus, 'crude unit')}, {o.periods} periods of "
                         f"{o.period_h:g} h. Congestion {o.congestion:g}, tightness {o.tightness:g}"
                         + (f", {o.scenarios} arrival-delay scenarios" if o.scenarios else "") + ". "
                         f"Options: {_options_text(o)}.")
    lay = sp["layers"]
    lay["grid"] = {"periods": o.periods, "period_h": o.period_h, "grades": grades, "start": "2026-11-16 06:00"}
    b = L.new_layer(sp, "berth")
    b["name"] = "Berth allocation"
    b["config"].update(vessels=vessels, berths=berths, hookup_h=hook, release_h=rel)
    lay["items"].append(b)
    t = L.new_layer(sp, "tank_farm")
    t["name"] = "Tank farm"
    t["config"].update(tanks=tanks, deliveries=deliveries, demand=demand, end_fraction=0.5,
                       no_simultaneous=bool(o.tank_modes))
    lay["items"].append(t)
    c = L.new_layer(sp, "cdu")
    c["name"] = "Crude units"
    c["config"].update(units=units, crudes=crudes)
    lay["items"].append(c)
    sp["solver"]["time_limit"] = 120.0
    sp["solver"]["mip_gap"] = 0.005

    if o.scenarios:
        scen = []
        for s in range(o.scenarios):
            changes = []
            for v in vessels:
                if s and rng.random() < 0.5:
                    d = round(rng.uniform(1.0, o.max_delay_h), 1)
                    changes.append({"param": f"{b['id']}_arr", "index": v["name"], "op": "add", "value": d})
            scen.append({"name": "OnTime" if s == 0 else f"Delay{s}", "probability": 0.0, "changes": changes})
        for sc in scen:
            sc["probability"] = round(1.0 / o.scenarios, 12)
        scen[-1]["probability"] = 1.0 - sum(sc["probability"] for sc in scen[:-1])
        sp["stochastic"].update(enabled=True, scenarios=scen)
    return S.normalize(sp)


def _n(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _options_text(o: GenOptions) -> str:
    d = asdict(o)
    return ", ".join(f"{f.name}={d[f.name]}" for f in fields(o))


def generate_checked(opts: GenOptions, solve_opts=None, attempts: int = 5, log=None):
    """Generate and solve. If the instance has no solution, try the next seeds.

    Return ``(spec, result, seed_used)``. Needs Pyomo and a solver.
    """
    from . import engine as E
    o = opts.resolved()
    last = None
    for i in range(attempts):
        trial = copy.copy(o)
        trial.seed = o.seed + i
        spec = generate(trial)
        res = E.solve(spec, solve_opts or E.SolverOptions(name="appsi_highs", time_limit=120, mip_gap=0.005,
                                                          tee=False))
        if log:
            log(f"seed {trial.seed}: {res.message}" + (f", objective {res.objective:,.0f}" if res.ok else ""))
        if res.ok:
            return spec, res, trial.seed
        last = res
    raise RuntimeError(f"No feasible instance in {attempts} seeds from {o.seed}: {last.message if last else ''}")
