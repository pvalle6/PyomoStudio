"""Random instance generator: determinism, validity, feasibility, scenarios, CLI."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyomo_studio import engine as E, generate as G, spec as S  # noqa: E402
from pyomo_studio.__main__ import main  # noqa: E402

OPTS = E.SolverOptions(name="appsi_highs", time_limit=120, mip_gap=0.005, tee=False)


def test_same_seed_same_model():
    a = G.generate(G.GenOptions(seed=11, preset="small"))
    b = G.generate(G.GenOptions(seed=11, preset="small"))
    c = G.generate(G.GenOptions(seed=12, preset="small"))
    assert S.dumps(a) == S.dumps(b)
    assert S.dumps(a) != S.dumps(c)


@pytest.mark.parametrize("preset", list(G.PRESETS))
def test_presets_are_valid(preset):
    for seed in range(1, 6):
        spec = G.generate(G.GenOptions(seed=seed, preset=preset))
        rep = S.validate(spec)
        assert rep.ok, (seed, [str(i) for i in rep.errors])
        p = G.PRESETS[preset]
        cfg = {it["id"]: it["config"] for it in spec["layers"]["items"]}
        assert len(cfg["berth"]["vessels"]) == p["vessels"]
        assert len(cfg["tank"]["tanks"]) == p["grades"] * p["tanks_per_grade"]
        assert len(cfg["cdu"]["units"]) == p["cdus"]
        lengths = [b["max_length"] for b in cfg["berth"]["berths"]]
        assert all(v["length"] <= max(lengths) for v in cfg["berth"]["vessels"])


def test_overrides_and_bad_options():
    spec = G.generate(G.GenOptions(seed=2, preset="tiny", vessels=4, periods=30))
    assert len(spec["layers"]["items"][0]["config"]["vessels"]) == 4
    assert spec["layers"]["grid"]["periods"] == 30
    for bad in (dict(preset="huge"), dict(congestion=1.5), dict(scenarios=1), dict(grades=99)):
        with pytest.raises(ValueError):
            G.generate(G.GenOptions(**bad))


@pytest.mark.parametrize("knobs", [(0.0, 0.0), (0.5, 0.5), (1.0, 1.0)], ids=["loose", "mid", "tight"])
def test_tiny_instances_solve(knobs):
    cong, tight = knobs
    for seed in range(1, 6):
        res = E.solve(G.generate(G.GenOptions(seed=seed, preset="tiny", congestion=cong, tightness=tight)), OPTS)
        assert res.ok, (seed, res.message)


def test_small_instance_solves_with_every_layer_combination():
    spec = G.generate(G.GenOptions(seed=4, preset="small"))
    for off in (None, "berth", "tank", "cdu"):
        s = json.loads(json.dumps(spec, default=list))
        s = S.normalize(s)
        for it in s["layers"]["items"]:
            it["enabled"] = it["id"] != off
        res = E.solve(s, OPTS)
        assert res.ok, (off, res.message)


def test_scenarios():
    spec = G.generate(G.GenOptions(seed=3, preset="tiny", scenarios=3))
    st = spec["stochastic"]
    assert st["enabled"] and len(st["scenarios"]) == 3
    assert abs(sum(s["probability"] for s in st["scenarios"]) - 1) < 1e-9
    assert st["scenarios"][0]["changes"] == []
    res = E.solve(spec, OPTS)
    assert res.ok and res.stochastic and len(res.scenarios) == 3


def test_cli_generate(tmp_path):
    out = tmp_path / "g.json"
    assert main(["generate", str(out), "--preset", "tiny", "--seed", "5", "--vessels", "2"]) == 0
    spec = S.load_spec(out)
    assert S.validate(spec).ok
    assert len(spec["layers"]["items"][0]["config"]["vessels"]) == 2
    assert main(["generate", str(out), "--congestion", "3"]) == 2


def test_medium_preset_is_tractable_and_tank_modes_pass_through():
    spec = G.generate(G.GenOptions(seed=1, preset="medium"))
    tank = next(it for it in spec["layers"]["items"] if it["type"] == "tank_farm")
    assert tank["config"]["no_simultaneous"] is False
    res = E.solve(spec, OPTS)
    assert res.ok, res.message
    spec = G.generate(G.GenOptions(seed=1, preset="medium", tank_modes=True))
    assert next(it for it in spec["layers"]["items"] if it["type"] == "tank_farm")["config"]["no_simultaneous"]
