# Pyomo Studio — User Guide

Version 1.0. This guide uses ASD-STE100 Simplified Technical English (STE).

---

## 1 About this guide

### 1.1 Scope

This guide tells you how to install and use Pyomo Studio. Pyomo Studio is a desktop program. You use it to make optimization models, solve them and read the plans that they give.

The program uses Pyomo. Pyomo is a Python library for optimization models. You do not have to write Python programs. You write short expressions in forms. The program makes the Pyomo model from the forms.

You can make these types of model:

| Type | Meaning | Example |
|---|---|---|
| LP | Linear program. All variables are continuous. | Production plan |
| MILP | Mixed-integer linear program. Some variables are integer or binary. | Berth allocation |
| QP, MIQP | Quadratic objective or constraints. | Portfolio |
| NLP, MINLP | Nonlinear functions, for example `exp` or `log`. | Process models |
| Two-stage stochastic program | A model with scenarios for uncertain data. | Berth allocation with delays |

### 1.2 How this guide is written

This guide follows the STE rules:

- A procedure has numbered steps. Each step has one instruction.
- A sentence in a procedure has 20 words or fewer.
- A sentence in a description has 25 words or fewer.
- The guide uses the active voice.

These text styles show parts of the program:

- **Bold** text is the name of a control, a page or a field. For example: click **Solve**.
- `Code` text is text that you write, or text that the program shows.
- *Italic* text is a term that the glossary (section 17) explains.

### 1.3 Warnings and cautions

A WARNING tells you about a risk of injury. This guide has no warnings.

A CAUTION tells you about a risk of damage to data or equipment.

> **CAUTION:** Expressions in a model file are Python code. The program runs this code on your computer. Do not open model files from people or places that you do not trust.

> **CAUTION:** The program does not save your work automatically. Save the model before you close the program.

---

## 2 Install the program

### 2.1 What you must have

- Windows 11. The program also operates on Windows 10, macOS and Linux, but without Mica.
- Python 3.10 or a later version.
- A solver. HiGHS is free and solves LP and MILP models.

### 2.2 Install

1. Open a command prompt in the program folder.
2. Write `python -m pip install -r requirements.txt`.
3. Push Enter.
4. Wait until the installation stops.

The file `requirements.txt` installs Pyomo, PySide6 (the Qt interface) and HiGHS (`highspy`).

### 2.3 Install more solvers (optional)

| Solver | For | How to get it |
|---|---|---|
| HiGHS (`appsi_highs`) | LP, MILP, convex QP | `pip install highspy` |
| CBC (`cbc`) | LP, MILP | Download from the COIN-OR project. Put `cbc.exe` on the PATH. |
| GLPK (`glpk`) | LP, MILP | Download GLPK. Put `glpsol.exe` on the PATH. |
| Ipopt (`ipopt`) | NLP | `pip install idaes-pse`, then `idaes get-extensions`. Or download Ipopt. |
| SCIP (`scip`) | MILP, MINLP | Download SCIP. Put `scip.exe` on the PATH. |
| Gurobi, CPLEX, Xpress | All types | Commercial. Install with the license of the vendor. |

To see the solvers that the program can find, click **Find installed solvers** on the **Solve** page.

### 2.4 Start the program

Do one of these steps:

- Double-click `run_studio.bat`.
- Write `python -m pyomo_studio` in a command prompt.
- Write `python -m pyomo_studio model.json` to open a model at the start.

---

## 3 The main window

### 3.1 Parts of the window

The window follows the Windows 11 Fluent design.

| Part | Position | Function |
|---|---|---|
| Navigation rail | Left | Opens the pages. Click the menu button at the top to make the rail narrow or wide. |
| Command bar | Top | **New**, **Open**, **Save**, **Examples**, **Validate**, **Analyze** and **Solve**. |
| Page | Center | The active page. |
| Progress line | Top of the page | Moves while the program solves. |
| Status line | Bottom | Shows the last message. |

The navigation rail has these groups:

- **Home** — model name, description, steps and examples.
- **Model** — **Sets**, **Parameters**, **Variables**, **Expressions**, **Constraints**, **Objectives**, **Uncertainty**.
- **Run** — **Solve**.
- **Output** — **Results**, **Schedule**, **Plan**.
- At the bottom: **User guide** and **Settings**.

### 3.2 Keyboard shortcuts

