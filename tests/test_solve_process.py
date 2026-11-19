"""Solves in a child process: same results, hard time-limit stop, user stop."""
from __future__ import annotations

import math
import multiprocessing as mp
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyomo_studio import engine as E, generate as G, inventory as I, schedule as SCH, spec as S  # noqa: E402

EX = Path(__file__).resolve().parents[1] / "pyomo_studio" / "examples"


def hard_model() -> dict:
    """A generated instance on which HiGHS searches for a long time."""
    return G.generate(G.GenOptions(seed=2, preset="medium", congestion=1.0, tightness=1.0, periods=48,
                                   period_h=2.0, tank_modes=True))


def test_isolated_solve_matches_in_process():
    spec = S.load_spec(EX / "refinery_terminal.json")
    a = E.solve(spec, E.SolverOptions(name="appsi_highs", time_limit=120, mip_gap=0, tee=False, isolate=False))
    b = E.solve(spec, E.SolverOptions(name="appsi_highs", time_limit=120, mip_gap=0, tee=False, isolate=True))
    assert a.ok and b.ok
    assert math.isclose(a.objective, b.objective, rel_tol=1e-9)
    # The values are loaded into the parent model: the result views work.
    assert len(SCH.compute_schedule(b.spec, b.built).tasks) == 5
    assert I.compute(b.spec, b).counts() == I.compute(a.spec, a).counts()


def test_duals_and_log_come_back():
    lines: list[str] = []
    res = E.solve(S.load_spec(EX / "production_lp.json"),
                  E.SolverOptions(name="appsi_highs", duals=True, tee=True), lines.append)
    assert res.ok and math.isclose(res.objective, 6050.0)
    assert any(c["dual"] is not None for c in res.scenarios[0].constraints)
    assert any("HiGHS" in ln for ln in lines)


def test_hard_stop_when_the_solver_ignores_its_limit():
    # The extra option gives HiGHS a long limit; the program limit is 3 s + 1 s grace.
    opts = E.SolverOptions(name="appsi_highs", time_limit=3, grace=1, mip_gap=0.005, tee=False,
                           extra={"time_limit": 1000})
    t = time.perf_counter()
    res = E.solve(hard_model(), opts)
    took = time.perf_counter() - t
    assert res.termination == E.HARD_STOP and not res.ok
    assert took < 30, took
    assert not mp.active_children()


def test_user_stop():
    cancel = E.Cancel()
    threading.Timer(3.0, cancel.set).start()
    t = time.perf_counter()
    res = E.solve(hard_model(), E.SolverOptions(name="appsi_highs", time_limit=None, tee=False), cancel=cancel)
    assert res.termination == E.USER_STOP and not res.ok
    assert time.perf_counter() - t < 30
    assert not mp.active_children()


def test_stopped_analysis_raises():
    cancel = E.Cancel()
    cancel.set()
    with pytest.raises(E.EngineError, match="stopped by the user"):
        E.stochastic_analysis(S.load_spec(EX / "bap_stochastic.json"),
                              E.SolverOptions(name="appsi_highs", tee=False), cancel=cancel)


def test_hard_limit_formula():
    assert E.hard_limit(E.SolverOptions(time_limit=None)) is None
    assert E.hard_limit(E.SolverOptions(time_limit=20)) == 30          # at least 10 s grace
    assert E.hard_limit(E.SolverOptions(time_limit=120)) == 150        # 25 % grace
    assert E.hard_limit(E.SolverOptions(time_limit=60, grace=2)) == 62
