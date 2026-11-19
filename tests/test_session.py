"""Session used by the MCP server: load, edit, validate, solve, export."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyomo_studio.session import SessionError, StudioSession, summarize_spec  # noqa: E402

EX = Path(__file__).resolve().parents[1] / "pyomo_studio" / "examples"


def test_list_and_load_example():
    s = StudioSession()
    names = {e["name"] for e in s.list_examples()}
    assert {"production_lp", "bap_discrete", "bap_continuous", "bap_stochastic"} <= names
    summary = s.load_example("production_lp")
    assert summary["name"].startswith("Production")
    assert {v["name"] for v in summary["variables"]} == {"make"}
    assert s.validate_model()["ok"]


def test_new_model_and_upsert():
    s = StudioSession()
    s.new_model("Tiny LP")
    s.upsert_component("sets", {"name": "P", "kind": "list", "elements": ["A", "B"]})
    s.upsert_component("params", {
        "name": "profit", "index": "i in P",
        "values": [["A", 3], ["B", 5]],
    })
    s.upsert_component("variables", {"name": "x", "index": "i in P", "domain": "NonNegativeReals"})
    s.upsert_component("constraints", {
        "name": "cap", "expr": "sum(x[i] for i in P) <= 10",
    })
    s.upsert_component("objectives", {
        "name": "obj", "sense": "maximize", "expr": "sum(profit[i] * x[i] for i in P)",
    })
    rep = s.validate_model()
    assert rep["ok"], rep["issues"]
    result = s.solve_model(time_limit=30)
    assert result["ok"], result
    assert math.isclose(result["objective"], 50.0, rel_tol=1e-4)


def test_upsert_replaces_and_remove():
    s = StudioSession()
    s.load_example("production_lp")
    first = s.upsert_component("params", {"name": "profit", "values": [["Bench", 1]]})
    assert first["action"] == "replaced"
    assert first["item"]["index"] == "i in P"
    gone = s.remove_component("params", "demand")
    assert all(p["name"] != "demand" for p in gone["summary"]["params"])
    try:
        s.remove_component("params", "demand")
        raise AssertionError("expected SessionError")
    except SessionError:
        pass


def test_patch_solver_and_unknown_kind():
    s = StudioSession()
    s.load_example("production_lp")
    summary = s.patch_model({"solver": {"time_limit": 12, "name": "appsi_highs"}, "name": "Patched"})
    assert summary["name"] == "Patched"
    assert summary["solver"]["time_limit"] == 12
    try:
        s.patch_model({"sets": []})
        raise AssertionError("expected SessionError")
    except SessionError:
        pass
    try:
        s.upsert_component("widgets", {"name": "x"})
        raise AssertionError("expected SessionError")
    except SessionError:
        pass


def test_save_roundtrip(tmp_path: Path):
    s = StudioSession(workspace=tmp_path)
    s.load_example("production_lp")
    out = s.save_model("saved.json")
    assert Path(out).is_file()
    other = StudioSession(workspace=tmp_path)
    loaded = other.load_model("saved.json")
    assert loaded["name"] == s.spec["name"]


def test_load_spec_json_and_export(tmp_path: Path):
    s = StudioSession(workspace=tmp_path)
    raw = (EX / "production_lp.json").read_text(encoding="utf-8")
    s.load_spec_json(raw)
    script = Path(s.export_script("model.py"))
    assert "ConcreteModel" in script.read_text(encoding="utf-8")
    compile(script.read_text(encoding="utf-8"), str(script), "exec")


def test_solve_and_report(tmp_path: Path):
    s = StudioSession(workspace=tmp_path)
    s.load_example("production_lp")
    result = s.solve_model(include_values=True, variable="make")
    assert result["ok"]
    assert math.isclose(result["objective"], 6050.0, rel_tol=1e-4)
    assert "make" in result["scenarios"][0]["values"]
    html = Path(s.write_report("plan.html"))
    assert "Summary" in html.read_text(encoding="utf-8")
    md = Path(s.write_report("plan.md", fmt="md"))
    assert "Summary" in md.read_text(encoding="utf-8")
    lp = Path(s.write_model_file("model.lp"))
    assert lp.stat().st_size > 0
    preview = s.build_preview()
    assert preview["stats"]["class"] == "LP"


def test_schedule_from_bap():
    s = StudioSession()
    s.load_example("bap_discrete")
    s.solve_model()
    rows = s.get_schedule()
    assert "deterministic" in rows or len(rows) >= 1
    flat = next(iter(rows.values()))
    labels = {r["task"] for r in flat}
    assert "V02" in labels


def test_errors_without_model():
    s = StudioSession()
    try:
        s.validate_model()
        raise AssertionError("expected SessionError")
    except SessionError:
        pass
    try:
        s.get_solution()
        raise AssertionError("expected SessionError")
    except SessionError:
        pass
    try:
        s.load_example("no_such_model")
        raise AssertionError("expected SessionError")
    except SessionError:
        pass


def test_summarize_spec_shape():
    s = StudioSession()
    s.load_example("bap_stochastic")
    summary = summarize_spec(s.spec)
    assert summary["stochastic"]["enabled"] is True
    assert summary["stochastic"]["n_scenarios"] >= 2
    assert summary["schedule"]["type"] in {"gantt", "space_time", "none"}


def test_mcp_tools_register():
    import asyncio
    from pyomo_studio.mcp_server import mcp, reset_session
    reset_session()
    listed = asyncio.run(mcp.list_tools())
    tools = {t.name for t in listed}
    needed = {
        "list_examples", "new_model", "load_example", "load_model", "load_spec_json",
        "save_model", "get_model", "validate_model", "upsert_component", "remove_component",
        "patch_model", "list_solvers", "solve_model", "analyze_stochastic", "get_solution",
        "get_schedule", "build_preview", "write_report", "export_script", "write_lp",
    }
    assert needed <= tools


def test_mcp_client_load_example():
    import asyncio
    from mcp import Client
    from pyomo_studio.mcp_server import mcp, reset_session

    reset_session()

    async def go():
        async with Client(mcp) as client:
            tools = await client.list_tools()
            names = {t.name for t in tools.tools}
            assert "load_example" in names
            result = await client.call_tool("load_example", {"name": "production_lp"})
            data = result.structured_content
            assert data["name"].startswith("Production")
            v = await client.call_tool("validate_model", {})
            assert v.structured_content["ok"] is True

    asyncio.run(go())


if __name__ == "__main__":
    import inspect
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            params = inspect.signature(fn).parameters
            if "tmp_path" in params:
                import tempfile
                with tempfile.TemporaryDirectory() as d:
                    fn(Path(d))
            else:
                fn()
            print("passed", name)
