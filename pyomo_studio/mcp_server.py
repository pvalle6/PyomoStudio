"""MCP server that exposes a Pyomo Studio session as tools.

An agent can load a spec, edit components, solve, inspect the plan and
export a Pyomo script or HTML report. The desktop GUI is not required.

Run over stdio (Grok, Claude, Cursor):

    python -m pyomo_studio mcp

Needs the ``mcp`` extra:  pip install "pyomo-studio[mcp]"
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import Field

from . import APP_NAME, __version__
from .session import SessionError, StudioSession, example_path

try:
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ResourceNotFoundError, ToolError
except ImportError:  # mcp 1.x used the FastMCP name
    try:
        from mcp.server.fastmcp import FastMCP as MCPServer
        from mcp.server.fastmcp.exceptions import ResourceError as ToolError

        class ResourceNotFoundError(ToolError):  # type: ignore[no-redef]
            pass
    except ImportError as exc:  # pragma: no cover - install extra
        raise SystemExit(
            "The MCP extra is not installed. Install it with:\n"
            '  python -m pip install "mcp>=1.2"\n'
            f"(import error: {exc})"
        ) from exc

INSTRUCTIONS = """\
Pyomo Studio MCP. Drive one in-memory optimization model (a JSON spec).

Typical loop:
1. list_examples, then load_example, or new_model / load_model / load_spec_json.
2. upsert_component and patch_model to edit sets, parameters, variables,
   constraints, objectives, solver, schedule or stochastic data.
3. validate_model, then solve_model (HiGHS by default) or analyze_stochastic.
4. get_solution / get_schedule, then write_report or export_script.

