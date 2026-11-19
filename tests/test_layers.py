"""Layer tests: compose, ports and fallbacks, custom layers, and solves of the refinery example.

Run:  python -m pytest tests
"""
from __future__ import annotations

import copy
import itertools
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyomo_studio import codegen, engine as E, layers as L, schedule as SCH, spec as S  # noqa: E402

EX = Path(__file__).resolve().parents[1] / "pyomo_studio" / "examples"
OPTS = E.SolverOptions(name="appsi_highs", time_limit=300, mip_gap=0.0, tee=False)
IDS = ("berth", "tank", "cdu")


def refinery(**enabled) -> dict:
    spec = S.load_spec(EX / "refinery_terminal.json")
    for it in spec["layers"]["items"]:
        it["enabled"] = enabled.get(it["id"], True)
    return spec


def by_name(spec: dict, kind: str) -> dict:
    return {it["name"]: it for it in spec[kind]}


# ---------------------------------------------------------------------------
# Compose (no solver)
# ---------------------------------------------------------------------------

def test_compose_without_layers_keeps_the_model():
    spec = S.load_spec(EX / "bap_discrete.json")
    flat = L.compose(spec)
    for kind in S.COMPONENT_KINDS:
        assert [i["name"] for i in flat[kind]] == [i["name"] for i in spec[kind]]
    assert "layers" not in flat


def test_compose_is_idempotent_and_does_not_change_the_input():
    spec = refinery()
    before = copy.deepcopy(spec)
    flat = L.compose(spec)
    assert L.compose(flat) is flat
    assert spec == before


def test_all_layers_linked_through_ports():
    flat = L.compose(refinery())
    cons = by_name(flat, "constraints")
    assert "berth_crude_receipt[g, k]" in cons["tank_Receive"]["expr"]
    assert "tank_crude_supply[g, k]" in cons["cdu_Supply"]["expr"]
    # The berth layer adds its pumping periods only because the tank layer imports them.
    assert "berth_z" in by_name(flat, "variables")
    # The tank fallbacks are not in the model.
    params = by_name(flat, "params")
    assert "tank_delivery" not in params and "tank_demand" not in params
    obj = [o for o in flat["objectives"] if o["active"]]
    assert [o["name"] for o in obj] == ["TotalCost"]
    # One cost measure per layer that has cost terms (the linked tank farm has none: no penalties apply).
    assert {"Cost_berth", "Cost_cdu"} <= set(by_name(flat, "objectives"))
    assert "Cost_tank" not in by_name(flat, "objectives")


def test_disabled_provider_uses_fallback():
    flat = L.compose(refinery(berth=False))
    cons = by_name(flat, "constraints")
    assert "tank_delivery" in cons["tank_Receive"]["expr"]
    assert not any(n.startswith("berth_") for n in S.component_names(flat))


def test_disabled_consumer_uses_fallback_demand_and_no_pumping_periods():
    flat = L.compose(refinery(cdu=False))
    assert "tank_Demand" in by_name(flat, "constraints")
    flat = L.compose(refinery(tank=False))
    assert "berth_z" not in by_name(flat, "variables")       # nobody takes the crude
    assert "cdu_available" in by_name(flat, "params")


def test_layer_schedule_view_is_used():
    flat = L.compose(refinery())
    assert flat["schedule"]["type"] == "gantt"
    assert flat["schedule"]["resource"] == "which(berth_x, v)"


def test_two_exporters_of_one_port_is_an_error():
    spec = refinery()
    extra = L.new_layer(spec, "custom")
    extra["config"]["exports"] = [{"port": "crude_receipt", "component": "q", "index": "g in GRADES, k in PERIODS"}]
    spec["layers"]["items"].append(extra)
    rep = S.validate(spec)
    assert not rep.ok and "only one enabled layer" in rep.errors[0].message.lower()


def test_unknown_grade_is_an_error():
    spec = refinery()
    spec["layers"]["items"][0]["config"]["vessels"][0]["grade"] = "XXX"
    rep = S.validate(spec)
    assert not rep.ok and "XXX" in rep.errors[0].message


def test_component_tag_of_missing_layer_is_an_error():
    spec = refinery()
    spec["constraints"].append({**S.new_item("constraints", "Stray"), "expr": "1 <= 2", "layer": "nolayer"})
    rep = S.validate(spec)
    assert not rep.ok and "nolayer" in rep.errors[0].message


def test_bad_layer_id():
    spec = refinery()
    spec["layers"]["items"][0]["id"] = "bad id"
    assert not S.validate(spec).ok


# ---------------------------------------------------------------------------
# Custom layer
# ---------------------------------------------------------------------------

def _custom_spec(provider_on: bool) -> dict:
    """A tank-farm layer feeds a form-built 'blender' layer that imports crude_supply."""
    spec = refinery(berth=False, cdu=False)
    spec["layers"]["items"][1]["enabled"] = provider_on
    lay = L.new_layer(spec, "custom")
    lay["id"] = "blend"
    lay["config"]["imports"] = [{"port": "crude_supply", "alias": "sup", "index": "g in GRADES, k in PERIODS",
                                 "fallback": "1000"}]
    lay["config"]["cost"] = "-sum(blend_take[g, k] for g in GRADES for k in PERIODS)"
    spec["layers"]["items"].append(lay)
    spec["variables"].append({**S.new_item("variables", "blend_take"), "index": "g in GRADES, k in PERIODS",
                              "layer": "blend"})
    spec["constraints"].append({**S.new_item("constraints", "BlendTake"), "index": "g in GRADES, k in PERIODS",
                                "expr": "blend_take[g, k] <= sup[g, k]", "layer": "blend"})
    return spec


