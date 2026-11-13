"""Install check: solve the examples with real Pyomo and HiGHS.

Run:  python -m pytest tests   (or: python tests/test_examples.py)
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyomo_studio import codegen, engine as E, report as R, schedule as SCH, spec as S  # noqa: E402

EX = Path(__file__).resolve().parents[1] / "pyomo_studio" / "examples"
OPTS = E.SolverOptions(name="appsi_highs", time_limit=300, mip_gap=0.0, tee=False)

EXPECTED = {  # optimal objective values
    "production_lp": 6050.0,
    "bap_discrete": 189.0,
    "bap_continuous": 420.2667,
    "bap_stochastic": 343.85,
}


def _solve(name: str):
    spec = S.load_spec(EX / f"{name}.json")
    assert S.validate(spec).ok
    res = E.solve(spec, OPTS)
    assert res.ok, res.message
    return spec, res


def test_objectives():
    for name, want in EXPECTED.items():
        spec, res = _solve(name)
        assert math.isclose(res.objective, want, rel_tol=1e-4), (name, res.objective)
        schedules = {sc.name: SCH.compute_schedule(spec, res.built, sc.name) for sc in res.scenarios}
        html, md = R.make_report(spec, res, schedules)
        assert "Summary" in md
        if spec["schedule"]["type"] != "none":
            assert "<svg" in html


def test_discrete_alarms():
    spec, res = _solve("bap_discrete")
    sched = SCH.compute_schedule(spec, res.built)
    late = sorted(t.label for t in sched.tasks if t.state == "alarm")
    assert late == ["V02", "V04"], late


def test_stochastic_analysis():
    spec = S.load_spec(EX / "bap_stochastic.json")
    a = E.stochastic_analysis(spec, OPTS)
    assert math.isclose(a["RP"], 343.85, rel_tol=1e-4)
    assert math.isclose(a["WS"], 312.645, rel_tol=1e-4)
    assert a["EVPI"] >= -1e-6 and a["VSS"] >= -1e-6


def test_export_script_compiles():
    for name in EXPECTED:
        spec = S.load_spec(EX / f"{name}.json")
        compile(codegen.generate(spec), f"{name}.py", "exec")


if __name__ == "__main__":
    for fn in (test_objectives, test_discrete_alarms, test_stochastic_analysis, test_export_script_compiles):
        fn()
        print("passed", fn.__name__)
