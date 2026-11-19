"""Layers page: add, switch on and off, and edit model layers.

The editor of a layer is made from the schema of its type (fields and
tables), so a new layer type needs no interface code.
"""
from __future__ import annotations

import copy

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QDoubleSpinBox, QGridLayout, QHeaderView, QLineEdit,
                               QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QSpinBox,
                               QSplitter, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget)

from .. import layers as L
from .. import spec as S
from .widgets import Card, ExprEdit, Form, InfoBar, PageHeader, ToggleSwitch, label, scroll_page, tool


def _h_row(*widgets, stretch_end: bool = True):
    from .pages import h_row
    return h_row(*widgets, stretch_end=stretch_end)


def _fmt(val) -> str:
    if isinstance(val, float) and val.is_integer():
        return f"{int(val)}"
    return "" if val is None else str(val)


class LayerTable(QTableWidget):
    """Editable table for one layer data table. Ctrl+V pastes a block from a spreadsheet."""

    def __init__(self, table: L.Table, rows: list[dict], on_change):
        super().__init__(0, len(table.columns))
        self.table = table
        self.data_rows = rows
        self.on_change = on_change
        self._loading = False
        heads = [c.label + (f" ({c.unit})" if c.unit else "") for c in table.columns]
        self.setHorizontalHeaderLabels(heads)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(28)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setStretchLastSection(True)
        self.setMinimumHeight(120)
        self.itemChanged.connect(self._edited)
        self.reload()

    def reload(self):
        self._loading = True
        self.setRowCount(len(self.data_rows))
        for i, row in enumerate(self.data_rows):
            for j, c in enumerate(self.table.columns):
                it = QTableWidgetItem(_fmt(row.get(c.key, c.default)))
                if c.kind in ("float", "int"):
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.setItem(i, j, it)
        self.setFixedHeight(min(420, 34 + 28 * max(3, len(self.data_rows))))
        self._loading = False

    def _value(self, col: L.Column, text: str):
        text = text.strip()
        if col.kind in ("float", "int"):
            val = S.parse_scalar(text) if text else col.default
            if isinstance(val, (int, float)):
                return int(round(val)) if col.kind == "int" else float(val)
            return text          # kept; the layer check reports it
        return text

    def _edited(self, it: QTableWidgetItem):
        if self._loading or it.row() >= len(self.data_rows):
            return
        col = self.table.columns[it.column()]
        self.data_rows[it.row()][col.key] = self._value(col, it.text())
        self.on_change()

    def add_row(self):
        row = {c.key: copy.deepcopy(c.default) for c in self.table.columns}
        kc = self.table.key_column
        if kc:
            names = {str(r.get(kc)) for r in self.data_rows}
            stem = str(self.table.columns[0].default).rstrip("0123456789") or "R"
            n = len(self.data_rows) + 1
            while f"{stem}{n}" in names:
                n += 1
            row[kc] = f"{stem}{n}"
        r = self.currentRow()
        pos = r + 1 if 0 <= r < len(self.data_rows) else len(self.data_rows)
        self.data_rows.insert(pos, row)
        self.reload()
        self.setCurrentCell(pos, 0)
        self.on_change()

    def delete_rows(self):
        rows = sorted({i.row() for i in self.selectedIndexes()}, reverse=True)
        if not rows and self.currentRow() >= 0:
            rows = [self.currentRow()]
        for r in rows:
            if 0 <= r < len(self.data_rows):
                del self.data_rows[r]
        self.reload()
        self.on_change()

    def keyPressEvent(self, e):
        if e.matches(QKeySequence.StandardKey.Paste):
            self.paste()
            return
        super().keyPressEvent(e)

    def paste(self):
        text = QGuiApplication.clipboard().text()
        lines = [ln for ln in text.replace("\r", "").split("\n") if ln.strip()]
        if not lines:
            return
        r0 = max(0, self.currentRow())
        c0 = max(0, self.currentColumn())
        for i, line in enumerate(lines):
            r = r0 + i
            while r >= len(self.data_rows):
                self.data_rows.append({c.key: copy.deepcopy(c.default) for c in self.table.columns})
            for j, cell in enumerate(line.split("\t")):
                c = c0 + j
                if c < len(self.table.columns):
                    col = self.table.columns[c]
                    self.data_rows[r][col.key] = self._value(col, cell)
        self.reload()
        self.on_change()