| Keys | Action |
|---|---|
| Ctrl+N | New model |
| Ctrl+O | Open a model |
| Ctrl+S | Save |
| Ctrl+Shift+S | Save as |
| F5 | Solve |
| F6 | Stochastic analysis |
| F7 | Validate |
| Ctrl+E | Export a Pyomo script |
| Ctrl+V | Paste values into the parameter grid |

### 3.3 Change the theme

1. Click **Settings**.
2. Click **Light**, **Dark** or **Use the Windows setting**.

The program changes the theme immediately.

Mica is the Windows 11 window material. It shows the desktop color through the window. Mica needs Windows 11 version 22H2 or a later version. To set Mica on or off:

1. Click **Settings**.
2. Click the **Mica window material** switch.
3. Close the program and start it again.

---

## 4 Parts of a model

A model has these parts. Make them in this sequence, because each part can use the parts above it.

| Part | What it is | Example |
|---|---|---|
| Set | A list of index values | `V` = vessels, `B` = berths |
| Parameter | Data | `a[v]` = arrival time of vessel `v` |
| Variable | A decision that the solver finds | `x[v, b]` = 1 if vessel `v` uses berth `b` |
| Expression | A named formula | `dep[v] = t[v] + hand[v]` |
| Constraint | A rule that a solution must obey | `sum(x[v, b] for b in B) == 1` |
| Objective | The measure to minimize or maximize | Total weighted time in port |

Each page for a model part has the same layout:

- The toolbar has **Add**, **Duplicate**, **Delete**, **Move up** and **Move down**.
- The list on the left shows the items.
- The form on the right shows the selected item.

The program saves each change in the model immediately. A red text below a field shows an error in that field.

### 4.1 Names

A name starts with a letter or `_`. A name has only letters, digits and `_`. Each name in a model must be different. Some names are for the program only, for example `sum`, `value`, `m` and `which`. The program tells you when a name is not permitted.

> **Note:** When you change a name, the program does not change the expressions that use the old name. Change these expressions yourself. Then click **Validate**.

---

## 5 Make a model

### 5.1 Sets

A set has one of three types:

| Type | How to make it |
|---|---|
| List of elements | Write one element on each line. Write `a, b` on one line for a tuple element (a pair). |
| Integer range | Set **Start**, **Stop** and **Step**. The range includes the stop value. |
| Python expression | Write an expression of the sets above it. For example: `[(u, v) for u in V for v in V if u != v]`. |

To make many elements quickly:

1. Set **Type** to **List of elements**.
2. In **Quick fill**, write a prefix, for example `V`.
3. Set **from**, **to** and **digits**.
4. Click **Fill**.

The text below the form shows the number of elements and the first elements.

### 5.2 Parameters

A parameter with no index has one value. A parameter with an index has one value for each index value.

To make an indexed parameter:

1. Click **Add**.
2. Write the name, for example `p`.
3. In **Index**, write `v in V, b in B`.
4. Write the values in the grid.

The grid has one of three shapes:

- One index set: one column of values.
- Two index sets: a matrix. The rows are the first set. The columns are the second set.
- Other indexes: one row for each index value.

These rules apply to the grid:

- An empty cell uses the **Default value**.
- If the **Default value** field is empty, an empty cell is an error when the model uses that value.
- A cell that is not a number becomes red.

To paste data from Excel:

1. In Excel, copy a block of cells.
2. In the grid, click the cell for the top-left value.
3. Push Ctrl+V.

To import a CSV file, click **Import CSV**. The file can have the shape of the grid (a header row and a header column). The file can also have one row for each value: the index values, then the value.

A **Formula** calculates each value from the index names and from other parameters. A formula replaces the grid. For example: `1 if len_[v] <= depth[b] else 0`.

### 5.3 Variables

| Field | Meaning |
|---|---|
| Index | The index of the variable. Empty for one variable. |
| Domain | `Reals`, `NonNegativeReals`, `NonPositiveReals`, `Binary`, `Integers`, `NonNegativeIntegers`, `NonPositiveIntegers` or `UnitInterval` (0 to 1). |
| Lower bound, Upper bound | A number or an expression of parameters and index names, for example `a[v]`. Optional. |
| Start value | A value that the solver can use as a first solution. Optional. |
| Stage | For stochastic models only. See section 11. |

Use a bound, not a constraint, when the limit applies to one variable. Bounds make the model smaller.

### 5.4 Expressions

A named expression is a formula that you use in more than one place. For example:

