"""Command line entry point.

    python -m pyomo_studio                          open the desktop interface
    python -m pyomo_studio model.json               open a model in the interface
    python -m pyomo_studio solve model.json --report plan.html [--analyze]
    python -m pyomo_studio export model.json model_script.py
    python -m pyomo_studio validate model.json
    python -m pyomo_studio solvers
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import APP_NAME, __version__
from . import spec as S


def _log(line: str) -> None:
    print(line, flush=True)


def cmd_solve(args) -> int:
    from . import engine, report, schedule
    spec = S.load_spec(args.model)
    if args.solver:
        spec["solver"]["name"] = args.solver
    if args.time_limit is not None:
        spec["solver"]["time_limit"] = args.time_limit
    spec["solver"]["tee"] = not args.quiet
    opts = engine.SolverOptions.from_spec(spec["solver"])
    analysis = None
    try:
        if args.analyze:
            analysis = engine.stochastic_analysis(spec, opts, _log)
            result = engine.solve(spec, opts, _log) if spec["stochastic"]["risk"].get("measure") == "cvar" \
                else analysis["rp_result"]
        else:
            result = engine.solve(spec, opts, _log)
    except engine.EngineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    schedules = {}
    if result.ok:
        for sc in result.scenarios:
            try:
                schedules[sc.name] = schedule.compute_schedule(spec, result.built, sc.name)
            except schedule.ScheduleError as exc:
                print(f"WARNING: {exc}", file=sys.stderr)
    html_text, md_text = report.make_report(spec, result, schedules, analysis, Path(args.model).name)
    if args.report:
        out = Path(args.report)
        if out.suffix.lower() in (".md", ".markdown"):
            out.write_text(md_text, encoding="utf-8")
        else:
            out.write_text(html_text, encoding="utf-8")
        print(f"Report written to {out}")
    if args.csv:
        Path(args.csv).write_text(report.schedule_csv(schedules), encoding="utf-8")
        print(f"Schedule CSV written to {args.csv}")
    if args.json:
        Path(args.json).write_text(report.result_json(result, schedules), encoding="utf-8")
        print(f"Results JSON written to {args.json}")
    if not args.report:
        print(md_text)
    return 0 if result.ok else 1


def cmd_export(args) -> int:
    from . import codegen
    spec = S.load_spec(args.model)
    Path(args.output).write_text(codegen.generate(spec, Path(args.output).name), encoding="utf-8")
    print(f"Pyomo script written to {args.output}")
    return 0


def cmd_validate(args) -> int:
    spec = S.load_spec(args.model)
    rep = S.validate(spec)
    for issue in rep.issues:
        print(issue)
    print("No errors." if rep.ok else f"{len(rep.errors)} error(s).")
    return 0 if rep.ok else 1


def cmd_solvers(_args) -> int:
    from . import engine
    try:
        found = engine.detect_solvers()
    except engine.EngineError as exc:
        print(exc)
        return 2
    for name, ok in found.items():
        print(f"{'available ' if ok else 'not found '} {name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    commands = {"solve", "export", "validate", "solvers", "gui"}
    if not argv or (argv[0] not in commands and not argv[0].startswith("-")):
        from .gui.app import run
        return run(argv[0] if argv else None)
    p = argparse.ArgumentParser(prog="pyomo_studio", description=f"{APP_NAME} {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gui", help="open the desktop interface")
    g.add_argument("model", nargs="?")
    s = sub.add_parser("solve", help="solve a model file and write a plan")
    s.add_argument("model")
    s.add_argument("--report", help="plan file (.html or .md)")
    s.add_argument("--csv", help="schedule CSV file")
    s.add_argument("--json", help="results JSON file")
    s.add_argument("--solver", help="solver name, for example appsi_highs or cbc")
    s.add_argument("--time-limit", type=float)
    s.add_argument("--analyze", action="store_true", help="stochastic analysis: EVPI and VSS")
    s.add_argument("--quiet", action="store_true", help="no solver log")
    e = sub.add_parser("export", help="write a standalone Pyomo script")
    e.add_argument("model")
    e.add_argument("output")
    v = sub.add_parser("validate", help="find errors in a model file")
    v.add_argument("model")
    sub.add_parser("solvers", help="show the installed solvers")
    args = p.parse_args(argv)
    if args.cmd == "gui":
        from .gui.app import run
        return run(args.model)
    return {"solve": cmd_solve, "export": cmd_export, "validate": cmd_validate,
            "solvers": cmd_solvers}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