class LayersPage(QWidget):
    def __init__(self, studio):
        super().__init__()
        self.studio = studio
        self._loading = False
        self.cur: dict | None = None
        v = QVBoxLayout(self)
        v.setContentsMargins(36, 28, 36, 20)
        v.setSpacing(12)
        v.addWidget(PageHeader("Layers", "A layer is a sub-model that you can switch on and off, for example berths, "
                                         "a tank farm or crude units. Layers connect through ports. When the "
                                         "layer at the other end of a port is off, a layer uses its fallback data. "
                                         "The components on the model pages are always in the model, except "
                                         "those that you give to a custom layer."))
        self.info = InfoBar(closable=False)
        v.addWidget(self.info)

        grid = Card("Shared time grid and grades", spacing=8)
        grid.setToolTip("All layers use the same periods. The model gets the set PERIODS (1, 2, ...), "
                        "the parameter period_h and the set GRADES.")
        self.periods = QSpinBox()
        self.periods.setRange(1, 10000)
        self.period_h = QDoubleSpinBox()
        self.period_h.setRange(0.01, 10000)
        self.period_h.setDecimals(2)
        self.start = QLineEdit()
        self.start.setPlaceholderText("2026-11-16 06:00")
        self.grades = QLineEdit()
        self.grades.setPlaceholderText("LSW, ARL, HSR")
        self.horizon = label("", "caption")
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        self.obj_name = QLineEdit()
        self.include_base = ToggleSwitch("Add the objective of the model pages")
        self.include_base.setToolTip("Add the active objective of the model pages to the total of the layer costs.")
        cells = [(label("Periods"), self.periods), (label("Period (h)"), self.period_h),
                 (label("Start"), self.start), (label("Grades"), self.grades)]
        for j, (lb, w) in enumerate(cells):
            g.addWidget(lb, 0, 2 * j)
            g.addWidget(w, 0, 2 * j + 1)
        g.addWidget(label("Total objective"), 1, 0)
        g.addWidget(self.obj_name, 1, 1, 1, 3)
        g.addWidget(self.include_base, 1, 4, 1, 3)
        g.addWidget(self.horizon, 1, 7)
        g.setColumnStretch(7, 1)
        grid.add(g)
        v.addWidget(grid)
        self.periods.valueChanged.connect(lambda x: self._grid("periods", x))
        self.period_h.valueChanged.connect(lambda x: self._grid("period_h", x))
        self.start.textEdited.connect(lambda t: self._grid("start", t.strip()))
        self.grades.textEdited.connect(
            lambda t: self._grid("grades", [x.strip() for x in t.split(",") if x.strip()]))
        self.obj_name.textEdited.connect(lambda t: self._objective("name", t.strip() or L.base.TOTAL_OBJECTIVE))
        self.include_base.clicked.connect(lambda on: self._objective("include_base", bool(on)))

        self.b_add = QToolButton()
        self.b_add.setText("Add layer")
        from .widgets import Icons
        Icons.bind(self.b_add, "add")
        self.b_add.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.b_add.setAutoRaise(True)
        self.b_add.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self)
        for type_name, cls in L.LAYER_TYPES.items():
            act = QAction(cls.title, self)
            act.setToolTip(cls.description)
            act.triggered.connect(lambda _=False, t=type_name: self.add_layer(t))
            menu.addAction(act)
        self.b_add.setMenu(menu)
        self.b_dup = tool("Duplicate", "copy")
        self.b_del = tool("Delete", "delete")
        self.b_up = tool("", "up", "Move up", show_text=False)
        self.b_down = tool("", "down", "Move down", show_text=False)
        v.addLayout(_h_row(self.b_add, self.b_dup, self.b_del, self.b_up, self.b_down,
                           label("Select the check box of a layer to switch it on.", "caption")))
        self.b_dup.clicked.connect(self.duplicate)
        self.b_del.clicked.connect(self.delete)
        self.b_up.clicked.connect(lambda: self.move(-1))
        self.b_down.clicked.connect(lambda: self.move(1))

        split = QSplitter(Qt.Orientation.Horizontal)
        self.list = QListWidget()
        self.list.setMinimumWidth(230)
        self.list.currentRowChanged.connect(self.show_layer)
        self.list.itemChanged.connect(self._checked)
        split.addWidget(self.list)
        self.editor_host = QWidget()
        self.editor_lay = QVBoxLayout(self.editor_host)
        self.editor_lay.setContentsMargins(0, 0, 0, 0)
        sa = scroll_page(self.editor_host, 1000)
        sa.widget().layout().setContentsMargins(16, 0, 8, 0)
        split.addWidget(sa)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([250, 750])
        v.addWidget(split, 1)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.refresh_status)
        self.editor: QWidget | None = None
        self.links_label = None
        self.names_view = None

    # -- data -----------------------------------------------------------------
    @property
    def lay(self) -> dict:
        return L.normalize_layers(self.studio.spec)

    @property
    def items(self) -> list[dict]:
        return self.lay["items"]

    def changed(self, results_too: bool = True):
        self.studio.mark_dirty(results_too)
        self.timer.start()

    def _grid(self, key, val):
        if self._loading:
            return
        self.lay["grid"][key] = val
        self.update_horizon()
        self.changed()

    def _objective(self, key, val):
        if self._loading:
            return
        self.lay["objective"][key] = val
        self.changed()

    def update_horizon(self):
        gr = self.lay["grid"]
        try:
            hz = float(gr["periods"]) * float(gr["period_h"])
            self.horizon.setText(f"Horizon {hz:g} h ({hz / 24:.3g} d)")
        except (TypeError, ValueError):
            self.horizon.setText("")

    # -- page -----------------------------------------------------------------
    def on_show(self):
        self._loading = True
        gr = self.lay["grid"]
        self.periods.setValue(int(gr.get("periods", 24)))
        self.period_h.setValue(float(gr.get("period_h", 1.0)))
        self.start.setText(str(gr.get("start", "") or ""))
        self.grades.setText(", ".join(gr.get("grades") or []))
        ob = self.lay["objective"]
        self.obj_name.setText(str(ob.get("name") or L.base.TOTAL_OBJECTIVE))
        self.include_base.setChecked(bool(ob.get("include_base", True)))
        self._loading = False
        self.update_horizon()
        self.refresh_list()
        self.refresh_status()

    def item_text(self, it: dict) -> str:
        cls = L.LAYER_TYPES.get(it.get("type"))
        title = it.get("name") or (cls.title if cls else it.get("type"))
        return f"{it.get('id')}    {title}"

    def refresh_list(self, row: int | None = None):
        cur = self.list.currentRow() if row is None else row
        self.list.blockSignals(True)
        self.list.clear()
        for it in self.items:
            li = QListWidgetItem(self.item_text(it), self.list)
            li.setFlags(li.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            li.setCheckState(Qt.CheckState.Checked if it.get("enabled", True) else Qt.CheckState.Unchecked)
            cls = L.LAYER_TYPES.get(it.get("type"))
            li.setToolTip(cls.description if cls else "")
        self.list.blockSignals(False)
        n = len(self.items)
        if n:
            self.list.setCurrentRow(max(0, min(cur if cur is not None and cur >= 0 else 0, n - 1)))
            self.show_layer(self.list.currentRow())
        else:
            self.show_layer(-1)

    def _checked(self, li: QListWidgetItem):
        r = self.list.row(li)
        if 0 <= r < len(self.items):
            on = li.checkState() == Qt.CheckState.Checked
            if bool(self.items[r].get("enabled", True)) != on:
                self.items[r]["enabled"] = on
                if self.items[r] is self.cur and hasattr(self, "e_enabled"):
                    self.e_enabled.setChecked(on)
                self.changed()

    def refresh_status(self):
        infos, err = L.describe(self.studio.spec)
        if err:
            self.info.show_message("critical", "Layer error", err)
        elif not self.items:
            self.info.show_message("info", "No layers", "Click Add layer. The model pages alone then make the model.")
        else:
            on = sum(1 for it in self.items if it.get("enabled", True))
            self.info.show_message("success", "Layers", f"{on} of {len(self.items)} layers are on.")
        self.studio.refresh_names()
        if self.cur is None or self.links_label is None:
            return
        li = next((x for x in infos if x.id == self.cur.get("id")), None)
        if li is None:
            self.links_label.setText("Connections are not available until the error is corrected.")
            self.names_view.setPlainText("")
            return
        lines = []
        for lk in li.links:
            port = L.PORTS.get(lk.port)
            unit = f" [{port.unit}]" if port and port.unit else ""
            if lk.direction == "in":
                lines.append(f"← imports {lk.port}{unit}: " +
                             (f"from layer {lk.partner} ({lk.component})" if lk.partner else "fallback data"))
            else:
                lines.append(f"→ exports {lk.port}{unit} as {lk.component}: " +
                             (f"used by layer {lk.partner}" if lk.partner else "no layer uses it"))
        if not li.enabled:
            lines.insert(0, "The layer is off. The connections show what it connects when it is on.")
        self.links_label.setText("\n".join(lines) or "This layer has no ports.")
        txt = []
        for kind in S.COMPONENT_KINDS:
            names = li.names.get(kind) or []
            if names:
                txt.append(f"{S.KIND_LABEL[kind]}s ({len(names)}): {', '.join(names)}")
        if self.cur.get("type") == "custom":
            tagged = [f"{x['name']}" for kind in S.COMPONENT_KINDS for x in self.studio.spec[kind]
                      if x.get("layer") == self.cur.get("id")]
            txt.append(f"Components on the model pages with this layer ({len(tagged)}): {', '.join(tagged) or 'none'}")
        self.names_view.setPlainText("\n\n".join(txt))

    # -- list actions ---------------------------------------------------------
    def add_layer(self, type_name: str):
        item = L.new_layer(self.studio.spec, type_name)
        grades = self.lay["grid"].get("grades") or []
        cls = L.layer_class(type_name)
        for t in cls.tables:      # give grade columns of the sample rows a real grade
            for i, row in enumerate(item["config"].get(t.key, [])):
                for c in t.columns:
                    if c.kind == "grade" and not row.get(c.key) and grades:
                        row[c.key] = grades[i % len(grades)]
        self.items.append(item)
        self.changed()
        self.refresh_list(len(self.items) - 1)

    def duplicate(self):
        r = self.list.currentRow()
        if r < 0:
            return
        it = copy.deepcopy(self.items[r])
        ids = {str(x["id"]) for x in self.items} | set(S.component_names(self.studio.spec))
        stem = str(it["id"]).rstrip("0123456789") or "layer"
        n = 2
        while f"{stem}{n}" in ids:
            n += 1
        it["id"] = f"{stem}{n}"
        it["enabled"] = False      # two copies would export the same ports
        self.items.insert(r + 1, it)
        self.changed()
        self.refresh_list(r + 1)

    def delete(self):
        r = self.list.currentRow()
        if r < 0:
            return
        it = self.items[r]
        tagged = [x for kind in S.COMPONENT_KINDS for x in self.studio.spec[kind] if x.get("layer") == it["id"]]
        extra = f"\n{len(tagged)} components on the model pages belong to it. They will then be always on." \
            if tagged else ""
        if QMessageBox.question(self, "Delete", f"Delete layer '{it['id']}'?{extra}") \
                != QMessageBox.StandardButton.Yes:
            return
        for x in tagged:
            x["layer"] = ""
        del self.items[r]
        self.changed()
        self.refresh_list(r)

    def move(self, d: int):
        r = self.list.currentRow()
        j = r + d
        if r < 0 or not 0 <= j < len(self.items):
            return
        self.items[r], self.items[j] = self.items[j], self.items[r]
        self.changed(results_too=False)
        self.refresh_list(j)

    # -- editor ---------------------------------------------------------------
    def show_layer(self, row: int):
        if self.editor is not None:
            self.editor.setParent(None)
            self.editor.deleteLater()
            self.editor = None
        self.links_label = None
        self.names_view = None
        has = 0 <= row < len(self.items)
        for b in (self.b_dup, self.b_del, self.b_up, self.b_down):
            b.setEnabled(has)
        if not has:
            self.cur = None
            self.editor = label("There are no layers. Click Add layer.", "secondary")
            self.editor_lay.addWidget(self.editor)
            return
        self.cur = it = self.items[row]
        try:
            cls = L.layer_class(it.get("type"))
        except S.SpecError as exc:
            self.editor = label(str(exc), "error", wrap=True)
            self.editor_lay.addWidget(self.editor)
            return
        # Fill missing settings so that the editor writes into complete rows.
        layer = cls(it)
        it["config"] = layer.cfg
        cfg = it["config"]

        ed = QWidget()
        v = QVBoxLayout(ed)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)
        v.addWidget(label(cls.title, "subtitle"))
        v.addWidget(label(cls.description, "secondary", wrap=True))

        self._loading = True
        form = Form()
        e_id = form.add("id", "Layer id", QLineEdit(str(it.get("id", ""))),
                        "Letters and digits. Built-in layers start their component names with id_.")
        e_name = form.add("name", "Name", QLineEdit(str(it.get("name", ""))))
        self.e_enabled = form.add("enabled", "", ToggleSwitch("Layer is on"))
        self.e_enabled.setChecked(bool(it.get("enabled", True)))
        e_w = QDoubleSpinBox()
        e_w.setRange(-1e6, 1e6)
        e_w.setDecimals(2)
        e_w.setValue(float(it.get("weight", 1.0)))
        form.add("weight", "Weight in the total objective", e_w, "The layer cost is multiplied by this value.")
        v.addWidget(form)
        e_id.editingFinished.connect(lambda w=e_id: self.rename(w.text().strip(), w))
        e_name.textEdited.connect(lambda t: self._set_item("name", t))
        self.e_enabled.clicked.connect(lambda on: self._set_enabled(bool(on)))
        e_w.valueChanged.connect(lambda x: self._set_item("weight", x))

        conn = Card("Connections")
        self.links_label = label("", wrap=True)
        conn.add(self.links_label)
        v.addWidget(conn)

        if cls.fields:
            sc = Card("Settings")
            f2 = Form()
            for fld in cls.fields:
                head = fld.label + (f" ({fld.unit})" if fld.unit else "")
                val = cfg.get(fld.key, fld.default)
                if fld.kind == "bool":
                    w = ToggleSwitch(head)
                    w.setChecked(bool(val))
                    w.clicked.connect(lambda on, k=fld.key: self._set_cfg(k, bool(on)))
                    f2.add(fld.key, "", w, fld.help)
                elif fld.kind in ("float", "int"):
                    w = QDoubleSpinBox() if fld.kind == "float" else QSpinBox()
                    lo = fld.minimum if fld.minimum is not None else -1e12
                    hi = fld.maximum if fld.maximum is not None else 1e12
                    if fld.kind == "float":
                        w.setDecimals(2)
                        w.setRange(lo, hi)
                    else:
                        w.setRange(int(max(lo, -2**31)), int(min(hi, 2**31 - 1)))
                    try:
                        w.setValue(float(val) if fld.kind == "float" else int(val))
                    except (TypeError, ValueError):
                        pass
                    w.valueChanged.connect(lambda x, k=fld.key: self._set_cfg(k, x))
                    f2.add(fld.key, head, w, fld.help)
                elif fld.kind == "expr":
                    w = ExprEdit(2, "", self.studio.names)
                    w.set_text(str(val or ""))
                    w.edited.connect(lambda t, k=fld.key: self._set_cfg(k, t))
                    f2.add(fld.key, head, w, fld.help)
                else:
                    w = QLineEdit(str(val or ""))
                    w.textEdited.connect(lambda t, k=fld.key: self._set_cfg(k, t))
                    f2.add(fld.key, head, w, fld.help)
            sc.add(f2)
            v.addWidget(sc)

        for t in cls.tables:
            card = Card(t.label, t.help)
            table = LayerTable(t, cfg[t.key], self.changed)
            b_add = tool("Add row", "add")
            b_del = tool("Delete rows", "delete")
            b_add.clicked.connect(table.add_row)
            b_del.clicked.connect(table.delete_rows)
            card.add(_h_row(b_add, b_del, label("Ctrl+V pastes a block from Excel.", "caption")))
            card.add(table)
            v.addWidget(card)

        if cls.type_name == "custom":
            v.addWidget(label("To put a component in this layer, open it on the Sets, Parameters, Variables, "
                              "Expressions, Constraints or Objectives page and set its Layer field to "
                              f"'{it.get('id')}'.", "secondary", wrap=True))
        gen = Card("Components of the layer", "The names that the layer adds to the model. Use them in "
                                              "scenarios, the schedule view and your own components.")
        self.names_view = QPlainTextEdit()
        self.names_view.setReadOnly(True)
        self.names_view.setFixedHeight(150)
        gen.add(self.names_view)
        v.addWidget(gen)
        v.addStretch(1)
        self._loading = False
        self.editor = ed
        self.editor_lay.addWidget(ed)
        self.refresh_status()

    def _set_item(self, key, val):
        if self._loading or self.cur is None:
            return
        self.cur[key] = val
        if key == "name":
            self.list.item(self.list.currentRow()).setText(self.item_text(self.cur))
        self.changed()

    def _set_enabled(self, on: bool):
        if self._loading or self.cur is None:
            return
        self.cur["enabled"] = on
        li = self.list.item(self.list.currentRow())
        self.list.blockSignals(True)
        li.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self.list.blockSignals(False)
        self.changed()

    def _set_cfg(self, key, val):
        if self._loading or self.cur is None:
            return
        self.cur["config"][key] = val
        self.changed()

    def rename(self, new_id: str, w: QLineEdit):
        it = self.cur
        if it is None or new_id == it.get("id"):
            return
        others = {str(x["id"]) for x in self.items if x is not it}
        if not L.base._ID_RE.match(new_id) or new_id in others:
            QMessageBox.warning(self, "Layer id", "Use letters and digits, start with a letter, and use an id "
                                                  "that no other layer has.")
            w.setText(str(it.get("id")))
            return
        old = it["id"]
        for kind in S.COMPONENT_KINDS:
            for x in self.studio.spec[kind]:
                if x.get("layer") == old:
                    x["layer"] = new_id
        it["id"] = new_id
        self.list.item(self.list.currentRow()).setText(self.item_text(it))
        if it.get("type") != "custom":
            self.studio.status(f"Layer renamed. Its components now start with {new_id}_. Update scenario "
                               "changes and your own expressions that use the old names.")
        self.changed()
