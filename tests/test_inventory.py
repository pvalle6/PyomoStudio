"""Tank inventory view: data from a solve, schematic and trend layout, report section."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyomo_studio import engine as E, inventory as I, report as R, spec as S  # noqa: E402

EX = Path(__file__).resolve().parents[1] / "pyomo_studio" / "examples"
OPTS = E.SolverOptions(name="appsi_highs", time_limit=300, mip_gap=0.0, tee=False)


def _solve(**enabled):
    spec = S.load_spec(EX / "refinery_terminal.json")
    for it in spec["layers"]["items"]:
        it["enabled"] = enabled.get(it["id"], True)
    res = E.solve(spec, OPTS)
    assert res.ok, res.message
    return res


@pytest.fixture(scope="module")
def linked():
    return _solve()


def test_linked_data(linked):
    inv = I.compute(linked.spec, linked)
    assert (inv.source_kind, inv.source_layer, inv.sink_kind, inv.sink_layer) == ("berth", "berth", "cdu", "cdu")
    assert [t.name for t in inv.tanks] == ["T101", "T102", "T201", "T202", "T301", "T302"]
    assert inv.periods == 36 and inv.period_h == 2.0 and inv.origin is not None
    for t in inv.tanks:                                  # stock balance of each tank
        for k in range(1, inv.periods + 1):
            assert math.isclose(t.level(k), t.level(k - 1) + t.fin[k - 1] - t.fout[k - 1], abs_tol=1e-4)
            assert t.heel - 1e-4 <= t.level(k) <= t.capacity + 1e-4
    for g in inv.grades:                                 # what the vessels pump goes into the tanks
        for k in range(1, inv.periods + 1):
            pumped = sum(f.volume for f in inv.inflows.get((g, k), []))
            assert math.isclose(pumped, inv.received(g, k), abs_tol=1e-4)
            fed = sum(u.blend[k - 1].get(g, 0.0) for u in inv.units)
            assert math.isclose(fed, inv.sent(g, k), abs_tol=1e-4)
    assert [u.name for u in inv.units] == ["CDU1", "CDU2"]
    for u in inv.units:                                  # blend sulfur within the unit limit
        for k in range(1, inv.periods + 1):
            s = u.blend_sulfur(k)
            assert s is None or s <= u.max_sulfur + 1e-6


def test_states(linked):
    inv = I.compute(linked.spec, linked)
    t201 = next(t for t in inv.tanks if t.name == "T201")
    full = [k for k in range(1, 37) if t201.level(k) >= 0.95 * t201.capacity]
    assert full and all(t201.state(k)[0] == "warning" for k in full)
    c = inv.counts()
    assert c["alarms"] == 0 and c["warnings"] > 0
    # Hook-up and release periods are not waiting periods.
    notes = {f.note for fl in inv.inflows.values() for f in fl if f.note}
    assert notes <= {"hook-up or release", "WAITING, not pumping"}


def test_fallback_sources_and_sinks():
    inv = I.compute(*(lambda r: (r.spec, r))(_solve(berth=False)))
    assert inv.source_kind == "fixed" and inv.sink_kind == "cdu"
    assert any(f.label == "Fixed delivery" for fl in inv.inflows.values() for f in fl)
    inv = I.compute(*(lambda r: (r.spec, r))(_solve(cdu=False)))
    assert inv.source_kind == "berth" and inv.sink_kind == "fixed"
    assert inv.demand == {"LSW": 650.0, "ARL": 1200.0, "HSR": 350.0}
    assert not inv.units


def test_no_tank_layer():
    res = _solve(tank=False)
    assert I.compute_all(res.spec, res) == []
    with pytest.raises(I.InventoryError):
        I.compute(res.spec, res)


def test_layouts(linked):
    inv = I.compute(linked.spec, linked)
    for k in (1, 16, 36):
        prims, w, h = I.layout_schematic(inv, k)
        assert w >= 1100 and h > 400
        texts = {p.text for p in prims if p.kind == "text"}
        assert {"T101", "CDU1", "Crude units"} <= texts
    prims, w, h, geom = I.layout_trends(inv, 10)
    assert sum(1 for p in prims if p.kind == "path") == len(inv.tanks)
    assert geom.period_at(geom.x0 + 1e-6) == 1 and geom.period_at(geom.x1) == inv.periods
    assert "<polyline" in I.trends_svg(inv) and "<svg" in I.schematic_svg(inv, 5)
    csv = I.inventory_csv(inv).splitlines()
    assert len(csv) == 1 + len(inv.tanks) * inv.periods


def test_report_section(linked):
    html, md = R.make_report(linked.spec, linked, {})
    assert "Tank inventory - tank" in md and "Warning periods" in md
    assert "<polyline" in html
