"""In-memory Pyomo Studio session used by the MCP server and tests.

The GUI and CLI already load, validate, solve and export a spec. This module
holds one open spec plus the last solve so an agent can drive the same
operations without the desktop window.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import codegen, engine as E, report as R, schedule as SCH, spec as S

EXAMPLES_DIR = Path(__file__).resolve().parent / "examples"
LogFn = Callable[[str], None]


class SessionError(Exception):
    """A problem the agent can fix: missing model, bad path, or engine error."""


def _issue_dict(issue: S.Issue) -> dict[str, str]:
    return {"level": issue.level, "where": issue.where, "message": issue.message}


def _json_load(text: str) -> dict:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SessionError(f"The JSON is not valid: {exc}") from exc
    if not isinstance(data, dict):
        raise SessionError("A model file must be a JSON object.")
    return data


def example_names() -> list[str]:
    return sorted(p.stem for p in EXAMPLES_DIR.glob("*.json"))


def example_path(name: str) -> Path:
    stem = name.removesuffix(".json")
    path = EXAMPLES_DIR / f"{stem}.json"
    if not path.is_file():
        known = ", ".join(example_names()) or "(none)"
        raise SessionError(f"Unknown example '{name}'. Available: {known}.")
    return path


def summarize_spec(spec: dict) -> dict[str, Any]:
    """Compact inventory of a spec, without parameter tables or expressions."""
    st = spec.get("stochastic") or {}
    return {
        "name": spec.get("name", ""),
        "description": spec.get("description", ""),
        "sets": [{"name": x["name"], "kind": x.get("kind"), "index": "",
                  "n_elements": len(x.get("elements") or []),
                  "description": x.get("description", "")} for x in spec.get("sets", [])],
        "params": [{"name": x["name"], "index": x.get("index", ""),
                    "n_values": len(x.get("values") or []),
                    "description": x.get("description", "")} for x in spec.get("params", [])],
        "variables": [{"name": x["name"], "index": x.get("index", ""),
                       "domain": x.get("domain"), "stage": x.get("stage", 2),
                       "description": x.get("description", "")} for x in spec.get("variables", [])],
        "expressions": [{"name": x["name"], "index": x.get("index", ""),
                         "description": x.get("description", "")} for x in spec.get("expressions", [])],
        "constraints": [{"name": x["name"], "index": x.get("index", ""),
                         "active": x.get("active", True),
                         "description": x.get("description", "")} for x in spec.get("constraints", [])],
        "objectives": [{"name": x["name"], "sense": x.get("sense"),
                        "active": x.get("active", True),
                        "expr": x.get("expr", "")} for x in spec.get("objectives", [])],
        "stochastic": {
            "enabled": bool(st.get("enabled")),
            "n_scenarios": len(st.get("scenarios") or []),
            "risk": st.get("risk") or {},
        },
        "schedule": {"type": (spec.get("schedule") or {}).get("type", "none")},
        "solver": {
            "name": (spec.get("solver") or {}).get("name"),
            "time_limit": (spec.get("solver") or {}).get("time_limit"),
            "mip_gap": (spec.get("solver") or {}).get("mip_gap"),
        },
        "has_hook": bool((spec.get("hook") or "").strip()),
    }


def compact_result(result: E.SolveResult, *, include_values: bool = False,
                   variable: str | None = None, max_values: int = 80) -> dict[str, Any]:
    """JSON-ready solve summary. Full tables stay off unless asked for."""
    data = json.loads(R.result_json(result))
    if include_values:
        if variable:
            for sc in data.get("scenarios") or []:
                sc["values"] = {k: v for k, v in (sc.get("values") or {}).items() if k == variable}
                sc["expressions"] = {k: v for k, v in (sc.get("expressions") or {}).items() if k == variable}
        for sc in data.get("scenarios") or []:
            for bucket in ("values", "expressions"):
                trimmed = {}
                n = 0
                for name, vals in (sc.get(bucket) or {}).items():
                    if n >= max_values:
                        trimmed[name] = {"_truncated": True, "n": len(vals)}
                        continue
                    if len(vals) + n > max_values:
                        keys = list(vals.keys())[: max(0, max_values - n)]
                        trimmed[name] = {k: vals[k] for k in keys}
                        trimmed[name]["_truncated"] = True
                        trimmed[name]["_n"] = len(vals)
                        n = max_values
                    else:
                        trimmed[name] = vals
                        n += len(vals)
                sc[bucket] = trimmed
        return data
    for sc in data.get("scenarios") or []:
        sc["values"] = {name: len(vals) for name, vals in (sc.get("values") or {}).items()}
        sc["expressions"] = {name: len(vals) for name, vals in (sc.get("expressions") or {}).items()}
    return data


def _analysis_payload(analysis: dict) -> dict[str, Any]:
    skip = {"rp_result", "ev_first_stage"}
    out = {k: v for k, v in analysis.items() if k not in skip}
    first = analysis.get("ev_first_stage") or {}
    out["ev_first_stage_names"] = list(first)
    return out


@dataclass
class StudioSession:
    """One open model and, after a solve, the last result."""

    workspace: Path = field(default_factory=Path.cwd)
    spec: dict | None = None
    source: str = ""
    result: E.SolveResult | None = None
    schedules: dict[str, SCH.Schedule | None] = field(default_factory=dict)
    analysis: dict | None = None
    log_lines: list[str] = field(default_factory=list)

    def _log(self, line: str) -> None:
        self.log_lines.append(line)

    def _require_spec(self) -> dict:
        if self.spec is None:
            raise SessionError("No model is open. Call new_model, load_model or load_example first.")
        return self.spec

    def _require_result(self) -> E.SolveResult:
        if self.result is None:
            raise SessionError("No solve result yet. Call solve_model first.")
        return self.result

    def _set_spec(self, spec: dict, source: str) -> dict[str, Any]:
        self.spec = S.normalize(spec)
        self.source = source
        self.result = None
        self.schedules = {}
        self.analysis = None
        self.log_lines = []
        return summarize_spec(self.spec)

    def _resolve_path(self, path: str) -> Path:
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = (self.workspace / p).resolve()
        else:
            p = p.resolve()
        return p

    def list_examples(self) -> list[dict[str, str]]:
        out = []
        for name in example_names():
            spec = S.load_spec(example_path(name))
            out.append({"name": name, "title": spec.get("name", name),
                        "description": spec.get("description", "")})
        return out

    def new_model(self, name: str = "Untitled model") -> dict[str, Any]:
        return self._set_spec(S.new_spec(name), source="(new)")

    def load_example(self, name: str) -> dict[str, Any]:
        path = example_path(name)
        return self._set_spec(S.load_spec(path), source=str(path))

    def load_model(self, path: str) -> dict[str, Any]:
        p = self._resolve_path(path)
        if not p.is_file():
            raise SessionError(f"Model file not found: {p}")
        try:
            spec = S.load_spec(p)
        except json.JSONDecodeError as exc:
            raise SessionError(f"The file is not valid JSON: {exc}") from exc
        except OSError as exc:
            raise SessionError(f"Could not read {p}: {exc}") from exc
        return self._set_spec(spec, source=str(p))

    def load_spec_json(self, text: str, source: str = "(json)") -> dict[str, Any]:
        return self._set_spec(_json_load(text), source=source)

    def save_model(self, path: str) -> str:
        spec = self._require_spec()
        p = self._resolve_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        S.save_spec(spec, p)
        self.source = str(p)
        return str(p)

    def get_model(self, *, full: bool = False) -> dict[str, Any]:
        spec = self._require_spec()
        payload: dict[str, Any] = {"source": self.source, "summary": summarize_spec(spec)}
        if full:
            payload["spec"] = json.loads(S.dumps(spec))
        return payload

    def validate_model(self) -> dict[str, Any]:
        spec = self._require_spec()
        rep = S.validate(spec)
        return {
            "ok": rep.ok,
            "n_errors": len(rep.errors),
            "n_issues": len(rep.issues),
            "issues": [_issue_dict(i) for i in rep.issues],
        }

    def upsert_component(self, kind: str, item: dict[str, Any]) -> dict[str, Any]:
        spec = self._require_spec()
        if kind not in S.COMPONENT_KINDS:
            raise SessionError(f"Unknown component kind '{kind}'. Use one of: {', '.join(S.COMPONENT_KINDS)}.")
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            raise SessionError("The item must be an object with a non-empty 'name'.")
        name = str(item["name"]).strip()
        items = spec[kind]
        replaced = False
        full = S.new_item(kind, name)
        for i, existing in enumerate(items):
            if existing.get("name") == name:
                full = dict(existing)
                full.update(item)
                full["name"] = name
                items[i] = full
                replaced = True
                break
        if not replaced:
            full.update(item)
            full["name"] = name
            items.append(full)
        self.result = None
        return {"kind": kind, "name": name, "action": "replaced" if replaced else "added",
                "item": full, "summary": summarize_spec(spec)}

    def remove_component(self, kind: str, name: str) -> dict[str, Any]:
        spec = self._require_spec()
        if kind not in S.COMPONENT_KINDS:
            raise SessionError(f"Unknown component kind '{kind}'. Use one of: {', '.join(S.COMPONENT_KINDS)}.")
        before = len(spec[kind])
        spec[kind] = [x for x in spec[kind] if x.get("name") != name]
        if len(spec[kind]) == before:
            raise SessionError(f"No {S.KIND_LABEL[kind]} named '{name}'.")
        self.result = None
        return {"kind": kind, "name": name, "summary": summarize_spec(spec)}

    def patch_model(self, patch: dict[str, Any]) -> dict[str, Any]:
        spec = self._require_spec()
        if not isinstance(patch, dict):
            raise SessionError("patch must be a JSON object.")
        forbidden = set(S.COMPONENT_KINDS)
        for key, value in patch.items():
            if key in forbidden:
                raise SessionError(f"Use upsert_component / remove_component to change '{key}'.")
            if key in ("solver", "schedule", "stochastic") and isinstance(value, dict):
                spec.setdefault(key, {})
                if key == "stochastic" and "risk" in value and isinstance(value["risk"], dict):
                    spec[key].setdefault("risk", {})
                    spec[key]["risk"].update(value["risk"])
                    rest = {k: v for k, v in value.items() if k != "risk"}
                    spec[key].update(rest)
                else:
                    spec[key].update(value)
            else:
                spec[key] = value
        self.spec = S.normalize(spec)
        self.result = None
        return summarize_spec(self.spec)

    def list_solvers(self) -> dict[str, Any]:
        try:
            found = E.detect_solvers()
        except E.EngineError as exc:
            raise SessionError(str(exc)) from exc
        return {
            "solvers": [{"name": name, "available": ok} for name, ok in found.items()],
            "suggestions": E.CLASS_SOLVERS,
        }

    def _solver_options(self, spec: dict, solver: str | None, time_limit: float | None,
                        mip_gap: float | None, tee: bool) -> E.SolverOptions:
        if solver:
            spec["solver"]["name"] = solver
        if time_limit is not None:
            spec["solver"]["time_limit"] = time_limit
        if mip_gap is not None:
            spec["solver"]["mip_gap"] = mip_gap
        spec["solver"]["tee"] = tee
        return E.SolverOptions.from_spec(spec["solver"])

    def _compute_schedules(self, spec: dict, result: E.SolveResult) -> dict[str, SCH.Schedule | None]:
        schedules: dict[str, SCH.Schedule | None] = {}
        if not result.ok:
            return schedules
        for sc in result.scenarios:
            try:
                schedules[sc.name] = SCH.compute_schedule(spec, result.built, sc.name)
            except SCH.ScheduleError as exc:
                self._log(f"WARNING: {exc}")
                schedules[sc.name] = None
        return schedules

    def solve_model(self, solver: str | None = None, time_limit: float | None = None,
                    mip_gap: float | None = None, include_values: bool = False,
                    variable: str | None = None) -> dict[str, Any]:
        spec = self._require_spec()
        self.log_lines = []
        opts = self._solver_options(spec, solver, time_limit, mip_gap, tee=False)
        try:
            result = E.solve(spec, opts, self._log)
        except E.EngineError as exc:
            raise SessionError(str(exc)) from exc
        self.result = result
        self.schedules = self._compute_schedules(spec, result)
        self.analysis = None
        payload = compact_result(result, include_values=include_values, variable=variable)
        payload["log"] = "\n".join(self.log_lines)
        payload["n_schedule_tasks"] = {
            name: 0 if sched is None else len(sched.tasks) for name, sched in self.schedules.items()
        }
        return payload

    def analyze_stochastic(self, solver: str | None = None,
                           time_limit: float | None = None) -> dict[str, Any]:
        spec = self._require_spec()
        self.log_lines = []
        opts = self._solver_options(spec, solver, time_limit, None, tee=False)
        try:
            analysis = E.stochastic_analysis(spec, opts, self._log)
        except E.EngineError as exc:
            raise SessionError(str(exc)) from exc
        result = analysis["rp_result"]
        if spec["stochastic"]["risk"].get("measure") == "cvar":
            try:
                result = E.solve(spec, opts, self._log)
            except E.EngineError as exc:
                raise SessionError(str(exc)) from exc
        self.result = result
        self.analysis = analysis
        self.schedules = self._compute_schedules(spec, result)
        payload = compact_result(result)
        payload["analysis"] = _analysis_payload(analysis)
        payload["log"] = "\n".join(self.log_lines)
        return payload

    def get_solution(self, variable: str | None = None, include_values: bool = True) -> dict[str, Any]:
        result = self._require_result()
        payload = compact_result(result, include_values=include_values, variable=variable)
        if self.analysis:
            payload["analysis"] = _analysis_payload(self.analysis)
        return payload

    def get_schedule(self, scenario: str | None = None) -> dict[str, Any]:
        self._require_result()
        if not self.schedules or all(sched is None for sched in self.schedules.values()):
            raise SessionError("This model has no schedule view, or the last solve did not build one.")
        if scenario is None:
            return {name: SCH.schedule_rows(sched) if sched is not None else []
                    for name, sched in self.schedules.items()}
        if scenario not in self.schedules:
            known = ", ".join(self.schedules) or "(none)"
            raise SessionError(f"Unknown scenario '{scenario}'. Available: {known}.")
        sched = self.schedules[scenario]
        return {scenario: SCH.schedule_rows(sched) if sched is not None else []}

    def build_preview(self) -> dict[str, Any]:
        spec = self._require_spec()
        try:
            stats, listing = E.build_summary(spec)
        except E.EngineError as exc:
            raise SessionError(str(exc)) from exc
        return {"stats": stats, "listing": listing,
                "suggested_solvers": E.CLASS_SOLVERS.get(stats.get("class", ""), [])}

    def write_report(self, path: str, fmt: str = "html") -> str:
        spec = self._require_spec()
        result = self._require_result()
        html_text, md_text = R.make_report(spec, result, self.schedules, self.analysis, self.source)
        p = self._resolve_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        kind = fmt.lower().lstrip(".")
        if kind in ("md", "markdown") or p.suffix.lower() in (".md", ".markdown"):
            p.write_text(md_text, encoding="utf-8")
        elif kind == "json" or p.suffix.lower() == ".json":
            p.write_text(R.result_json(result, self.schedules), encoding="utf-8")
        elif kind == "csv" or p.suffix.lower() == ".csv":
            p.write_text(R.schedule_csv(self.schedules), encoding="utf-8")
        else:
            p.write_text(html_text, encoding="utf-8")
        return str(p)

    def export_script(self, path: str) -> str:
        spec = self._require_spec()
        p = self._resolve_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(codegen.generate(spec, p.name), encoding="utf-8")
        return str(p)

    def write_model_file(self, path: str) -> str:
        spec = self._require_spec()
        p = self._resolve_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            E.write_model_file(spec, str(p))
        except E.EngineError as exc:
            raise SessionError(str(exc)) from exc
        except OSError as exc:
            raise SessionError(f"Could not write {p}: {exc}") from exc
        return str(p)
