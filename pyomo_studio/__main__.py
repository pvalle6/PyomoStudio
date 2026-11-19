"""Command line entry point.

    python -m pyomo_studio                          open the desktop interface
    python -m pyomo_studio model.json               open a model in the interface
    python -m pyomo_studio solve model.json --report plan.html [--analyze] [--tanks-csv tanks.csv]
    python -m pyomo_studio export model.json model_script.py
    python -m pyomo_studio generate out.json [--preset small] [--seed 7] [--check]
    python -m pyomo_studio validate model.json
    python -m pyomo_studio solvers
    python -m pyomo_studio mcp [--http] [--host HOST] [--port PORT]
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
    spec = result.spec or spec
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
    if args.tanks_csv:
        from . import inventory as INV
        invs = INV.compute_all(spec, result)
        if invs:
            text = "".join(INV.inventory_csv(inv).split("\n", 1)[1] if i else INV.inventory_csv(inv)
                           for i, inv in enumerate(invs))
            Path(args.tanks_csv).write_text(text, encoding="utf-8")
            print(f"Tank inventory CSV written to {args.tanks_csv}")
        else:
            print("WARNING: no tank farm layer, no tank CSV written.", file=sys.stderr)
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


def cmd_generate(args) -> int:
    from . import generate as G
    opts = G.GenOptions(seed=args.seed, preset=args.preset, congestion=args.congestion, tightness=args.tightness,
                        scenarios=args.scenarios)
    for key in ("vessels", "berths", "grades", "tanks_per_grade", "cdus", "periods", "period_h", "tank_modes"):
        if getattr(args, key) is not None:
            setattr(opts, key, getattr(args, key))
    try:
        if args.check:
            from . import engine
            solver = engine.SolverOptions(name=args.solver or "appsi_highs", time_limit=args.time_limit or 120,
                                          mip_gap=0.005, tee=False)
            spec, res, seed = G.generate_checked(opts, solver, attempts=args.attempts, log=_log)
            if seed != args.seed:
                print(f"Seed {args.seed} gave no solution; seed {seed} is used.")
        else:
            spec = G.generate(opts)
    except (ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    S.save_spec(spec, args.output)
    print(f"Model written to {args.output}: {spec['description'].split(' Options:')[0]}")
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


def cmd_mcp(args) -> int:
    from .mcp_server import reset_session, run
    reset_session()
    if args.http:
        run(transport="streamable-http", host=args.host, port=args.port)
    else:
        run(transport="stdio")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    commands = {"solve", "export", "generate", "validate", "solvers", "gui", "mcp"}
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
    s.add_argument("--tanks-csv", help="tank inventory CSV file (models with a tank farm layer)")
    s.add_argument("--solver", help="solver name, for example appsi_highs or cbc")
    s.add_argument("--time-limit", type=float)
    s.add_argument("--analyze", action="store_true", help="stochastic analysis: EVPI and VSS")
    s.add_argument("--quiet", action="store_true", help="no solver log")
    e = sub.add_parser("export", help="write a standalone Pyomo script")
    e.add_argument("model")
    e.add_argument("output")
    gp = sub.add_parser("generate", help="write a random crude terminal and refinery model")
    gp.add_argument("output")
    gp.add_argument("--preset", default="small", choices=["tiny", "small", "medium", "large"])
    gp.add_argument("--seed", type=int, default=1)
    for key, typ in (("vessels", int), ("berths", int), ("grades", int), ("tanks-per-grade", int), ("cdus", int),
                     ("periods", int), ("period-h", float)):
        gp.add_argument(f"--{key}", type=typ, help="replaces the preset value")
    gp.add_argument("--tank-modes", dest="tank_modes", action=argparse.BooleanOptionalAction, default=None,
                    help="tanks cannot receive and send in one period (more binaries; preset decides by default)")
    gp.add_argument("--congestion", type=float, default=0.5, help="0 to 1: vessel arrivals closer together")
    gp.add_argument("--tightness", type=float, default=0.5, help="0 to 1: less tank space")
    gp.add_argument("--scenarios", type=int, default=0, help="number of arrival-delay scenarios (0 = none)")
    gp.add_argument("--check", action="store_true", help="solve it; try the next seeds if it has no solution")
    gp.add_argument("--attempts", type=int, default=5)
    gp.add_argument("--solver")
    gp.add_argument("--time-limit", type=float)
    v = sub.add_parser("validate", help="find errors in a model file")
    v.add_argument("model")
    sub.add_parser("solvers", help="show the installed solvers")
    m = sub.add_parser("mcp", help="run the MCP server (stdio by default)")
    m.add_argument("--http", action="store_true", help="Streamable HTTP instead of stdio")
    m.add_argument("--host", default="127.0.0.1")
    m.add_argument("--port", type=int, default=8765)
    args = p.parse_args(argv)
    if args.cmd == "gui":
        from .gui.app import run
        return run(args.model)
    return {"solve": cmd_solve, "export": cmd_export, "generate": cmd_generate, "validate": cmd_validate,
            "solvers": cmd_solvers, "mcp": cmd_mcp}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
