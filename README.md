# Pyomo Studio

A Windows 11 (Fluent 2) desktop workbench for Pyomo optimization models. You build sets, parameters, variables, constraints and objectives in forms, solve LP / MILP / NLP / MINLP models, add two-stage stochastic programming with a mean-CVaR risk measure, and get detailed plans with an ISA-101 schedule graphic.

The worked example is the Berth Allocation Problem in three forms: discrete berths, a continuous quay, and uncertain arrivals. A second example links berths, an on-shore tank farm and crude distillation units as switchable layers.

## Install and run

```
python -m pip install -r requirements.txt
python -m pyomo_studio
```

On Windows you can also double-click `run_studio.bat`. You need Python 3.10 or later. HiGHS (`highspy`) is installed as the default LP/MILP solver; see the guide for CBC, GLPK, Ipopt, SCIP, Gurobi and CPLEX.

## Features

- **Model forms** for sets (list, range, Python expression), parameters (spreadsheet grid with Excel paste and CSV import, defaults, formulas), variables (domains, expression bounds, start values), named expressions, constraints (index, condition, relation), and multiple objectives (one optimized, the rest reported as KPIs).
- **Expression language**: plain Pyomo/Python syntax, for example `sum(x[v, b] for b in B) == 1`, with `which()`, `value()`, `inequality()` and the Pyomo nonlinear functions.
- **Solvers**: HiGHS, CBC, GLPK, Gurobi, CPLEX, Xpress, SCIP, Ipopt, Bonmin and Couenne, with a common time limit and MIP gap, free-form options, duals, and a live log. Solves run off the interface thread.
- **Layers**: sub-models that you switch on and off, connected through ports on a shared time grid. Built-in layers: berth allocation, tank farm (receipt, storage, send-out) and crude distillation units (charge, blend, start-ups). When a partner layer is off, a layer uses its fallback data, so each layer also solves alone. Custom layers group form-built components, and new layer types are Python subclasses of `Layer`.
- **Stochastic programming**: scenarios as parameter changes (set, add or scale, for one index or all), first- and second-stage variables, the extensive form with non-anticipativity, mean-CVaR, and an analysis that reports RP, WS, EV, EEV, EVPI and VSS.
- **Schedule view**: map any solution to tasks as a Gantt chart (resource rows) or a space-time chart (for example quay position). The graphic follows ISA-101: a gray background, gray bars, and color only for abnormal states (red priority-1 for late or overlap, amber priority-2 for long waits), each repeated as a symbol and text.
- **Tank schematic**: an ISA-101 process graphic of the tank farm for each period (receipt, tank levels and modes, send-out, crude unit blend), inventory trends with heel and capacity, and high-level, heel, reject and shortage indicators. It is also in the HTML plan and in a CSV.
- **Random models**: a seeded generator for crude terminal and refinery models (tiny to large presets, congestion, tank tightness, arrival-delay scenarios), in **Examples > Generate random model** and `python -m pyomo_studio generate`.
- **Plans**: an HTML report (Fluent styling with the embedded schedule graphic), Markdown, schedule CSV, values CSV and results JSON.
- **Export**: a standalone, readable Pyomo script; LP, MPS and NL model files.
- **Advanced hook**: Python code that runs on each model block, for Pyomo features the forms do not cover (GDP, piecewise).
- **Command line**: `python -m pyomo_studio solve model.json --analyze --report plan.html`, `python -m pyomo_studio generate model.json --preset small --seed 7`.
- **MCP server**: `python -m pyomo_studio mcp` (stdio). An agent can load examples, edit the spec, solve, inspect the schedule and export a Pyomo script. Install with `pip install "pyomo-studio[mcp]"` (needs the `mcp` extra).

## MCP (agent control)

Install the extra, then start the server from this repo:

```
python -m pip install "mcp>=1.2"
python -m pyomo_studio mcp
```

Grok reads `.grok/config.toml` in this project. Other hosts can copy `.mcp.json`. Streamable HTTP: `python -m pyomo_studio mcp --http --port 8765`.

Tools wrap the same engine as the CLI: `list_examples`, `load_example`, `new_model`, `upsert_component`, `validate_model`, `solve_model`, `analyze_stochastic`, `get_solution`, `get_schedule`, `write_report`, `export_script`.

## Interface

- PySide6 (Qt 6) with Fluent 2 tokens for light and dark themes. The program can follow the Windows setting and changes live.
- Mica backdrop through the DWM system backdrop on Windows 11 22H2 and later, with the solid fallback color elsewhere.
- 8 px window and flyout corners and 4 px control corners.
- Segoe UI Variable type ramp and Segoe Fluent Icons glyphs.
- A left NavigationView rail that collapses to a 48 px compact rail.

## Files

```
pyomo_studio/
  spec.py       model file format, index parsing, data, scenarios, validation (no Pyomo needed)
  engine.py     Pyomo build, solve, extensive form, CVaR, EVPI/VSS analysis
  schedule.py   schedule view, ISA-101 layout, SVG
  inventory.py  tank inventory data, schematic and trend layout
  generate.py   random crude terminal and refinery models
  report.py     HTML / Markdown / CSV / JSON plans
  codegen.py    standalone Pyomo script export
  layers/       switchable layers: framework, berth, tank farm, crude units, custom
  session.py    in-memory session used by the MCP server
  mcp_server.py MCP tools, resources and prompts
  gui/          Fluent 2 interface (theme, widgets, pages, window)
  examples/     bap_discrete, bap_continuous, bap_stochastic, production_lp, refinery_terminal
  docs/USER_GUIDE.md   user guide in ASD-STE100 Simplified Technical English
```

## Safety

Expressions and the hook are Python code that runs on your computer. Open model files only from sources that you trust.