def test_custom_layer_import_links_and_falls_back():
    flat = L.compose(_custom_spec(True))
    assert by_name(flat, "expressions")["sup"]["expr"] == "tank_crude_supply[g, k]"
    assert "tank_Demand" not in by_name(flat, "constraints")    # the custom layer takes the crude
    flat = L.compose(_custom_spec(False))
    assert by_name(flat, "expressions")["sup"]["expr"] == "1000"


def test_custom_layer_off_removes_its_components():
    spec = _custom_spec(True)
    spec["layers"]["items"][-1]["enabled"] = False
    flat = L.compose(spec)
    names = S.component_names(flat)
    assert "blend_take" not in names and "BlendTake" not in names and "sup" not in names
    assert "tank_Demand" in by_name(flat, "constraints")


def test_custom_layer_solves():
    res = E.solve(_custom_spec(True), OPTS)
    assert res.ok, res.message
    take = res.scenarios[0].values["blend_take"]
    sup = res.scenarios[0].expressions["tank_crude_supply"]
    assert all(take[k] <= sup[k] + 1e-6 for k in take)
    assert sum(take.values()) > 0


# ---------------------------------------------------------------------------
# Solves
# ---------------------------------------------------------------------------

COMBOS = [dict(zip(IDS, bits)) for bits in itertools.product([True, False], repeat=3) if any(bits)]


@pytest.mark.parametrize("enabled", COMBOS, ids=lambda d: "+".join(k for k, v in d.items() if v))
def test_every_layer_combination_solves(enabled):
    spec = refinery(**enabled)
    assert S.validate(spec).ok
    res = E.solve(spec, OPTS)
    assert res.ok, res.message
    assert res.spec is not None and res.spec.get("_composed")
    # Fallback data in the example fits: no penalty volumes.
    vals = res.scenarios[0].values
    for name in ("tank_reject", "tank_short"):
        if name in vals:
            assert sum(vals[name].values()) < 1e-6, name


def test_linked_plan_is_consistent():
    res = E.solve(refinery(), OPTS)
    assert res.ok
    assert math.isclose(res.objective, -3309280.0, rel_tol=1e-6)
    sc = res.scenarios[0]
    v, e = sc.values, sc.expressions
    flat = res.spec
    vol = {r[0]: r[1] for r in by_name(flat, "params")["berth_vol"]["values"]}
    grade = dict(by_name(flat, "sets")["berth_VG"]["elements"])
    received = {}
    for (vessel, k), q in v["berth_q"].items():
        received[vessel] = received.get(vessel, 0.0) + q
        if q > 1e-6:   # pumping lies inside the berth window
            assert v["berth_t"][vessel] <= (k - 1) * 2.0 + 1e-6
            assert v["berth_dep"][vessel] >= k * 2.0 - 1e-6
    for vessel, total in received.items():
        assert math.isclose(total, vol[vessel], rel_tol=1e-6)
    # Mass balance of the whole terminal for each grade.
    tanks = dict(by_name(flat, "sets")["tank_IG"]["elements"])
    init = {r[0]: r[1] for r in by_name(flat, "params")["tank_initial"]["values"]}
    for g in set(grade.values()):
        opening = sum(init[i] for i, gg in tanks.items() if gg == g)
        closing = sum(v["tank_inv"][(i, 36)] for i, gg in tanks.items() if gg == g)
        rec = sum(received[x] for x, gg in grade.items() if gg == g)
        fed = sum(val for (gg, _k), val in e["cdu_feed"].items() if gg == g)
        assert math.isclose(opening + rec - fed, closing, rel_tol=1e-6, abs_tol=1e-3)
    sched = SCH.compute_schedule(res.spec, res.built)
    assert len(sched.tasks) == 5


def test_tank_ullage_costs_berth_time():
    """The tank layer can only make the berth plan worse (it adds limits)."""
    alone = E.solve(refinery(tank=False, cdu=False), OPTS)
    linked = E.solve(refinery(), OPTS)
    assert alone.ok and linked.ok
    assert linked.scenarios[0].kpis["Cost_berth"] >= alone.objective - 1e-6


def test_stochastic_layers():
    spec = refinery()
    spec["stochastic"] = {"enabled": True, "risk": {"measure": "expected", "alpha": 0.9, "weight": 0.0},
                          "scenarios": [
                              {"name": "OnTime", "probability": 0.6, "changes": []},
                              {"name": "Late", "probability": 0.4, "changes": [
                                  {"param": "berth_arr", "index": "V3", "op": "add", "value": 10}]}]}
    res = E.solve(spec, E.SolverOptions(name="appsi_highs", time_limit=300, mip_gap=1e-3, tee=False))
    assert res.ok, res.message
    x0, x1 = (sc.values["berth_x"] for sc in res.scenarios)
    assert all(abs(x0[k] - x1[k]) < 1e-6 for k in x0)      # berth plan is first stage


def test_export_script_compiles():
    compile(codegen.generate(refinery()), "refinery.py", "exec")
