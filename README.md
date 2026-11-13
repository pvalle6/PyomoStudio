# Pyomo Studio

A Windows 11 (Fluent 2) desktop workbench for Pyomo optimization models. You build sets, parameters, variables, constraints and objectives in forms, solve LP / MILP / NLP / MINLP models, add two-stage stochastic programming with a mean-CVaR risk measure, and get detailed plans with an ISA-101 schedule graphic.

The worked example is the Berth Allocation Problem in three forms: discrete berths, a continuous quay, and uncertain arrivals.

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
- **Stochastic programming**: scenarios as parameter changes (set, add or scale, for one index or all), first- and second-stage variables, the extensive form with non-anticipativity, mean-CVaR, and an analysis that reports RP, WS, EV, EEV, EVPI and VSS.
- **Schedule view**: map any solution to tasks as a Gantt chart (resource rows) or a space-time chart (for example quay position). The graphic follows ISA-101: a gray background, gray bars, and color only for abnormal states (red priority-1 for late or overlap, amber priority-2 for long waits), each repeated as a symbol and text.
- **Plans**: an HTML report (Fluent styling with the embedded schedule graphic), Markdown, schedule CSV, values CSV and results JSON.
- **Export**: a standalone, readable Pyomo script; LP, MPS and NL model files.
- **Advanced hook**: Python code that runs on each model block, for Pyomo features the forms do not cover (GDP, piecewise).
- **Command line**: `python -m pyomo_studio solve model.json --analyze --report plan.html`.

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
  report.py     HTML / Markdown / CSV / JSON plans
  codegen.py    standalone Pyomo script export
  gui/          Fluent 2 interface (theme, widgets, pages, window)
  examples/     bap_discrete, bap_continuous, bap_stochastic, production_lp
  docs/USER_GUIDE.md   user guide in ASD-STE100 Simplified Technical English
```

## Safety

Expressions and the hook are Python code that runs on your computer. Open model files only from sources that you trust.