Expressions are Python/Pyomo, for example
`sum(x[v, b] for b in B) == 1`. Open files only from sources you trust.
Component kinds: sets, params, variables, expressions, constraints, objectives.
"""

mcp = MCPServer(
    name="pyomo-studio",
    title=APP_NAME,
    version=__version__,
    instructions=INSTRUCTIONS,
)

_SESSION = StudioSession()


def get_session() -> StudioSession:
    return _SESSION


def reset_session(workspace: Path | None = None) -> StudioSession:
    global _SESSION
    _SESSION = StudioSession(workspace=workspace or Path.cwd())
    return _SESSION


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except SessionError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
def list_examples() -> list[dict[str, str]]:
    """List the bundled example models (BAP and a production LP)."""
    return _call(_SESSION.list_examples)


@mcp.tool()
def new_model(name: str = Field(default="Untitled model", description="Model title")) -> dict[str, Any]:
    """Start a blank spec. Replaces the open model."""
    return _call(_SESSION.new_model, name)


@mcp.tool()
def load_example(name: str = Field(description="Example stem, for example production_lp or bap_discrete")) -> dict[str, Any]:
    """Open a bundled example. Replaces the open model."""
    return _call(_SESSION.load_example, name)


@mcp.tool()
def load_model(path: str = Field(description="Path to a .json model file, relative to the workspace or absolute")) -> dict[str, Any]:
    """Open a model JSON file. Replaces the open model."""
    return _call(_SESSION.load_model, path)


@mcp.tool()
def load_spec_json(
    spec_json: str | dict[str, Any] = Field(description="Full model spec as a JSON object, or a JSON object string"),
) -> dict[str, Any]:
    """Open a spec from JSON. Replaces the open model."""
    if isinstance(spec_json, dict):
        return _call(_SESSION.load_spec_json, json.dumps(spec_json))
    return _call(_SESSION.load_spec_json, spec_json)


@mcp.tool()
def save_model(path: str = Field(description="Destination .json path")) -> dict[str, str]:
    """Write the open spec to a JSON file."""
    saved = _call(_SESSION.save_model, path)
    return {"path": saved}


@mcp.tool()
def get_model(full: bool = Field(default=False, description="If true, include the full spec JSON")) -> dict[str, Any]:
    """Return a summary of the open spec, optionally the full JSON."""
    return _call(_SESSION.get_model, full=full)


@mcp.tool()
def validate_model() -> dict[str, Any]:
    """Check the open spec for errors that would stop a build."""
    return _call(_SESSION.validate_model)


@mcp.tool()
def upsert_component(
    kind: str = Field(description="sets | params | variables | expressions | constraints | objectives"),
    item: dict[str, Any] = Field(description="Component object; must include name. Other fields merge onto the existing item."),
) -> dict[str, Any]:
    """Add or replace one component. On replace, fields you omit stay as they were."""
    return _call(_SESSION.upsert_component, kind, item)


@mcp.tool()
def remove_component(
    kind: str = Field(description="sets | params | variables | expressions | constraints | objectives"),
    name: str = Field(description="Component name to remove"),
) -> dict[str, Any]:
    """Remove one component by kind and name."""
    return _call(_SESSION.remove_component, kind, name)


@mcp.tool()
def patch_model(
    patch: dict[str, Any] = Field(description="Top-level keys to merge: name, description, solver, schedule, stochastic, hook"),
) -> dict[str, Any]:
    """Update solver, schedule, stochastic, name, description or hook. Not component lists."""
    return _call(_SESSION.patch_model, patch)


@mcp.tool()
def list_solvers() -> dict[str, Any]:
    """Show which solvers Pyomo can find on this machine."""
    return _call(_SESSION.list_solvers)


@mcp.tool()
def solve_model(
    solver: str | None = Field(default=None, description="Solver name, default from the spec (usually appsi_highs)"),
    time_limit: float | None = Field(default=None, description="Seconds"),
    mip_gap: float | None = Field(default=None, description="Relative MIP gap"),
    include_values: bool = Field(default=False, description="Include variable values (can be large)"),
    variable: str | None = Field(default=None, description="If set with include_values, only this variable"),
) -> dict[str, Any]:
    """Validate, build and solve the open model. Returns status, objective and stats."""
    return _call(_SESSION.solve_model, solver, time_limit, mip_gap, include_values, variable)


@mcp.tool()
def analyze_stochastic(
    solver: str | None = Field(default=None, description="Solver name"),
    time_limit: float | None = Field(default=None, description="Seconds per subproblem"),
) -> dict[str, Any]:
    """Compute RP, WS, EV, EEV, EVPI and VSS for a two-stage stochastic model."""
    return _call(_SESSION.analyze_stochastic, solver, time_limit)


@mcp.tool()
def get_solution(
    variable: str | None = Field(default=None, description="If set, only this variable or expression"),
    include_values: bool = Field(default=True, description="Include value tables"),
) -> dict[str, Any]:
    """Return the last solve result."""
    return _call(_SESSION.get_solution, variable, include_values)


@mcp.tool()
def get_schedule(
    scenario: str | None = Field(default=None, description="Scenario name; omit for all"),
) -> dict[str, Any]:
    """Return Gantt / space-time schedule rows from the last solve."""
    return _call(_SESSION.get_schedule, scenario)


@mcp.tool()
def build_preview() -> dict[str, Any]:
    """Build the Pyomo model without solving. Returns statistics and a listing."""
    return _call(_SESSION.build_preview)


@mcp.tool()
def write_report(
    path: str = Field(description="Output path. Suffix .html, .md, .json or .csv selects the format"),
    fmt: str = Field(default="html", description="html | md | json | csv when the suffix is missing"),
) -> dict[str, str]:
    """Write an HTML, Markdown, JSON or CSV plan for the last solve."""
    saved = _call(_SESSION.write_report, path, fmt)
    return {"path": saved}


@mcp.tool()
def export_script(path: str = Field(description="Destination .py path")) -> dict[str, str]:
    """Write a standalone Pyomo script for the open spec."""
    saved = _call(_SESSION.export_script, path)
    return {"path": saved}


@mcp.tool()
def write_lp(path: str = Field(description="Destination .lp, .mps, .nl or .gms path")) -> dict[str, str]:
    """Write the built model to an LP, MPS, NL or GMS file."""
    saved = _call(_SESSION.write_model_file, path)
    return {"path": saved}


@mcp.resource("pyomo://examples/{name}")
def example_resource(name: str) -> str:
    """Bundled example model JSON."""
    try:
        path = example_path(name)
    except SessionError as exc:
        raise ResourceNotFoundError(str(exc)) from exc
    return path.read_text(encoding="utf-8")


@mcp.resource("pyomo://model/current")
def current_model_resource() -> str:
    """Open spec as JSON."""
    try:
        spec = _SESSION._require_spec()
    except SessionError as exc:
        raise ResourceNotFoundError(str(exc)) from exc
    from . import spec as S
    return S.dumps(spec)


@mcp.prompt()
def draft_model(problem: str, model_class: str = "MILP") -> str:
    """Prompt to turn a planning problem into a Pyomo Studio spec."""
    return (
        "You are building a Pyomo Studio model spec (JSON) for this problem.\n"
        f"Problem class: {model_class}.\n\n{problem}\n\n"
        "Use the pyomo-studio MCP tools. Start with new_model, then upsert_component "
        "for each set, parameter, variable, constraint and the single active objective. "
        "Expressions use Pyomo/Python, for example sum(x[i] for i in I) <= cap. "
        "Call validate_model before solve_model. Prefer appsi_highs for LP/MILP."
    )


@mcp.prompt()
def diagnose_infeasible() -> str:
    """Prompt to inspect a failed or infeasible last solve."""
    return (
        "The last Pyomo Studio solve failed or is infeasible. Use get_model(full=true), "
        "validate_model and get_solution. Check bounds, demand vs capacity, and "
        "stochastic non-anticipativity. Suggest the smallest spec change that restores "
        "feasibility, then validate_model and solve_model again."
    )


def run(transport: str = "stdio", **kwargs: Any) -> None:
    mcp.run(transport=transport, **kwargs)  # type: ignore[arg-type]


if __name__ == "__main__":
    run()
