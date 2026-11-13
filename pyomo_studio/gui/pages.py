"""Pages of the Pyomo Studio window."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QTextDocument
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QDoubleSpinBox, QFileDialog,
                               QGridLayout, QHBoxLayout, QHeaderView, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPlainTextEdit, QRadioButton, QSlider,
                               QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget,
                               QTextBrowser, QVBoxLayout, QWidget, QFrame)

from .. import APP_NAME, __version__
from .. import engine as E
from .. import report as R
from .. import schedule as SCH
from .. import spec as S
from .widgets import (Card, ExprEdit, Form, GanttScroll, InfoBar, PageHeader, ParamGrid,
                      ToggleSwitch, button, label, scroll_page, tool)

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"
GUIDE_PATH = Path(__file__).resolve().parent.parent / "docs" / "USER_GUIDE.md"


def mono_line(placeholder: str = "") -> QLineEdit:
    from .theme import mono_font
    w = QLineEdit()
    w.setFont(mono_font(13))
    w.setPlaceholderText(placeholder)
    return w


def read_only_table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setAlternatingRowColors(True)
    t.verticalHeader().setVisible(False)
    t.verticalHeader().setDefaultSectionSize(28)
    t.horizontalHeader().setStretchLastSection(True)
    t.setSortingEnabled(False)
    return t


def fill_table(t: QTableWidget, rows: list[list], numeric_cols: set[int] = frozenset(),
               state_col: int | None = None, states: list | None = None) -> None:
    from PySide6.QtGui import QBrush, QColor
    t.setSortingEnabled(False)
    t.setRowCount(len(rows))
    for i, row in enumerate(rows):
        for j, val in enumerate(row):
            it = QTableWidgetItem("" if val is None else str(val))
            if j in numeric_cols:
                it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if state_col is not None and states and j == state_col:
                st = states[i]
                if st == "alarm":
                    it.setBackground(QBrush(QColor(SCH.ISA["alarm"])))
                    it.setForeground(QBrush(QColor(SCH.ISA["alarm_text"])))
                elif st == "warning":
                    it.setBackground(QBrush(QColor(SCH.ISA["warning"])))
                    it.setForeground(QBrush(QColor(SCH.ISA["warning_text"])))
            t.setItem(i, j, it)
    t.resizeColumnsToContents()
    t.horizontalHeader().setStretchLastSection(True)


def h_row(*widgets, stretch_end: bool = True, spacing: int = 8) -> QHBoxLayout:
    h = QHBoxLayout()
    h.setSpacing(spacing)
    for w in widgets:
        if w is None:
            h.addStretch(1)
        elif isinstance(w, QWidget):
            h.addWidget(w)
        else:
            h.addLayout(w)
    if stretch_end:
        h.addStretch(1)
    return h


# ---------------------------------------------------------------------------
# Home
# ---------------------------------------------------------------------------

class HomePage(QWidget):
    def __init__(self, studio):
        super().__init__()
        self.studio = studio
        body = QWidget()
        v = QVBoxLayout(body)
        v.setSpacing(16)
        v.addWidget(PageHeader(APP_NAME, "Make, solve and plan with Pyomo optimization models. "
                                         "Use the navigation on the left in order, from Sets to Plan."))
        card = Card("Model")
        self.form = Form()
        self.name = QLineEdit()
        self.desc = QPlainTextEdit()
        self.desc.setFixedHeight(84)
        self.form.add("name", "Name", self.name)
        self.form.add("desc", "Description", self.desc)
        card.add(self.form)
        self.summary = label("", "secondary", wrap=True)
        card.add(self.summary)
        v.addWidget(card)
        self.name.textEdited.connect(self._name)
        self.desc.textChanged.connect(self._desc)
        self._loading = False

        steps = Card("Steps", "A model has these parts. Make them in this order.")
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(6)
        texts = [
            ("1  Sets", "Index lists, for example vessels V and berths B."),
            ("2  Parameters", "Data: numbers with or without an index."),
            ("3  Variables", "Decisions that the solver finds."),
            ("4  Expressions", "Named parts of formulas that you use again."),
            ("5  Constraints", "Rules that a solution must obey."),
            ("6  Objectives", "The measure to minimize or maximize."),
            ("7  Uncertainty", "Optional: scenarios for stochastic programming."),
            ("8  Solve", "Select a solver and solve."),
            ("9  Results, Schedule, Plan", "Read the solution, the schedule and the report."),
        ]
        for i, (a, b) in enumerate(texts):
            grid.addWidget(label(a, "strong"), i, 0)
            grid.addWidget(label(b, "secondary"), i, 1)
        steps.add(grid)
        guide = button("Open the user guide", "guide")
        guide.clicked.connect(lambda: studio.go_page("guide"))
        steps.add(h_row(guide))
        v.addWidget(steps)

        ex = Card("Examples", "Open an example to learn how a model is made. "
                              "The Berth Allocation examples also show the schedule and the plan.")
        for path in sorted(EXAMPLES_DIR.glob("*.json")):
            try:
                with open(path, encoding="utf-8") as fh:
                    d = json.load(fh)
            except (OSError, ValueError):
                continue
            row = QFrame()
            row.setProperty("card", True)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(14, 10, 10, 10)
            txt = QVBoxLayout()
            txt.addWidget(label(d.get("name", path.stem), "strong"))
            txt.addWidget(label(d.get("description", ""), "caption", wrap=True))
            rl.addLayout(txt, 1)
            b = button("Open", "open")
            b.clicked.connect(lambda _=False, p=path: studio.open_model(str(p)))
            rl.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
            ex.add(row)
        v.addWidget(ex)
        v.addStretch(1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(scroll_page(body))

    def _name(self, txt):
        if not self._loading:
            self.studio.spec["name"] = txt
            self.studio.mark_dirty()

    def _desc(self):
        if not self._loading:
            self.studio.spec["description"] = self.desc.toPlainText()
            self.studio.mark_dirty()

    def on_show(self):
        sp = self.studio.spec
        self._loading = True
        self.name.setText(sp.get("name", ""))
        if self.desc.toPlainText() != sp.get("description", ""):
            self.desc.setPlainText(sp.get("description", ""))
        self._loading = False
        counts = ", ".join(f"{len(sp[k])} {S.KIND_LABEL[k].lower()}{'s' if len(sp[k]) != 1 else ''}"
                           for k in S.COMPONENT_KINDS)
        st = "Stochastic: on, " + f"{len(sp['stochastic']['scenarios'])} scenarios." \
            if sp["stochastic"].get("enabled") else "Stochastic: off."
        cls = ""
        if self.studio.result is not None:
            cls = f" Last solve: {self.studio.result.stats.get('class')}."
        self.summary.setText(f"{counts}. {st}{cls}")


# ---------------------------------------------------------------------------
# Component editor pages
# ---------------------------------------------------------------------------

KIND_INFO = {
    "sets": ("Sets", "Sets are the index lists of the model, for example vessels V and berths B. "
                     "A set can be a list, an integer range or a Python expression of other sets.", "S"),
    "params": ("Parameters", "Parameters are the data. A parameter with an index has one value for each "
                             "index value, for example the arrival time a[v] of each vessel.", "p"),
    "variables": ("Variables", "Variables are the decisions. The solver finds their values.", "x"),
    "expressions": ("Expressions", "A named expression is a formula that you use in more than one place, "
                                   "for example the departure time dep[v] = t[v] + hand[v].", "e"),
    "constraints": ("Constraints", "Constraints are the rules of the model. Write one relation with ==, <= "
                                   "or >=. The program makes one constraint for each index value.", "c"),
    "objectives": ("Objectives", "The objective is the measure to minimize or maximize. Only one objective is "
                                 "active. The program shows the value of the other objectives as measures.", "obj"),
}

SET_KINDS = [("list", "List of elements"), ("range", "Integer range"), ("expression", "Python expression")]
STAGES = [(1, "1 - Here and now (first stage)"), (2, "2 - Wait and see (second stage)")]


class ComponentPage(QWidget):
    def __init__(self, studio, kind: str):
        super().__init__()
        self.studio = studio
        self.kind = kind
        self.cur: dict | None = None
        self._loading = False
        title, desc, self.stem = KIND_INFO[kind]
        outer = QVBoxLayout(self)
        outer.setContentsMargins(36, 28, 36, 20)
        outer.setSpacing(12)
        outer.addWidget(PageHeader(title, desc))
        self.b_add = tool("Add", "add", f"Add a {S.KIND_LABEL[kind].lower()}")
        self.b_dup = tool("Duplicate", "copy")
        self.b_del = tool("Delete", "delete")
        self.b_up = tool("", "up", "Move up", show_text=False)
        self.b_down = tool("", "down", "Move down", show_text=False)
        self.count = label("", "caption")
        outer.addLayout(h_row(self.b_add, self.b_dup, self.b_del, self.b_up, self.b_down, None, self.count,
                              stretch_end=False))
        self.b_add.clicked.connect(self.add)
        self.b_dup.clicked.connect(self.duplicate)
        self.b_del.clicked.connect(self.delete)
        self.b_up.clicked.connect(lambda: self.move(-1))
        self.b_down.clicked.connect(lambda: self.move(1))

        split = QSplitter(Qt.Orientation.Horizontal)
        self.list = QListWidget()
        self.list.setMinimumWidth(220)
        self.list.currentRowChanged.connect(self.show_item)
        split.addWidget(self.list)
        self.editor = QWidget()
        ev = QVBoxLayout(self.editor)
        ev.setContentsMargins(4, 0, 4, 12)
        self.form = Form()
        ev.addWidget(self.form)
        ev.addStretch(1)
        self.empty = label(f"There are no {title.lower()}. Click Add.", "secondary")
        ev.addWidget(self.empty)
        sa = scroll_page(self.editor, 900)
        sa.widget().layout().setContentsMargins(16, 0, 4, 0)
        split.addWidget(sa)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([260, 700])
        outer.addWidget(split, 1)
        self._build_editor()
        self.grid_timer = QTimer(self)
        self.grid_timer.setSingleShot(True)
        self.grid_timer.setInterval(450)
        self.grid_timer.timeout.connect(self.reload_grid)

    # -- list -----------------------------------------------------------------
    @property
    def items(self) -> list:
        return self.studio.spec[self.kind]

    def item_text(self, it: dict) -> str:
        k = self.kind
        n = it.get("name", "")
        if k == "sets":
            extra = {"list": f"{len(it.get('elements', []))} elements", "range": f"{it.get('start')}..{it.get('stop')}",
                     "expression": "expression"}.get(it.get("kind"), "")
        elif k == "params":
            extra = f"[{it['index']}]" if it.get("index") else f"= {it.get('value')}"
        elif k == "variables":
            extra = (f"[{it['index']}]  " if it.get("index") else "") + it.get("domain", "")
        elif k in ("constraints", "expressions"):
            extra = f"for {it['index']}" if it.get("index") else ""
            if k == "constraints" and not it.get("active", True):
                extra += "  (off)"
        else:
            extra = it.get("sense", "") + ("  - active" if it.get("active", True) else "")
        return f"{n}    {extra}".rstrip()

    def refresh(self, row: int | None = None) -> None:
        cur = self.list.currentRow() if row is None else row
        self.list.blockSignals(True)
        self.list.clear()
        for it in self.items:
            QListWidgetItem(self.item_text(it), self.list)
        self.list.blockSignals(False)
        n = len(self.items)
        self.count.setText(f"{n} item{'s' if n != 1 else ''}")
        if n:
            self.list.setCurrentRow(max(0, min(cur, n - 1)))
            self.show_item(self.list.currentRow())
        else:
            self.show_item(-1)

    def on_show(self):
        self.refresh()

    def update_row_text(self):
        r = self.list.currentRow()
        if 0 <= r < len(self.items):
            self.list.item(r).setText(self.item_text(self.items[r]))

    def add(self):
        name = S.unique_name(self.studio.spec, self.stem)
        it = S.new_item(self.kind, name)
        if self.kind == "objectives":
            it["active"] = not any(o.get("active", True) for o in self.items)
        self.items.append(it)
        self.studio.mark_dirty()
        self.refresh(len(self.items) - 1)
        self.f["name"].setFocus()
        self.f["name"].selectAll()

    def duplicate(self):
        r = self.list.currentRow()
        if r < 0:
            return
        it = copy.deepcopy(self.items[r])
        it["name"] = S.unique_name(self.studio.spec, it["name"])
        if self.kind == "objectives":
            it["active"] = False
        self.items.insert(r + 1, it)
        self.studio.mark_dirty()
        self.refresh(r + 1)

    def delete(self):
        r = self.list.currentRow()
        if r < 0:
            return
        name = self.items[r]["name"]
        if QMessageBox.question(self, "Delete", f"Delete {S.KIND_LABEL[self.kind].lower()} '{name}'?\n"
                                "Other components that use this name will then have errors.") \
                != QMessageBox.StandardButton.Yes:
            return
        del self.items[r]
        self.studio.mark_dirty()
        self.refresh(r)

    def move(self, d: int):
        r = self.list.currentRow()
        j = r + d
        if r < 0 or not 0 <= j < len(self.items):
            return
        self.items[r], self.items[j] = self.items[j], self.items[r]
        self.studio.mark_dirty()
        self.refresh(j)

    # -- editor ---------------------------------------------------------------
    def _build_editor(self):
        f = self.form
        self.f: dict[str, QWidget] = {}
        names = self.studio.names
        self.f["name"] = f.add("name", "Name", QLineEdit(), "Letters, digits and _. Start with a letter.")
        self.f["description"] = f.add("description", "Description", QLineEdit())
        k = self.kind
        if k == "sets":
            cb = QComboBox()
            for key, text in SET_KINDS:
                cb.addItem(text, key)
            self.f["kind"] = f.add("kind", "Type", cb)
            self.f["elements"] = f.add("elements", "Elements", QPlainTextEdit(),
                                       "One element on each line. Write a, b on one line for a tuple element.")
            self.f["elements"].setProperty("code", True)
            self.f["elements"].setFixedHeight(170)
            fill = QWidget()
            fl = QHBoxLayout(fill)
            fl.setContentsMargins(0, 0, 0, 0)
            self.fill_prefix = QLineEdit("V")
            self.fill_prefix.setFixedWidth(70)
            self.fill_from = QSpinBox()
            self.fill_from.setRange(0, 10**6)
            self.fill_from.setValue(1)
            self.fill_to = QSpinBox()
            self.fill_to.setRange(0, 10**6)
            self.fill_to.setValue(10)
            self.fill_digits = QSpinBox()
            self.fill_digits.setRange(0, 6)
            self.fill_digits.setValue(2)
            bfill = button("Fill", "refresh")
            bfill.clicked.connect(self.quick_fill)
            for w in (label("Prefix"), self.fill_prefix, label("from"), self.fill_from, label("to"),
                      self.fill_to, label("digits"), self.fill_digits, bfill):
                fl.addWidget(w)
            fl.addStretch(1)
            f.add("fill", "Quick fill", fill, "Makes elements like V01, V02, ... V10.")
            for key, lo in (("start", -10**9), ("stop", -10**9), ("step", -10**6)):
                sb = QSpinBox()
                sb.setRange(lo, 10**9)
                self.f[key] = f.add(key, key.capitalize(), sb)
            self.f["expr"] = f.add("expr", "Expression", ExprEdit(3, "[(u, v) for u in V for v in V if u != v]", names),
                                   "A Python expression of sets that are higher in the list.")
            self.preview = label("", "caption", wrap=True)
            f.add_widget(self.preview)
            cb.activated.connect(lambda _i: self.set("kind", cb.currentData()))
            self.f["elements"].textChanged.connect(self._elements_changed)
            for key in ("start", "stop", "step"):
                self.f[key].valueChanged.connect(lambda val, kk=key: self.set(kk, val))
        if k in ("params", "variables", "expressions", "constraints"):
            self.f["index"] = f.add("index", "For all" if k == "constraints" else "Index",
                                    mono_line("v in V, b in B"),
                                    "Write 'name in SET' for each index, for example 'v in V, b in B'. "
                                    "Write '(u, v) in PAIRS' for a set of pairs. Keep it empty for no index.")
        if k == "params":
            self.f["value"] = f.add("value", "Value", mono_line("0"), "The value of a parameter with no index.")
            self.f["default"] = f.add("default", "Default value", mono_line("0"),
                                      "Used for index values that have no value. Keep it empty to make a missing value an error.")
            self.f["formula"] = f.add("formula", "Formula (optional)", ExprEdit(2, "1 if l[v] <= depth[b] else 0", names),
                                      "Calculates each value from the index names and other parameters. "
                                      "A formula replaces the values in the grid.")
            gbox = QWidget()
            gv = QVBoxLayout(gbox)
            gv.setContentsMargins(0, 0, 0, 0)
            self.grid = ParamGrid()
            b_reload = tool("Reload grid", "refresh")
            b_imp = tool("Import CSV", "import")
            b_exp = tool("Export CSV", "export")
            b_clear = tool("Clear", "delete")
            gv.addLayout(h_row(b_reload, b_imp, b_exp, b_clear))
            gv.addWidget(self.grid)
            self.grid_msg = label("", "caption", wrap=True)
            gv.addWidget(self.grid_msg)
            f.add("grid", "Values", gbox, "Paste a block from Excel with Ctrl+V. Empty cells use the default value.")
            b_reload.clicked.connect(self.reload_grid)
            b_imp.clicked.connect(self.import_csv)
            b_exp.clicked.connect(self.export_csv)
            b_clear.clicked.connect(self.clear_grid)
            self.grid.changed.connect(self._grid_changed)
        if k == "variables":
            cb = QComboBox()
            cb.addItems(S.DOMAINS)
            self.f["domain"] = f.add("domain", "Domain", cb, "Binary for yes/no decisions. Integers for counts.")
            cb.activated.connect(lambda _i: self.set("domain", cb.currentText()))
            self.f["lb"] = f.add("lb", "Lower bound", mono_line("a[v]"), "A number or an expression of parameters. Optional.")
            self.f["ub"] = f.add("ub", "Upper bound", mono_line(""), "Optional.")
            self.f["init"] = f.add("init", "Start value", mono_line(""), "Optional start value for the solver.")
            st = QComboBox()
            for val, text in STAGES:
                st.addItem(text, val)
            self.f["stage"] = f.add("stage", "Stage (stochastic models only)", st,
                                    "First-stage decisions are the same in all scenarios. "
                                    "Second-stage decisions change with the scenario.")
            st.activated.connect(lambda _i: self.set("stage", st.currentData()))
        if k == "constraints":
            self.f["condition"] = f.add("condition", "Only where (optional)", mono_line("u < v"),
                                        "A condition on the index and the data. The program skips index values where it is false.")
        if k == "objectives":
            cb = QComboBox()
            cb.addItems(["minimize", "maximize"])
            self.f["sense"] = f.add("sense", "Sense", cb)
            cb.activated.connect(lambda _i: self.set("sense", cb.currentText()))
        if k in ("expressions", "constraints", "objectives"):
            ph = {"expressions": "t[v] + sum(p[v, b] * x[v, b] for b in B)",
                  "constraints": "sum(x[v, b] for b in B) == 1",
                  "objectives": "sum(w[v] * (dep[v] - a[v]) for v in V)"}[k]
            self.f["expr"] = f.add("expr", "Expression", ExprEdit(4, ph, names),
                                   "Python syntax with Pyomo components. Use sum(... for ... in ...) for sums.")
        if k == "constraints":
            self.f["active"] = f.add("active", "", ToggleSwitch("Active"),
                                     "An inactive constraint stays in the file but is not in the model.")
            self.f["active"].clicked.connect(lambda on: self.set("active", bool(on)))
        if k == "objectives":
            self.f["active"] = f.add("active", "", ToggleSwitch("Optimize this objective"),
                                     "Only one objective is optimized. The program reports the others as measures.")
            self.f["active"].clicked.connect(self._objective_active)

        # Text bindings (user edits only).
        for key in ("name", "description", "index", "value", "default", "lb", "ub", "init", "condition"):
            w = self.f.get(key)
            if isinstance(w, QLineEdit):
                w.textEdited.connect(lambda txt, kk=key: self.set(kk, txt))
        for key in ("expr", "formula"):
            w = self.f.get(key)
            if isinstance(w, ExprEdit):
                w.edited.connect(lambda txt, kk=key: self.set(kk, txt))

    def show_item(self, row: int):
        has = 0 <= row < len(self.items)
        self.cur = self.items[row] if has else None
        self.form.setVisible(has)
        self.empty.setVisible(not has)
        for b in (self.b_dup, self.b_del, self.b_up, self.b_down):
            b.setEnabled(has)
        if not has:
            return
        it = self.cur
        self._loading = True
        for key, w in self.f.items():
            val = it.get(key, "")
            if isinstance(w, QLineEdit):
                w.setText("" if val is None else str(val))
            elif isinstance(w, ExprEdit):
                w.set_text(val or "")
            elif isinstance(w, QPlainTextEdit) and key == "elements":
                w.blockSignals(True)
                w.setPlainText(S.format_elements(val or []))
                w.blockSignals(False)
            elif isinstance(w, QComboBox):
                idx = w.findData(val) if w.findData(val) >= 0 else w.findText(str(val))
                w.setCurrentIndex(max(0, idx))
            elif isinstance(w, QSpinBox):
                w.blockSignals(True)
                w.setValue(int(val or 0))
                w.blockSignals(False)
            elif isinstance(w, ToggleSwitch):
                w.setChecked(bool(val) if val != "" else True)
        self._loading = False
        for key in self.form.errors:
            self.form.set_error(key, "")
        self.update_visibility()
        self.check_all()
        if self.kind == "params":
            self.reload_grid()
        if self.kind == "sets":
            self.update_preview()

    def update_visibility(self):
        it = self.cur
        if it is None:
            return
        if self.kind == "sets":
            kind = it.get("kind", "list")
            for key in ("elements", "fill"):
                self.form.show_row(key, kind == "list")
            for key in ("start", "stop", "step"):
                self.form.show_row(key, kind == "range")
            self.form.show_row("expr", kind == "expression")
        if self.kind == "params":
            indexed = bool((it.get("index") or "").strip())
            has_formula = bool((it.get("formula") or "").strip())
            self.form.show_row("value", not indexed and not has_formula)
            self.form.show_row("default", indexed)
            self.form.show_row("grid", indexed and not has_formula)

    def set(self, key: str, value):
        if self._loading or self.cur is None:
            return
        self.cur[key] = value
        self.studio.mark_dirty()
        self.update_row_text()
        self.check_field(key)
        if key in ("kind", "index", "formula"):
            self.update_visibility()
        if self.kind == "params" and key == "index":
            self.grid_timer.start()
        if self.kind == "sets":
            self.update_preview()

    def check_field(self, key: str):
        it = self.cur
        if it is None:
            return
        msg = ""
        if key == "name":
            n = it.get("name", "")
            others = [x for kind in S.COMPONENT_KINDS for x in self.studio.spec[kind] if x is not it]
            if not S._NAME_RE.match(n or ""):
                msg = "Use letters, digits and _. Start with a letter."
            elif n in S.RESERVED_NAMES:
                msg = "The program uses this name. Use a different name."
            elif any(x.get("name") == n for x in others):
                msg = "Another component has this name."
        elif key == "index":
            try:
                for item in S.parse_index(it.get("index", "")):
                    if item.set_name not in {s["name"] for s in self.studio.spec["sets"]}:
                        msg = f"Set '{item.set_name}' does not exist."
            except S.SpecError as exc:
                msg = exc.message
        elif key in ("expr", "formula", "condition", "lb", "ub", "init"):
            text = it.get(key, "")
            if isinstance(text, str) and text.strip():
                try:
                    S.compile_expr(text, key)
                except S.SpecError as exc:
                    msg = exc.message
            elif key == "expr" and self.kind in ("expressions", "constraints", "objectives"):
                msg = "Write the expression."
        elif key in ("value", "default"):
            text = str(it.get(key, ""))
            if text.strip() and not isinstance(S.parse_scalar(text), (int, float)):
                msg = "Write a number."
        self.form.set_error(key, msg)

    def check_all(self):
        for key in ("name", "index", "expr", "formula", "condition", "lb", "ub", "init", "value", "default"):
            if key in self.f:
                self.check_field(key)

    # -- sets -----------------------------------------------------------------
    def _elements_changed(self):
        if self._loading or self.cur is None:
            return
        self.cur["elements"] = S.parse_elements(self.f["elements"].toPlainText())
        self.studio.mark_dirty()
        self.update_row_text()
        self.update_preview()

    def quick_fill(self):
        pre = self.fill_prefix.text()
        d = self.fill_digits.value()
        a, b = self.fill_from.value(), self.fill_to.value()
        els = [f"{pre}{i:0{d}d}" if d else f"{pre}{i}" for i in range(a, b + 1)]
        self.f["elements"].setPlainText("\n".join(els))

    def update_preview(self):
        try:
            sets = S.resolve_sets(self.studio.spec)
            els = sets.get(self.cur["name"], [])
            shown = ", ".join(S.format_element(e) if not isinstance(e, tuple) else f"({S.format_element(e)})"
                              for e in els[:12])
            more = " ..." if len(els) > 12 else ""
            self.preview.setText(f"{len(els)} elements: {shown}{more}")
            self.preview.setProperty("role", "caption")
        except S.SpecError as exc:
            self.preview.setText(str(exc))
            self.preview.setProperty("role", "error")
        self.preview.style().unpolish(self.preview)
        self.preview.style().polish(self.preview)

    # -- params ---------------------------------------------------------------
    def reload_grid(self):
        if self.kind != "params" or self.cur is None:
            return
        it = self.cur
        try:
            items = S.parse_index(it.get("index", ""))
            sets = S.resolve_sets(self.studio.spec)
        except S.SpecError as exc:
            self.grid_msg.setText(str(exc))
            return
        if not items:
            return
        msg = self.grid.load(items, sets, it.get("values", []))
        self.grid_msg.setText(msg)

    def _grid_changed(self):
        if self.cur is None or self._loading:
            return
        self.cur["values"] = self.grid.rows()
        self.studio.mark_dirty()

    def import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import values", self.studio.last_dir(), "CSV files (*.csv);;All files (*)")
        if not path:
            return
        with open(path, encoding="utf-8-sig") as fh:
            n = self.grid.import_csv(fh.read())
        self.grid_msg.setText(f"{n} values read from {Path(path).name}.")

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export values", self.studio.last_dir(f"{self.cur['name']}.csv"),
                                              "CSV files (*.csv)")
        if path:
            Path(path).write_text(self.grid.export_csv(), encoding="utf-8")

    def clear_grid(self):
        if self.cur is None:
            return
        self.cur["values"] = []
        self.studio.mark_dirty()
        self.reload_grid()

    # -- objectives -------------------------------------------------------------
    def _objective_active(self, on: bool):
        if self._loading or self.cur is None:
            return
        for o in self.items:
            o["active"] = False
        self.cur["active"] = True
        self.f["active"].setChecked(True)
        self.studio.mark_dirty()
        self.refresh()


# ---------------------------------------------------------------------------
# Uncertainty
# ---------------------------------------------------------------------------

class UncertaintyPage(QWidget):
    def __init__(self, studio):
        super().__init__()
        self.studio = studio
        self._loading = False
        body = QWidget()
        v = QVBoxLayout(body)
        v.setSpacing(16)
        v.addWidget(PageHeader("Uncertainty", "Add scenarios to make a two-stage stochastic program. "
                                              "Each scenario changes some parameters. First-stage decisions are the "
                                              "same in all scenarios. The program solves the extensive form."))
        top = Card()
        self.enabled = ToggleSwitch("Use a stochastic model")
        self.enabled.clicked.connect(self._enabled)
        top.add(self.enabled)
        self.stage_info = label("", "secondary", wrap=True)
        top.add(self.stage_info)
        v.addWidget(top)

        risk = Card("Risk", "Expected value is risk-neutral. Mean-CVaR also reduces the cost of the worst "
                            "(1 - alpha) part of the scenarios.")
        self.measure = QComboBox()
        self.measure.addItem("Expected value", "expected")
        self.measure.addItem("Expected value + CVaR", "cvar")
        self.alpha = QDoubleSpinBox()
        self.alpha.setRange(0.5, 0.999)
        self.alpha.setDecimals(3)
        self.alpha.setSingleStep(0.05)
        self.weight = QDoubleSpinBox()
        self.weight.setRange(0, 1)
        self.weight.setDecimals(2)
        self.weight.setSingleStep(0.1)
        grid = QGridLayout()
        grid.addWidget(label("Measure"), 0, 0)
        grid.addWidget(self.measure, 0, 1)
        grid.addWidget(label("CVaR level alpha"), 1, 0)
        grid.addWidget(self.alpha, 1, 1)
        grid.addWidget(label("CVaR weight (0 to 1)"), 2, 0)
        grid.addWidget(self.weight, 2, 1)
        grid.setColumnStretch(2, 1)
        risk.add(grid)
        v.addWidget(risk)
        self.measure.activated.connect(lambda _i: self._risk("measure", self.measure.currentData()))
        self.alpha.valueChanged.connect(lambda x: self._risk("alpha", x))
        self.weight.valueChanged.connect(lambda x: self._risk("weight", x))

        sc = Card("Scenarios", "The probabilities must add to 1.")
        self.b_add = tool("Add", "add")
        self.b_dup = tool("Duplicate", "copy")
        self.b_del = tool("Delete", "delete")
        self.b_eq = tool("Equal probabilities", "refresh")
        self.psum = label("", "caption")
        sc.add(h_row(self.b_add, self.b_dup, self.b_del, self.b_eq, None, self.psum, stretch_end=False))
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Scenario", "Probability"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setMinimumHeight(170)
        sc.add(self.table)
        v.addWidget(sc)
        self.table.itemChanged.connect(self._scen_edited)
        self.table.currentCellChanged.connect(lambda r, *_: self.show_changes(r))
        self.b_add.clicked.connect(self.add_scenario)
        self.b_dup.clicked.connect(self.dup_scenario)
        self.b_del.clicked.connect(self.del_scenario)
        self.b_eq.clicked.connect(self.equal_probs)

        ch = Card("Changes in the selected scenario",
                  "Each row changes a parameter. Operation set writes the value, add adds it and scale "
                  "multiplies by it. Keep the index empty to change all index values.")
        self.c_add = tool("Add change", "add")
        self.c_del = tool("Delete change", "delete")
        ch.add(h_row(self.c_add, self.c_del))
        self.changes = QTableWidget(0, 4)
        self.changes.setHorizontalHeaderLabels(["Parameter", "Index (empty = all)", "Operation", "Value"])
        self.changes.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.changes.verticalHeader().setVisible(False)
        self.changes.setMinimumHeight(200)
        ch.add(self.changes)
        self.c_add.clicked.connect(self.add_change)
        self.c_del.clicked.connect(self.del_change)
        self.changes.itemChanged.connect(self._change_edited)
        v.addWidget(ch)
        v.addStretch(1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(scroll_page(body))

    @property
    def st(self) -> dict:
        return self.studio.spec["stochastic"]

    def on_show(self):
        self._loading = True
        self.enabled.setChecked(bool(self.st.get("enabled")))
        r = self.st["risk"]
        self.measure.setCurrentIndex(max(0, self.measure.findData(r.get("measure", "expected"))))
        self.alpha.setValue(float(r.get("alpha", 0.9)))
        self.weight.setValue(float(r.get("weight", 0.0)))
        self._loading = False
        first = [v["name"] for v in self.studio.spec["variables"] if int(v.get("stage", 2)) == 1]
        second = [v["name"] for v in self.studio.spec["variables"] if int(v.get("stage", 2)) != 1]
        self.stage_info.setText(f"First stage: {', '.join(first) or 'none'}.   "
                                f"Second stage: {', '.join(second) or 'none'}.   "
                                "Change the stage of a variable on the Variables page.")
        self.load_scenarios()

    def _enabled(self, on):
        self.st["enabled"] = bool(on)
        self.studio.mark_dirty()

    def _risk(self, key, val):
        if self._loading:
            return
        self.st["risk"][key] = val
        self.studio.mark_dirty()

    def load_scenarios(self, select: int | None = None):
        self._loading = True
        scen = self.st["scenarios"]
        cur = self.table.currentRow() if select is None else select
        self.table.setRowCount(len(scen))
        for i, s in enumerate(scen):
            self.table.setItem(i, 0, QTableWidgetItem(str(s.get("name", ""))))
            it = QTableWidgetItem(f"{float(s.get('probability', 0)):g}")
            it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(i, 1, it)
        self._loading = False
        self.update_sum()
        if scen:
            self.table.setCurrentCell(max(0, min(cur, len(scen) - 1)), 0)
            self.show_changes(self.table.currentRow())
        else:
            self.show_changes(-1)

    def update_sum(self):
        tot = sum(float(s.get("probability", 0) or 0) for s in self.st["scenarios"])
        ok = abs(tot - 1) < 1e-6
        self.psum.setText(f"Sum of probabilities: {tot:.6g}" + ("" if ok else "  - must be 1"))
        self.psum.setProperty("role", "caption" if ok else "error")
        self.psum.style().unpolish(self.psum)
        self.psum.style().polish(self.psum)

    def _scen_edited(self, it: QTableWidgetItem):
        if self._loading:
            return
        s = self.st["scenarios"][it.row()]
        if it.column() == 0:
            s["name"] = it.text().strip()
        else:
            val = S.parse_scalar(it.text())
            s["probability"] = float(val) if isinstance(val, (int, float)) else 0.0
            self.update_sum()
        self.studio.mark_dirty()

    def add_scenario(self):
        n = len(self.st["scenarios"]) + 1
        self.st["scenarios"].append({"name": f"S{n}", "probability": 0.0, "changes": []})
        self.studio.mark_dirty()
        self.load_scenarios(n - 1)

    def dup_scenario(self):
        r = self.table.currentRow()
        if r < 0:
            return
        s = copy.deepcopy(self.st["scenarios"][r])
        s["name"] = f"{s['name']}_copy"
        self.st["scenarios"].insert(r + 1, s)
        self.studio.mark_dirty()
        self.load_scenarios(r + 1)

    def del_scenario(self):
        r = self.table.currentRow()
        if r < 0:
            return
        del self.st["scenarios"][r]
        self.studio.mark_dirty()
        self.load_scenarios(r)

    def equal_probs(self):
        n = len(self.st["scenarios"])
        for s in self.st["scenarios"]:
            s["probability"] = round(1.0 / n, 12) if n else 0
        if n:
            self.st["scenarios"][-1]["probability"] = 1.0 - sum(s["probability"] for s in self.st["scenarios"][:-1])
        self.studio.mark_dirty()
        self.load_scenarios()

    def show_changes(self, r: int):
        self._loading = True
        scen = self.st["scenarios"]
        has = 0 <= r < len(scen)
        self.changes.setEnabled(has)
        self.c_add.setEnabled(has)
        self.c_del.setEnabled(has)
        rows = scen[r]["changes"] if has else []
        self.changes.setRowCount(len(rows))
        params = [p["name"] for p in self.studio.spec["params"]]
        for i, chg in enumerate(rows):
            cb = QComboBox()
            cb.addItems(params)
            cb.setCurrentText(chg.get("param", ""))
            cb.activated.connect(lambda _x, row=i, w=cb: self._change_set(row, "param", w.currentText()))
            self.changes.setCellWidget(i, 0, cb)
            self.changes.setItem(i, 1, QTableWidgetItem(str(chg.get("index", ""))))
            op = QComboBox()
            op.addItems(["set", "add", "scale"])
            op.setCurrentText(chg.get("op", "set"))
            op.activated.connect(lambda _x, row=i, w=op: self._change_set(row, "op", w.currentText()))
            self.changes.setCellWidget(i, 2, op)
            it = QTableWidgetItem(f"{chg.get('value', 0)}")
            it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.changes.setItem(i, 3, it)
        self.changes.resizeColumnToContents(0)
        self._loading = False

    def _cur_changes(self) -> list | None:
        r = self.table.currentRow()
        if 0 <= r < len(self.st["scenarios"]):
            return self.st["scenarios"][r]["changes"]
        return None

    def _change_set(self, row, key, val):
        ch = self._cur_changes()
        if ch is None or row >= len(ch):
            return
        ch[row][key] = val
        self.studio.mark_dirty()

    def _change_edited(self, it: QTableWidgetItem):
        if self._loading:
            return
        if it.column() == 1:
            self._change_set(it.row(), "index", it.text().strip())
        elif it.column() == 3:
            val = S.parse_scalar(it.text())
            self._change_set(it.row(), "value", float(val) if isinstance(val, (int, float)) else 0.0)

    def add_change(self):
        ch = self._cur_changes()
        if ch is None:
            return
        first = self.studio.spec["params"][0]["name"] if self.studio.spec["params"] else ""
        ch.append({"param": first, "index": "", "op": "scale", "value": 1.0})
        self.studio.mark_dirty()
        self.show_changes(self.table.currentRow())

    def del_change(self):
        ch = self._cur_changes()
        r = self.changes.currentRow()
        if ch is None or not 0 <= r < len(ch):
            return
        del ch[r]
        self.studio.mark_dirty()
        self.show_changes(self.table.currentRow())


# ---------------------------------------------------------------------------
# Solve
# ---------------------------------------------------------------------------

class SolvePage(QWidget):
    def __init__(self, studio):
        super().__init__()
        self.studio = studio
        self._loading = False
        body = QWidget()
        v = QVBoxLayout(body)
        v.setSpacing(16)
        v.addWidget(PageHeader("Solve", "Select a solver, then solve. HiGHS (appsi_highs) solves LP and MILP "
                                        "models and installs with pip install highspy."))
        self.info = InfoBar()
        v.addWidget(self.info)

        sc = Card("Solver")
        self.solver = QComboBox()
        self.solver.setEditable(True)
        self.solver.addItems(E.SOLVER_CHOICES)
        self.b_detect = button("Find installed solvers", "search")
        self.found = label("", "caption", wrap=True)
        sc.add(h_row(self.solver, self.b_detect))
        sc.add(self.found)
        grid = QGridLayout()
        self.time_limit = QDoubleSpinBox()
        self.time_limit.setRange(0, 10**6)
        self.time_limit.setDecimals(0)
        self.time_limit.setSuffix(" s")
        self.time_limit.setSpecialValueText("No limit")
        self.gap = QDoubleSpinBox()
        self.gap.setRange(0, 1)
        self.gap.setDecimals(6)
        self.gap.setSingleStep(0.001)
        grid.addWidget(label("Time limit"), 0, 0)
        grid.addWidget(self.time_limit, 0, 1)
        grid.addWidget(label("Relative MIP gap"), 1, 0)
        grid.addWidget(self.gap, 1, 1)
        grid.setColumnStretch(2, 1)
        sc.add(grid)
        self.tee = ToggleSwitch("Show the solver log")
        self.duals = ToggleSwitch("Get duals (LP only)")
        sc.add(h_row(self.tee, self.duals, spacing=24))
        sc.add(label("More solver options, one on each line as name = value:", "secondary"))
        self.extra = QPlainTextEdit()
        self.extra.setProperty("code", True)
        self.extra.setFixedHeight(70)
        self.extra.setPlaceholderText("presolve = on\nthreads = 4")
        sc.add(self.extra)
        v.addWidget(sc)
        self.solver.currentTextChanged.connect(lambda t: self._set("name", t))
        self.time_limit.valueChanged.connect(lambda x: self._set("time_limit", x or ""))
        self.gap.valueChanged.connect(lambda x: self._set("mip_gap", x))
        self.tee.clicked.connect(lambda on: self._set("tee", bool(on)))
        self.duals.clicked.connect(lambda on: self._set("duals", bool(on)))
        self.extra.textChanged.connect(lambda: self._set("options", self.extra.toPlainText()))
        self.b_detect.clicked.connect(studio.detect_solvers)

        run = Card("Run")
        self.b_validate = button("Validate", "check")
        self.b_build = button("Build only", "code", tip="Build the model and show its size, no solve")
        self.b_solve = button("Solve", "solve", accent=True)
        self.b_analyze = button("Stochastic analysis", "analyze",
                                tip="Solve RP, WS, EV and EEV; calculate EVPI and VSS")
        run.add(h_row(self.b_validate, self.b_build, self.b_solve, self.b_analyze))
        self.b_script = button("Export Pyomo script", "export")
        self.b_lp = button("Write LP / MPS / NL file", "export")
        run.add(h_row(self.b_script, self.b_lp))
        v.addWidget(run)
        self.b_validate.clicked.connect(studio.validate)
        self.b_build.clicked.connect(studio.build_only)
        self.b_solve.clicked.connect(studio.solve)
        self.b_analyze.clicked.connect(studio.analyze)
        self.b_script.clicked.connect(studio.export_script)
        self.b_lp.clicked.connect(studio.write_model_file)

        adv = Card("Custom Python hook (advanced)",
                   "Python code that runs after the build of each model or scenario block. Use m for the block "
                   "and pyo for pyomo.environ. Use it for components that the forms do not have, for example "
                   "pyomo.gdp disjunctions or piecewise functions.")
        self.hook = ExprEdit(9, "from pyomo.gdp import Disjunction\n# m.extra = pyo.Constraint(expr=m.t['V01'] <= 10)",
                             studio.names)
        self.hook.setTabChangesFocus(False)
        adv.add(self.hook)
        self.hook.edited.connect(lambda txt: self._set_hook(txt))
        v.addWidget(adv)

        logc = Card("Log")
        self.b_clear = tool("Clear", "delete")
        self.b_copy = tool("Copy", "copy")
        logc.add(h_row(self.b_clear, self.b_copy))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setProperty("code", True)
        self.log.setMinimumHeight(300)
        self.log.setMaximumBlockCount(20000)
        self.log.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        logc.add(self.log)
        self.b_clear.clicked.connect(self.log.clear)
        self.b_copy.clicked.connect(lambda: (self.log.selectAll(), self.log.copy()))
        v.addWidget(logc)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(scroll_page(body))

    def on_show(self):
        s = self.studio.spec["solver"]
        self._loading = True
        self.solver.setCurrentText(str(s.get("name", "appsi_highs")))
        try:
            self.time_limit.setValue(float(s.get("time_limit") or 0))
        except (TypeError, ValueError):
            self.time_limit.setValue(0)
        self.gap.setValue(float(s.get("mip_gap") or 0))
        self.tee.setChecked(bool(s.get("tee", True)))
        self.duals.setChecked(bool(s.get("duals", False)))
        if self.extra.toPlainText() != s.get("options", ""):
            self.extra.setPlainText(s.get("options", ""))
        self.hook.set_text(self.studio.spec.get("hook", ""))
        self._loading = False
        self.b_analyze.setEnabled(bool(self.studio.spec["stochastic"].get("enabled")))

    def _set(self, key, val):
        if self._loading:
            return
        self.studio.spec["solver"][key] = val
        self.studio.mark_dirty()

    def _set_hook(self, txt):
        if self._loading:
            return
        self.studio.spec["hook"] = txt
        self.studio.mark_dirty()

    def append_log(self, line: str):
        self.log.appendPlainText(line)

    def set_busy(self, busy: bool):
        for b in (self.b_validate, self.b_build, self.b_solve, self.b_analyze, self.b_detect, self.b_lp):
            b.setEnabled(not busy)
        if not busy:
            self.b_analyze.setEnabled(bool(self.studio.spec["stochastic"].get("enabled")))


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

class Metric(QFrame):
    def __init__(self, title: str):
        super().__init__()
        self.setProperty("card", True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(2)
        lay.addWidget(label(title, "caption"))
        self.value = label("-", "metric")
        lay.addWidget(self.value)
        self.sub = label("", "caption")
        lay.addWidget(self.sub)
        self.setMinimumWidth(150)

    def set(self, value: str, sub: str = ""):
        self.value.setText(value)
        self.sub.setText(sub)


class ResultsPage(QWidget):
    def __init__(self, studio):
        super().__init__()
        self.studio = studio
        body = QWidget()
        v = QVBoxLayout(body)
        v.setSpacing(16)
        v.addWidget(PageHeader("Results", "The solution of the last solve."))
        self.info = InfoBar(closable=False)
        v.addWidget(self.info)
        self.stale = InfoBar()
        v.addWidget(self.stale)
        grid = QGridLayout()
        grid.setSpacing(12)
        self.m_obj, self.m_status, self.m_gap = Metric("Objective"), Metric("Status"), Metric("MIP gap")
        self.m_time, self.m_class, self.m_size = Metric("Solve time"), Metric("Problem class"), Metric("Size")
        for i, m in enumerate((self.m_obj, self.m_status, self.m_gap, self.m_time, self.m_class, self.m_size)):
            grid.addWidget(m, i // 3, i % 3)
        v.addLayout(grid)
        self.stoch = Card("Uncertainty")
        self.stoch_text = label("", "secondary", wrap=True)
        self.stoch.add(self.stoch_text)
        self.scen_table = read_only_table(["Scenario", "Probability", "Objective", "RP", "WS", "EEV"])
        self.scen_table.setMinimumHeight(150)
        self.stoch.add(self.scen_table)
        v.addWidget(self.stoch)

        self.scenario = QComboBox()
        self.scenario.currentIndexChanged.connect(self.fill_tables)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter by name or index")
        self.filter.textChanged.connect(self.fill_tables)
        self.nonzero = ToggleSwitch("Hide zeros")
        self.nonzero.setChecked(True)
        self.nonzero.clicked.connect(self.fill_tables)
        self.binding = ToggleSwitch("Binding only")
        self.binding.clicked.connect(self.fill_tables)
        self.b_csv = tool("Export values CSV", "export")
        self.b_json = tool("Export results JSON", "export")
        self.b_csv.clicked.connect(studio.export_values_csv)
        self.b_json.clicked.connect(studio.export_results_json)
        v.addLayout(h_row(label("Scenario"), self.scenario, self.filter, self.nonzero, self.binding, None,
                          self.b_csv, self.b_json, stretch_end=False))
        self.tabs = QTabWidget()
        self.t_vars = read_only_table(["Variable", "Index", "Value", "Lower", "Upper"])
        self.t_expr = read_only_table(["Expression", "Index", "Value"])
        self.t_cons = read_only_table(["Constraint", "Index", "Activity", "Lower", "Upper", "Slack", "Dual"])
        self.t_kpi = read_only_table(["Objective", "Sense", "Value", "Optimized"])
        for t, name in ((self.t_vars, "Variables"), (self.t_expr, "Expressions"),
                        (self.t_cons, "Constraints"), (self.t_kpi, "Objectives")):
            t.setMinimumHeight(380)
            self.tabs.addTab(t, name)
        v.addWidget(self.tabs)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(scroll_page(body, 1300))

    def on_show(self):
        res = self.studio.result
        if res is None:
            self.info.show_message("info", "No results", "Solve the model on the Solve page.")
        if self.studio.results_stale and res is not None:
            self.stale.show_message("caution", "Changed model", "You changed the model after this solve. "
                                                              "Solve again to update the results.")
        else:
            self.stale.hide()

    def load(self, res, analysis=None):
        if res is None:
            return
        sev = "success" if res.ok and res.termination in ("optimal", "globallyOptimal") else (
            "caution" if res.ok else "critical")
        title = {"success": "Solved", "caution": "Solved with a limit", "critical": "No solution"}[sev]
        self.info.show_message(sev, title, res.message + (f"  ({res.label})" if res.label else ""))
        sense = "min" if res.sense == 1 else "max"
        self.m_obj.set(R.fnum(res.objective), f"{res.objective_name} ({sense}"
                       + (", expected)" if res.stochastic else ")"))
        self.m_status.set(res.termination, res.solver)
        self.m_gap.set(f"{res.gap:.3%}" if res.gap is not None else "-",
                       f"bound {R.fnum(res.best_bound)}" if res.best_bound is not None else "")
        self.m_time.set(f"{res.wall_time:.2f} s", "wall time")
        st = res.stats
        self.m_class.set(st.get("class", "-"), "stochastic extensive form" if res.stochastic else "deterministic")
        self.m_size.set(f"{st['variables']:,} var", f"{st['binary']:,} binary, {st['integer']:,} integer, "
                                                      f"{st['constraints']:,} constraints")
        self.stoch.setVisible(res.stochastic)
        if res.stochastic and res.ok:
            r = res.risk
            text = (f"Expected {res.objective_name}: {R.fnum(res.objective)}.   "
                    f"CVaR (alpha {r.get('alpha', 0.9):g}): {R.fnum(r.get('cvar'))}.   "
                    f"Worst: {R.fnum(r.get('worst'))}.   Best: {R.fnum(r.get('best'))}.")
            if analysis:
                text += (f"\nEVPI = {R.fnum(analysis.get('EVPI'))} (value of perfect information).   "
                         f"VSS = {R.fnum(analysis.get('VSS'))} (value of the stochastic solution).   "
                         f"WS = {R.fnum(analysis.get('WS'))}, EEV = {R.fnum(analysis.get('EEV'))}.")
                for n in analysis.get("notes", []):
                    text += f"\nNote: {n}"
            self.stoch_text.setText(text)
            per = {p["scenario"]: p for p in (analysis or {}).get("per_scenario", [])}
            rows = []
            for sc in res.scenarios:
                p = per.get(sc.name, {})
                rows.append([sc.name, f"{sc.probability:g}", R.fnum(sc.objective), R.fnum(p.get("rp")),
                             R.fnum(p.get("ws")), R.fnum(p.get("eev"))])
            fill_table(self.scen_table, rows, {1, 2, 3, 4, 5})
        self.scenario.blockSignals(True)
        self.scenario.clear()
        for sc in res.scenarios:
            self.scenario.addItem(sc.name)
        self.scenario.setEnabled(res.stochastic)
        self.scenario.blockSignals(False)
        self.fill_tables()

    def fill_tables(self, *_):
        res = self.studio.result
        if res is None or not res.ok:
            for t in (self.t_vars, self.t_expr, self.t_cons, self.t_kpi):
                t.setRowCount(0)
            return
        sc = res.scenario(self.scenario.currentText() or None)
        flt = self.filter.text().strip().lower()
        hide0 = self.nonzero.isChecked()
        built = res.built
        reg = built.regs[sc.name] if built else {}

        def keep(name, key, val):
            if flt and flt not in name.lower() and flt not in S.format_key(key).lower():
                return False
            return not (hide0 and (val is None or abs(val) < 1e-9))
        rows = []
        for name, vals in sc.values.items():
            comp = reg.get(name)
            for k, val in vals.items():
                if keep(name, k, val):
                    lb = ub = None
                    if comp is not None:
                        vd = comp[k] if k is not None else comp
                        lb, ub = vd.lb, vd.ub
                    rows.append([name, S.format_key(k), R.fnum(val), R.fnum(lb), R.fnum(ub)])
        fill_table(self.t_vars, rows[:20000], {2, 3, 4})
        rows = [[n, S.format_key(k), R.fnum(v)] for n, vals in sc.expressions.items() for k, v in vals.items()
                if keep(n, k, v)]
        fill_table(self.t_expr, rows[:20000], {2})
        rows = []
        for c in sc.constraints:
            if self.binding.isChecked() and not (c["slack"] is not None and abs(c["slack"]) <= 1e-6):
                continue
            if flt and flt not in c["name"].lower() and flt not in S.format_key(c["index"]).lower():
                continue
            rows.append([c["name"] + ("" if c["active"] else " (off)"), S.format_key(c["index"]), R.fnum(c["body"]),
                         R.fnum(c["lower"]), R.fnum(c["upper"]), R.fnum(c["slack"]), R.fnum(c["dual"])])
        fill_table(self.t_cons, rows[:20000], {2, 3, 4, 5, 6})
        spec = self.studio.result_spec or self.studio.spec
        rows = [[o["name"], o.get("sense"), R.fnum(sc.kpis.get(o["name"])),
                 "yes" if o["name"] == res.objective_name else ""] for o in spec["objectives"]]
        fill_table(self.t_kpi, rows, {2})


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------

SCHEDULE_FIELDS = [
    ("tasks", "Tasks (index)", "v in V", "One task for each index value."),
    ("condition", "Only where (optional)", "", "Skip tasks where this is false."),
    ("label", "Label", "v", "Text on the bar."),
    ("resource", "Resource (row)", "which(x, v)", "which(x, v) gives the b where x[v, b] = 1."),
    ("start", "Start", "t[v]", ""),
    ("duration", "Duration", "hand[v]", ""),
    ("release", "Release / arrival (optional)", "a[v]", "Wait = start - release."),
    ("due", "Due (optional)", "d[v]", "Late = end - due."),
    ("position", "Position (space-time)", "pos[v]", "Lower edge in space, for example the quay position."),
    ("size", "Size (space-time)", "len_[v]", "Height in space, for example the vessel length."),
    ("space_max", "Total space (space-time)", "L", ""),
    ("space_label", "Space axis label", "Quay position (m)", ""),
    ("time_unit", "Time unit", "h", "min, h or d gives clock times when the time origin is set."),
    ("time_origin", "Time origin (t = 0)", "2026-11-16 06:00", "Optional. Shows dates and clock times in the plan."),
    ("wait_warning", "Wait warning limit", "3", "A wait above this value is a warning (amber). Optional."),
    ("late_tolerance", "Late tolerance", "0.001", "Lateness above this value is an alarm (red)."),
]


class SchedulePage(QWidget):
    def __init__(self, studio):
        super().__init__()
        self.studio = studio
        self._loading = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(36, 28, 36, 20)
        outer.setSpacing(12)
        outer.addWidget(PageHeader("Schedule", "The plan as a process graphic (ISA-101): normal tasks are gray. "
                                               "Color shows only abnormal states: red with a 1 is an alarm (late or "
                                               "overlap), amber with a 2 is a warning (long wait)."))
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)

        # Plan view
        pv = QWidget()
        pl = QVBoxLayout(pv)
        pl.setContentsMargins(0, 12, 0, 0)
        pl.setSpacing(10)
        self.scenario = QComboBox()
        self.scenario.currentIndexChanged.connect(self.show_schedule)
        self.b_zo = tool("", "zoom_out", "Zoom out", show_text=False)
        self.b_zi = tool("", "zoom_in", "Zoom in", show_text=False)
        self.zoom = QSlider(Qt.Orientation.Horizontal)
        self.zoom.setRange(50, 800)
        self.zoom.setValue(100)
        self.zoom.setFixedWidth(160)
        self.b_svg = tool("Export SVG", "export")
        self.b_png = tool("Export PNG", "export")
        pl.addLayout(h_row(label("Scenario"), self.scenario, None, self.b_zo, self.zoom, self.b_zi,
                           self.b_svg, self.b_png, stretch_end=False))
        self.zoom.valueChanged.connect(lambda x: self.gantt.view.set_zoom(x / 100))
        self.b_zo.clicked.connect(lambda: self.zoom.setValue(int(self.zoom.value() / 1.25)))
        self.b_zi.clicked.connect(lambda: self.zoom.setValue(int(self.zoom.value() * 1.25)))
        self.b_svg.clicked.connect(self.export_svg)
        self.b_png.clicked.connect(self.export_png)
        kg = QHBoxLayout()
        kg.setSpacing(12)
        self.k_tasks, self.k_end, self.k_wait = Metric("Tasks"), Metric("Plan end"), Metric("Total wait")
        self.k_late, self.k_alarm = Metric("Late tasks"), Metric("Alarms / warnings")
        for m in (self.k_tasks, self.k_end, self.k_wait, self.k_late, self.k_alarm):
            kg.addWidget(m)
        pl.addLayout(kg)
        self.gantt = GanttScroll()
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.gantt)
        self.t_tasks = read_only_table(["Resource", "#", "Task", "Start", "End", "Duration", "Release", "Wait",
                                        "Due", "Late by", "State"])
        split.addWidget(self.t_tasks)
        split.setSizes([420, 240])
        pl.addWidget(split, 1)
        self.msg = label("", "secondary", wrap=True)
        pl.addWidget(self.msg)
        self.tabs.addTab(pv, "Plan view")

        # View settings
        body = QWidget()
        bv = QVBoxLayout(body)
        bv.setSpacing(12)
        bv.addWidget(label("The view maps the solution to tasks. Each field is an expression in the language "
                           "of the model, with the task index names.", "secondary", wrap=True))
        self.form = Form()
        self.type = QComboBox()
        self.type.addItem("No schedule", "none")
        self.type.addItem("Gantt chart (resource rows)", "gantt")
        self.type.addItem("Space-time chart (for example quay position)", "space_time")
        self.form.add("type", "View type", self.type)
        self.type.activated.connect(lambda _i: self._set("type", self.type.currentData()))
        self.fields: dict[str, QLineEdit] = {}
        for key, head, ph, hlp in SCHEDULE_FIELDS:
            w = mono_line(ph)
            self.fields[key] = self.form.add(key, head, w, hlp)
            w.textEdited.connect(lambda txt, kk=key: self._set(kk, txt))
        bv.addWidget(self.form)
        apply_b = button("Apply and draw", "refresh", accent=True)
        apply_b.clicked.connect(self.apply)
        bv.addLayout(h_row(apply_b))
        bv.addStretch(1)
        sa = scroll_page(body, 900)
        sa.widget().layout().setContentsMargins(0, 12, 0, 12)
        self.tabs.addTab(sa, "View settings")

    def on_show(self):
        sv = self.studio.spec["schedule"]
        self._loading = True
        self.type.setCurrentIndex(max(0, self.type.findData(sv.get("type", "none"))))
        for key, w in self.fields.items():
            w.setText(str(sv.get(key, "") or ""))
        self._loading = False
        self.update_rows()

    def update_rows(self):
        kind = self.studio.spec["schedule"].get("type", "none")
        for key in ("position", "size", "space_max", "space_label"):
            self.form.show_row(key, kind == "space_time")

    def _set(self, key, val):
        if self._loading:
            return
        self.studio.spec["schedule"][key] = val
        self.studio.mark_dirty(results_too=False)
        if key == "type":
            self.update_rows()

    def apply(self):
        self.studio.recompute_schedules()
        self.tabs.setCurrentIndex(0)

    def load(self):
        res = self.studio.result
        self.scenario.blockSignals(True)
        self.scenario.clear()
        if res is not None:
            for sc in res.scenarios:
                self.scenario.addItem(sc.name)
        self.scenario.setEnabled(res is not None and res.stochastic)
        self.scenario.blockSignals(False)
        self.show_schedule()

    def current(self):
        name = self.scenario.currentText()
        return self.studio.schedules.get(name) if name else None

    def show_schedule(self, *_):
        sched = self.current()
        err = self.studio.schedule_error
        self.msg.setText(err or ("" if sched else "There is no schedule. Solve a model and set the view on the "
                                                  "View settings tab."))
        title = "" if sched is None else (self.studio.spec.get("name", "") +
                                          (f" - scenario {self.scenario.currentText()}"
                                           if self.studio.result and self.studio.result.stochastic else ""))
        self.gantt.view.set_schedule(sched, title)
        if sched is None:
            self.t_tasks.setRowCount(0)
            for m in (self.k_tasks, self.k_end, self.k_wait, self.k_late, self.k_alarm):
                m.set("-")
            return
        k = sched.kpis
        u = sched.unit
        self.k_tasks.set(str(k.get("tasks", 0)), f"{len(sched.resources)} resources")
        self.k_end.set(sched.clock(k.get("plan_end")) if sched.origin else R.fnum(k.get("plan_end")),
                       f"span {SCH.format_duration(k.get('span'), u)}")
        self.k_wait.set(SCH.format_duration(k.get("wait_total"), u) if "wait_total" in k else "-",
                        f"longest {SCH.format_duration(k.get('wait_max'), u)}" if "wait_max" in k else "")
        self.k_late.set(R.fnum(k.get("late_count")) if "late_count" in k else "-",
                        f"total {SCH.format_duration(k.get('tardiness_total'), u)}" if "tardiness_total" in k else "")
        self.k_alarm.set(f"{k.get('alarms', 0)} / {k.get('warnings', 0)}", "priority 1 / priority 2")
        rows, states = [], []
        for r in SCH.schedule_rows(sched):
            rows.append([r["resource"], r["sequence"], r["task"], sched.clock(r["start"]), sched.clock(r["end"]),
                         SCH.format_duration(r["duration"], u), sched.clock(r["release"]),
                         SCH.format_duration(r["wait"], u), sched.clock(r["due"]),
                         SCH.format_duration(r["tardiness"], u),
                         r["state"].upper() + (": " + r["notes"] if r["notes"] else "")])
            states.append(r["state"])
        fill_table(self.t_tasks, rows, {1}, state_col=10, states=states)

    def export_svg(self):
        sched = self.current()
        if sched is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export schedule", self.studio.last_dir("schedule.svg"),
                                              "SVG image (*.svg)")
        if path:
            Path(path).write_text(SCH.schedule_svg(sched, 1400, self.studio.spec.get("name", "")), encoding="utf-8")

    def export_png(self):
        if self.current() is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export schedule", self.studio.last_dir("schedule.png"),
                                              "PNG image (*.png)")
        if path:
            self.gantt.view.to_image().save(path)


# ---------------------------------------------------------------------------
# Plan report
# ---------------------------------------------------------------------------

class PlanPage(QWidget):
    def __init__(self, studio):
        super().__init__()
        self.studio = studio
        self.html = ""
        self.md = ""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(36, 28, 36, 20)
        outer.setSpacing(12)
        outer.addWidget(PageHeader("Plan", "The detailed plan of the last solve. Save it as HTML (with the "
                                           "schedule graphic), Markdown or CSV."))
        self.b_html = button("Save HTML report", "save", accent=True)
        self.b_open = button("Open in browser", "globe")
        self.b_md = button("Save Markdown", "save")
        self.b_csv = button("Save schedule CSV", "export")
        outer.addLayout(h_row(self.b_html, self.b_open, self.b_md, self.b_csv))
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        outer.addWidget(self.view, 1)
        self.b_html.clicked.connect(lambda: self.save("html"))
        self.b_md.clicked.connect(lambda: self.save("md"))
        self.b_csv.clicked.connect(lambda: self.save("csv"))
        self.b_open.clicked.connect(self.open_browser)

    def load(self):
        res = self.studio.result
        if res is None:
            self.view.setMarkdown("*No plan. Solve the model first.*")
            return
        src = Path(self.studio.path).name if self.studio.path else ""
        self.html, self.md = R.make_report(self.studio.result_spec or self.studio.spec, res,
                                           self.studio.schedules, self.studio.analysis, src)
        self.view.setMarkdown(self.md)

    def save(self, fmt: str):
        if self.studio.result is None:
            return
        stem = (self.studio.spec.get("name") or "plan").replace(" ", "_")[:40]
        filt = {"html": "HTML report (*.html)", "md": "Markdown (*.md)", "csv": "CSV (*.csv)"}[fmt]
        path, _ = QFileDialog.getSaveFileName(self, "Save plan", self.studio.last_dir(f"{stem}_plan.{fmt}"), filt)
        if not path:
            return
        text = {"html": self.html, "md": self.md, "csv": R.schedule_csv(self.studio.schedules)}[fmt]
        Path(path).write_text(text, encoding="utf-8")
        self.studio.status(f"Saved {Path(path).name}.")

    def open_browser(self):
        if not self.html:
            return
        import tempfile
        fd = Path(tempfile.gettempdir()) / "pyomo_studio_plan.html"
        fd.write_text(self.html, encoding="utf-8")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(fd)))


# ---------------------------------------------------------------------------
# Guide and settings
# ---------------------------------------------------------------------------

class GuidePage(QWidget):
    def __init__(self, studio):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(36, 28, 36, 20)
        outer.setSpacing(12)
        outer.addWidget(PageHeader("User guide", "Written in ASD-STE100 Simplified Technical English."))
        self.find = QLineEdit()
        self.find.setPlaceholderText("Find in the guide")
        self.find.returnPressed.connect(self.find_next)
        b = button("Find next", "search")
        b.clicked.connect(self.find_next)
        outer.addLayout(h_row(self.find, b))
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        outer.addWidget(self.view, 1)
        try:
            self.view.setMarkdown(GUIDE_PATH.read_text(encoding="utf-8"))
        except OSError:
            self.view.setMarkdown(f"*The guide file is missing: {GUIDE_PATH}*")

    def find_next(self):
        txt = self.find.text()
        if txt and not self.view.find(txt):
            self.view.moveCursor(self.view.textCursor().MoveOperation.Start)
            self.view.find(txt, QTextDocument.FindFlag(0))


class SettingsPage(QWidget):
    def __init__(self, studio):
        super().__init__()
        self.studio = studio
        body = QWidget()
        v = QVBoxLayout(body)
        v.setSpacing(16)
        v.addWidget(PageHeader("Settings"))
        app = Card("Appearance")
        self.group = QButtonGroup(self)
        row = QHBoxLayout()
        for key, text in (("light", "Light"), ("dark", "Dark"), ("system", "Use the Windows setting" if sys.platform == "win32" else "Use the system setting")):
            rb = QRadioButton(text)
            rb.setProperty("key", key)
            self.group.addButton(rb)
            row.addWidget(rb)
        row.addStretch(1)
        app.add(label("Theme", "strong"))
        app.add(row)
        self.group.buttonClicked.connect(lambda b: studio.set_theme(b.property("key")))
        from .theme import mica_supported
        self.mica = ToggleSwitch("Mica window material")
        self.mica.setEnabled(mica_supported())
        self.mica.clicked.connect(lambda on: studio.set_mica(bool(on)))
        app.add(self.mica)
        app.add(label("Mica needs Windows 11 version 22H2 or later. Restart the program to apply a change.",
                      "caption", wrap=True))
        v.addWidget(app)
        about = Card("About")
        self.about = label("", "secondary", wrap=True)
        about.add(self.about)
        v.addWidget(about)
        v.addStretch(1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(scroll_page(body))

    def on_show(self):
        pref = self.studio.settings.value("theme", "system")
        for b in self.group.buttons():
            b.setChecked(b.property("key") == pref)
        self.mica.setChecked(self.mica.isEnabled()
                             and self.studio.settings.value("mica", True, type=bool))
        import platform
        try:
            from PySide6 import __version__ as qtv
        except ImportError:
            qtv = "?"
        try:
            import pyomo
            pv = pyomo.__version__
        except Exception:
            pv = "not installed"
        self.about.setText(f"{APP_NAME} {__version__}\nPython {platform.python_version()}, PySide6 {qtv}, "
                           f"Pyomo {pv}\nSettings file: {self.studio.settings.fileName()}")