- Name `hand`, index `v in V`, expression `sum(p[v, b] * x[v, b] for b in B)`.
- Name `dep`, index `v in V`, expression `t[v] + hand[v]`.

The program shows the value of each expression on the **Results** page.

### 5.5 Constraints

| Field | Meaning |
|---|---|
| For all | The index. The program makes one constraint for each index value. |
| Only where | A condition. The program skips index values where the condition is false. |
| Expression | One relation with `==`, `<=` or `>=`. |
| Active | An inactive constraint stays in the file, but it is not in the model. |

The condition can use index names and parameters. It cannot use variables. For example: `u < v`, or `ok[v, b] == 1`.

You can also write `inequality(lower, expression, upper)` for a range constraint.

### 5.6 Objectives

You can make more than one objective. Only one objective is active. The solver optimizes the active objective. The program calculates the value of the other objectives and shows them as measures (KPIs).

To change the active objective:

1. Select the objective in the list.
2. Click the **Optimize this objective** switch.

### 5.7 The expression language

Expressions use Python syntax with Pyomo components. Use the names of your sets, parameters, variables and expressions directly.

| Item | Example |
|---|---|
| Index a component | `x[v, b]`, `a[v]`, `y[u, v]` |
| Sum | `sum(w[v] * T[v] for v in V)` |
| Sum with a condition | `sum(x[v, b] for b in B if ok[v, b] == 1)` |
| Double sum | `sum(c[i, j] * f[i, j] for i in I for j in J)` |
| Pair in a set of pairs | `for (u, v) in PAIRS` |
| Relation | `==`, `<=`, `>=` |
| Range | `inequality(0, x[i] - y[i], 10)` |
| Condition in data | `max(0, a[u] + Wmax - a[v])` — data only |
| Ordered sets | `T.first()`, `T.last()`, `T.prev(t)`, `T.next(t)`, `T.ord(t)` |

These functions are available:

| Function | Use |
|---|---|
| `sum`, `quicksum` | Sums. `quicksum` is faster for large sums. |
| `exp`, `log`, `log10`, `sqrt`, `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `sinh`, `cosh`, `tanh` | Nonlinear functions of variables (Pyomo functions). |
| `min`, `max`, `abs`, `round`, `len`, `range`, `sorted`, `enumerate`, `zip`, `any`, `all` | Python functions. Use `min` and `max` on data only. |
| `value(e)` | The value of a component after a solve. |
| `num(e)` | The value as a number. |
| `which(x, v)` | The remaining index of the member of `x` that is 1. For example, the berth `b` where `x[v, b] = 1`. |
| `pyo` | The full `pyomo.environ` module. |
| `pi`, `inf`, `math` | Constants and the Python `math` module (for data). |

An expression can use more than one line. Each line must be part of the same expression.

> **Note:** Parameters are data. A parameter is a number in an expression. Thus you can use `max`, `min` and `if ... else` on parameters. You cannot use them on variables. For a maximum of variables, add a variable and two constraints.

---

## 6 Solve the model

### 6.1 Procedure

1. Click **Solve** in the navigation rail.
2. In **Solver**, select a solver. For LP and MILP, use `appsi_highs`.
3. Set the **Time limit**. Set 0 for no limit.
4. Set the **Relative MIP gap**. Use 0 for an optimal solution. Use 0.01 for a solution that is not more than 1 % from the optimum.
5. Click **Solve**, or push F5.

The **Log** shows the solver output. The progress line moves until the solver stops. When the solver stops, the program opens the **Schedule** page or the **Results** page.

### 6.2 Other actions

| Button | Action |
|---|---|
| **Validate** (F7) | Finds errors. It also tests the data. It does not solve. |
| **Build only** | Makes the model and shows its size and class. The log shows the full model. |
| **Stochastic analysis** (F6) | See section 11.4. |
| **Export Pyomo script** (Ctrl+E) | Writes a Python file that makes and solves the model with Pyomo only. |
| **Write LP / MPS / NL file** | Writes the model in a solver file format. |

### 6.3 Solver options

The program sets the time limit and the MIP gap with the option names of each solver. To set other options, write one option on each line in this format: `name = value`. For example, for HiGHS: `presolve = on` or `threads = 4`.

Set **Get duals** to on to get the dual values of an LP. A dual value is the change of the objective when the right side of a constraint increases by 1.

### 6.4 The custom Python hook (advanced)

The hook is Python code. The program runs it after it makes each model block. Use it for Pyomo components that the forms do not have, for example disjunctions (`pyomo.gdp`) or piecewise functions.

In the hook:

- `m` is the model block.
- `pyo` is `pyomo.environ`.
- All components are available by name.

> **CAUTION:** The hook can run any Python code. Use it only for code that you understand.

---

## 7 Read the results

The **Results** page shows:

- A status bar. Green is an optimal solution. Yellow is a solution that is not proved optimal, for example at the time limit. Red is no solution.
- Metric cards: objective, solver status, MIP gap, solve time, problem class and size.
- For a stochastic model: the expected objective, the CVaR, the worst and the best scenario, and a table for each scenario.
- Tables for variables, expressions, constraints and objectives.

To find values:

- Write a name or an index in **Filter**.
- Set **Hide zeros** to on to hide values that are 0.
- Set **Binding only** to on to show only constraints where the slack is 0. Binding constraints limit the solution.
- For a stochastic model, select a scenario in **Scenario**.

To export the values, click **Export values CSV** or **Export results JSON**.

If you change the model after a solve, the page shows the message `Changed model`. Solve again to update the results.

---

## 8 The schedule

### 8.1 What the schedule view does

The schedule view changes the solution into tasks. Each task has a resource, a start and a duration. The program then shows the tasks as a graphic and as tables.

There are two graphic types:

- **Gantt chart** — one row for each resource, for example one row for each berth.
- **Space-time chart** — the horizontal axis is time. The vertical axis is space, for example the position on a quay. Each task is a rectangle.

### 8.2 Set the schedule view

1. Click **Schedule**.
2. Click the **View settings** tab.
3. Set **View type**.
4. Write the fields. Each field is an expression with the index names of the tasks.
5. Click **Apply and draw**.

| Field | Example (berth model) |
|---|---|
| Tasks (index) | `v in V` |
| Only where | (empty) |
| Label | `v` |
| Resource | `which(x, v)` |
| Start | `t[v]` |
| Duration | `hand[v]` |
| Release / arrival | `a[v]` |
| Due | `d[v]` |
| Position, Size, Total space | `pos[v]`, `len_[v]`, `L` (space-time only) |
| Time unit | `h` |
| Time origin | `2026-11-16 06:00` |
| Wait warning limit | `3` |
| Late tolerance | `0.001` |

If you set a time origin and the time unit is `min`, `h` or `d`, the plan shows dates and clock times.

### 8.3 Colors in the schedule graphic (ISA-101)

The graphic follows ISA-101, the standard for high-performance process graphics:

- The background is gray.
- Normal tasks are gray bars.
- Color shows only abnormal states.
- A symbol and a text also show each abnormal state. Thus you do not have to see colors to read the plan.

| State | Color | Symbol | Cause |
|---|---|---|---|
| Normal | Gray | None | The task starts and ends in its limits. |
| Warning (priority 2) | Amber | Triangle with `2` | The wait is longer than the wait warning limit. |
| Alarm (priority 1) | Red | Square with `1` | The task ends after its due time, or two tasks overlap. |

Other marks:

- A dark triangle below a bar is the release time (arrival).
- A dashed line from the triangle to the bar is the wait.
- A short vertical line is the due time.
- A red strip at the bottom of a bar is the late part.

The graphic keeps the ISA-101 gray background in the light theme and in the dark theme.

### 8.4 Use the plan view

- Move the pointer on a bar to see the details of the task.
- Use the zoom slider or the zoom buttons to make the time axis longer.
- The metric cards show the tasks, the plan end, the total wait, the late tasks and the number of alarms and warnings.
- The table below the graphic shows each task in sequence on each resource.
- Click **Export SVG** or **Export PNG** to save the graphic.

---

## 9 The plan

The **Plan** page shows the full plan of the last solve. The plan has these sections:

1. Summary: status, objective, bound, gap, solver, size.
2. Other objectives (measures).
3. Decision under uncertainty (stochastic models only): the first-stage plan, the scenarios, the risk measures and the stochastic analysis.
4. Schedule: measures, the graphic, the exceptions, the plan by resource and the task sequence on each resource.
5. Decision variables that are not 0.
6. Named expressions.
7. Binding constraints and duals.
8. The model formulation.

To save the plan:

| Button | Result |
|---|---|
| **Save HTML report** | An HTML file with the schedule graphic. It shows correctly in a browser and when you print it. |
| **Open in browser** | Opens the HTML report in your default browser. |
| **Save Markdown** | A Markdown file without the graphic. |
| **Save schedule CSV** | One row for each task, for Excel. |

---

## 10 Other model types

### 10.1 Linear programs (LP)

Use continuous domains only. Example: open **Examples > production lp**. The model finds the product mix with the highest profit. The optimal profit is 6,050. Set **Get duals** to on. The duals of `Capacity` show the value of one more hour of each resource.

### 10.2 Nonlinear programs (NLP, MINLP)

Write nonlinear expressions with `exp`, `log`, `sqrt`, powers (`x[i]**2`) or products of variables. Then select a nonlinear solver:

- NLP: `ipopt`.
- MINLP: `scip`, `bonmin` or `couenne`.

A local solver such as Ipopt finds a local optimum. Give good start values in the **Start value** field.

---

## 11 Stochastic programming

### 11.1 The two-stage model

In a two-stage stochastic program, you make some decisions before you know the uncertain data. These are the *first-stage* decisions ("here and now"). After the data is known, you make the *second-stage* decisions ("wait and see"). The second-stage decisions can be different in each scenario.

The program makes the *extensive form*. The extensive form has one copy of the model for each scenario $s$ with probability $p_s$. *Non-anticipativity* constraints make the first-stage variables equal in all scenarios:

$$
x_s = x_{s_1} \qquad \forall s \neq s_1 .
$$

The objective is the expected value of the scenario objectives $f_s$:

$$
\min \; \sum_{s} p_s \, f_s(x_s, y_s).
$$

For a maximization, the program minimizes the negative value and shows the result with the correct sign.

### 11.2 Make a stochastic model

1. Make and solve the deterministic model first. Make sure that it is correct.
2. On the **Variables** page, set **Stage** to `1 - Here and now` for each first-stage variable.
3. Click **Uncertainty**.
4. Set the **Use a stochastic model** switch to on.
5. Click **Add** for each scenario. Write the name and the probability.
6. Make sure that the probabilities add to 1. Click **Equal probabilities** if all scenarios have the same probability.
7. Select a scenario.
8. Click **Add change** for each parameter that is different in this scenario.
9. Click **Solve**.

A change has four fields:

| Field | Meaning |
|---|---|
| Parameter | The parameter to change. |
| Index | The index value, for example `V05` or `V05, B1`. Empty means all index values. |
| Operation | `set` writes the value. `add` adds the value. `scale` multiplies by the value. |
| Value | The number. |

A scenario with no changes uses the base data.

### 11.3 Risk: mean-CVaR

The expected value does not look at the spread of the results. To decrease the cost of bad scenarios, use *CVaR* (conditional value at risk). $\mathrm{CVaR}_\alpha$ is the mean cost of the worst $(1-\alpha)$ part of the scenarios.

The program minimizes this objective:

$$
(1-\lambda)\, \mathbb{E}[f] \;+\; \lambda\, \mathrm{CVaR}_\alpha[f],
\qquad
\mathrm{CVaR}_\alpha[f] = \min_{\eta}\; \eta + \frac{1}{1-\alpha} \sum_s p_s \max\!\left(0,\, f_s - \eta\right).
$$

To use it:

1. On the **Uncertainty** page, set **Measure** to **Expected value + CVaR**.
2. Set **CVaR level alpha**, for example 0.8.
3. Set **CVaR weight** $\lambda$ from 0 to 1. A higher weight gives a more careful plan.

The program shows the CVaR on the **Results** page for each stochastic solve, also when the weight is 0.

### 11.4 Stochastic analysis: EVPI and VSS

Click **Analyze** (F6). The program solves these problems:

| Name | Problem |
|---|---|
| RP | The recourse problem: the extensive form, risk-neutral. |
| WS | Wait and see: each scenario solved alone with perfect information. $\mathrm{WS} = \sum_s p_s f_s^\ast$. |
| EV | The expected-value problem: one scenario with the mean data. |
| EEV | The first-stage plan of EV, used in each real scenario. |

Then it calculates two values (for a minimization):

$$
\mathrm{EVPI} = \mathrm{RP} - \mathrm{WS}, \qquad \mathrm{VSS} = \mathrm{EEV} - \mathrm{RP}.
$$

- EVPI is the highest price that you can pay for a perfect forecast.
- VSS is the gain when you plan with the scenarios, not with the mean data.
- If the EV plan is infeasible in a scenario, EEV and VSS are infinite. Then the mean-data plan cannot operate in that scenario.

The analysis uses the risk-neutral objective, because EVPI and VSS are defined for the expected value.

---

## 12 Example: the Berth Allocation Problem

### 12.1 The problem

Vessels arrive at a container terminal. Each vessel needs a berth for a known handling time. A berth can serve only one vessel at a time. The terminal must find the berth and the start time of each vessel. The objective is a short time in port and few late departures.

The program has three examples. Click **Examples** in the command bar, or open them on the **Home** page.

| File | Model |
|---|---|
| `bap_discrete.json` | 10 vessels, 3 berths. MILP. |
| `bap_continuous.json` | 8 vessels on a 600 m quay. MILP with time and space. |
| `bap_stochastic.json` | The discrete model with 3 scenarios of delays. Two-stage stochastic MILP. |

### 12.2 Discrete berths: the formulation

Sets: vessels $V$, berths $B$, ordered pairs $P = \{(u,v) \in V \times V : u \neq v\}$.

Parameters:

| Symbol | Name in the model | Meaning |
|---|---|---|
| $a_v$ | `a` | Arrival time (h) |
| $d_v$ | `d` | Requested departure (h) |
| $w_v$ | `w` | Priority weight |
| $p_{vb}$ | `p` | Handling time of $v$ at berth $b$ (h) |
| $k_{vb}$ | `ok` | 1 if $v$ can use berth $b$ (draft) |
| $s_b$ | `s` | Opening time of berth $b$ |
| $W$ | `Wmax` | Longest wait allowed (h) |
| $\lambda$ | `lam` | Penalty for late departure |

Variables: $x_{vb} \in \{0,1\}$ (berth), $y_{uv} \in \{0,1\}$ ($u$ before $v$), $t_v \ge 0$ (start), $T_v \ge 0$ (late departure).

Expressions: handling time $h_v = \sum_b p_{vb}\, x_{vb}$ and departure $c_v = t_v + h_v$.

$$
\begin{aligned}
\min\quad & \sum_{v} w_v\,(c_v - a_v) \;+\; \lambda \sum_{v} w_v\, T_v \\
\text{s.t.}\quad
& \sum_{b} x_{vb} = 1 && \forall v &&\text{(Assign)}\\
& x_{vb} = 0 && \forall v, b : k_{vb} = 0 &&\text{(Compatible)}\\
& y_{uv} + y_{vu} = 1 && \forall (u,v) \in P : u < v &&\text{(Order)}\\
& t_u + p_{ub} \le t_v + M_{uvb}\,(3 - x_{ub} - x_{vb} - y_{uv}) && \forall (u,v) \in P,\ b &&\text{(NoOverlap)}\\
& t_v \ge s_b\, x_{vb} && \forall v, b : s_b > 0 &&\text{(BerthOpen)}\\
& T_v \ge c_v - d_v && \forall v &&\text{(Late)}\\
& a_v \le t_v \le a_v + W && \forall v &&\text{(bounds)}
\end{aligned}
$$

The constraint NoOverlap is active only when $u$ and $v$ both use berth $b$ and $u$ goes first. Then the three binary terms are 1 and the big-M term is 0. The bounds on $t$ give a small and valid big-M for each pair:

$$
M_{uvb} = \max\left(0,\; a_u + W + p_{ub} - a_v\right).
$$

A small big-M makes the LP relaxation stronger. Thus the solver finds the optimum faster.

### 12.3 Discrete berths: the procedure

1. Click **Examples > bap discrete**.
2. Look at each page from **Sets** to **Objectives**. Compare the forms with the formulation above.
3. Click **Solve** (F5).
4. Wait until the **Schedule** page opens.

The optimal cost is 189. The schedule shows two alarms: vessels V02 and V04 depart 1 h late. V04 also waits 5 h. The other vessels are normal.

To examine the plan:

1. Move the pointer on the bar of V04. Read the wait and the lateness.
2. Click **Plan**.
3. Click **Save HTML report**.

Try these changes. Solve again after each change and compare the plan.

| Change | Result |
|---|---|
| On **Objectives**, make `TotalLate` active. | 1 vessel departs 1 h late. The total wait increases from 15.5 h to 16.5 h. Two waits are longer than the warning limit. |
| On **Objectives**, make `TotalWait` active. | The total wait decreases to 12.5 h. But 3 vessels depart late. |
| On **Parameters**, select `s`. Set B3 to 0 (the berth opens at 06:00). | The cost decreases to 182. Only 1 vessel departs late. |

These results show the trade-off between waiting time and late departures. The objective `Cost` balances the two with the weight `lam`.

### 12.4 Continuous quay

In this model, the vessels share a quay of length $L$. The berth is a position $q_v$ on the quay. Two vessels must be apart in space or in time. The handling time increases with the distance from the preferred position $r_v$:

$$
h_v = h^0_v\left(1 + \beta\,\frac{\delta_v}{L}\right), \qquad \delta_v \ge q_v - r_v, \quad \delta_v \ge r_v - q_v .
$$

For each pair, binary variables $\ell_{uv}$ ($u$ left of $v$) and $\tau_{uv}$ ($u$ before $v$) select the separation:

$$
\begin{aligned}
& q_u + l_u \le q_v + L\,(1 - \ell_{uv}) && \forall (u,v) \in P\\
& t_u + h_u \le t_v + M\,(1 - \tau_{uv}) && \forall (u,v) \in P\\
& \ell_{uv} + \ell_{vu} + \tau_{uv} + \tau_{vu} \ge 1 && \forall (u,v) \in P : u < v
\end{aligned}
$$

Open **Examples > bap continuous** and solve. The optimal cost is approximately 420.27. The **Schedule** page shows a space-time chart. Each vessel is a rectangle: the width is the handling time and the height is the vessel length.

### 12.5 Uncertain arrivals

The stochastic example uses the discrete model with three scenarios:

| Scenario | Probability | Changes |
|---|---|---|
| Calm | 0.5 | None |
| Delays | 0.3 | V03 +4 h, V05 +6 h, V08 +3 h; all handling times × 1.1 |
| Storm | 0.2 | V01 +3 h, V05 +10 h, V08 +8 h, V10 +6 h; all handling times × 1.25 |

The first stage is the berth $x$ and the sequence $y$ of each vessel. The terminal publishes this plan before the vessels arrive. The second stage is the start time $t$ and the late departure $T$ in each scenario.

1. Click **Examples > bap stochastic**.
2. Click **Uncertainty**. Look at the scenarios and the changes.
3. Click **Solve**. The expected cost is 343.85.
4. On the **Schedule** page, select each scenario in **Scenario**. The berths and the sequence are the same. The times change.
5. Click **Analyze** (F6). Wait until the eight solves stop.

The analysis gives these values:

| Value | Result |
|---|---|
| RP | 343.85 |
| WS | 312.65 |
| EVPI | 31.2 |
| EEV | approximately 351.45 |
| VSS | approximately 7.6 |

> **Note:** EEV and VSS can be different with a different solver. If the EV problem has more than one optimal plan, each plan can give a different EEV.

The results show that a perfect forecast is worth at most 31.2. The stochastic plan saves 7.6 against a plan made with the mean data.

To make a plan that protects against the Storm scenario:

1. Click **Uncertainty**.
2. Set **Measure** to **Expected value + CVaR**.
3. Make sure that **CVaR level alpha** is 0.8.
4. Set **CVaR weight** to 0.5.
5. Click **Solve**.

The cost of the Storm scenario decreases from 666.75 to 612.5. The expected cost increases from 343.85 to 391.6. This is the price of a safer plan.

---

## 13 Export and automation

### 13.1 The Pyomo script

**Export Pyomo script** (Ctrl+E) writes a Python file. The file has the data, a `build` function with the full model, the extensive form for a stochastic model, and the solve. It needs only Pyomo and a solver. Use it to:

- Run the model on a server or in a scheduled job.
- Keep the model in version control.
- Learn Pyomo from your own model.

### 13.2 The command line

| Command | Action |
|---|---|
| `python -m pyomo_studio` | Open the program. |
| `python -m pyomo_studio model.json` | Open the program with a model. |
| `python -m pyomo_studio solve model.json --report plan.html` | Solve and write the HTML plan. |
| `python -m pyomo_studio solve model.json --analyze --report plan.html` | Solve, do the stochastic analysis and write the plan. |
| `python -m pyomo_studio solve model.json --csv schedule.csv --json results.json` | Write the schedule and the results. |
| `python -m pyomo_studio export model.json model.py` | Write the Pyomo script. |
| `python -m pyomo_studio validate model.json` | Find errors. |
| `python -m pyomo_studio solvers` | Show the installed solvers. |

Options of `solve`: `--solver NAME`, `--time-limit SECONDS`, `--quiet` (no solver log).

---

## 14 The model file

A model is a JSON file. You can read it and compare versions of it in version control. The file has these keys:

| Key | Content |
|---|---|
| `name`, `description` | Text. |
| `sets` | `name`, `kind` (`list`, `range`, `expression`), `elements`, `start`, `stop`, `step`, `expr`. |
| `params` | `name`, `index`, `value`, `default`, `values` (rows: index values, then the value), `formula`. |
| `variables` | `name`, `index`, `domain`, `lb`, `ub`, `init`, `stage`. |
| `expressions` | `name`, `index`, `expr`. |
| `constraints` | `name`, `index`, `condition`, `expr`, `active`. |
| `objectives` | `name`, `sense`, `expr`, `active`. |
| `stochastic` | `enabled`, `scenarios` (`name`, `probability`, `changes`), `risk` (`measure`, `alpha`, `weight`). |
| `schedule` | The schedule view fields (section 8.2). |
| `solver` | `name`, `time_limit`, `mip_gap`, `tee`, `duals`, `options`. |
| `hook` | The custom Python code. |

---

## 15 Troubleshooting

| Problem | Possible cause | Remedy |
|---|---|---|
| `Pyomo is not installed` | Pyomo is missing. | Write `pip install pyomo highspy`. |
| `Solver ... is not available` | The solver is not installed or not on the PATH. | Click **Find installed solvers**. Install the solver. Or select `appsi_highs`. |
| `NameError: name 'q' is not defined` | The expression uses a name that does not exist. | Correct the name. Names are case-sensitive. |
| `KeyError` in a parameter | A value is missing and the parameter has no default. | Write the value, or write a **Default value**. |
| `the constraint is always false for the data` | The data makes the constraint impossible at that index. | Examine the data. Or add a condition in **Only where**. |
| `a condition must give True or False from data only` | The condition uses a variable. | Use only index names and parameters in a condition. |
| `The model is infeasible` | No solution obeys all constraints. | Make constraints inactive one at a time to find the cause. Examine the bounds. |
| `The model is unbounded` | The objective can improve without limit. | Add bounds to the variables. |
| The solver stops at the time limit | The model is large or the big-M values are large. | Increase the time limit. Set a MIP gap of 0.01. Make the big-M values small. |
| No schedule | The view type is `No schedule`, or a field has an error. | Set the view on **Schedule > View settings**. Read the message below the graphic. |
| The window has no Mica | Windows 10, Windows 11 before 22H2, or Mica is off. | Update Windows. Set Mica on in **Settings**. Start the program again. |
| No icons in the window | The Segoe Fluent Icons font is missing (not Windows 11). | The program shows squares in place of the icons. All functions operate. |

---

## 16 Good practice

- Start with a small data set. Make sure that the model is correct. Then use the full data.
- Click **Validate** after each large change.
- Use bounds, not constraints, for limits on one variable.
- Keep big-M values as small as possible. Calculate them from the data.
- Give each item a description. The plan shows the descriptions in the formulation.
- Save the model often. Keep the model files in version control.
- Export the Pyomo script when the model is final. The script does not need the program.

---

## 17 Glossary

| Term | Meaning |
|---|---|
| Alarm | An abnormal state of priority 1. In the schedule: a late task or an overlap. |
| Big-M | A large constant that makes a constraint inactive when a binary variable has a specified value. |
| Binding constraint | A constraint with a slack of 0. |
| CVaR | Conditional value at risk. The mean cost of the worst part of the scenarios. |
| Dual value | The change of the objective when the right side of a constraint increases by 1 (LP only). |
| EEV | The expected result of the plan that the mean data gives. |
| EVPI | Expected value of perfect information: RP − WS. |
| Extensive form | One model with a copy of each scenario and non-anticipativity constraints. |
| First stage | Decisions made before the uncertain data is known. They are the same in all scenarios. |
| ISA-101 | A standard for process graphics. Normal states are gray. Color shows abnormal states. |
| MIP gap | The relative distance between the best solution and the best bound. |
| Non-anticipativity | The rule that first-stage decisions cannot use information from the future. |
| RP | Recourse problem: the stochastic model with the expected-value objective. |
| Second stage | Decisions made after the uncertain data is known. They change with the scenario. |
| Slack | The distance from the constraint value to its limit. |
| VSS | Value of the stochastic solution: EEV − RP. |
| Warning | An abnormal state of priority 2. In the schedule: a wait longer than the limit. |
| WS | Wait and see: the expected result with perfect information. |
