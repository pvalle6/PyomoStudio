"""Fluent 2 widgets for Pyomo Studio.

NavigationView (left rail), NavItem, Card, InfoBar, ToggleSwitch, Form,
ExprEdit with syntax colors, ParamGrid (spreadsheet-style parameter data)
and GanttView (paints the ISA-101 schedule primitives).
"""
from __future__ import annotations

import csv
import io
import itertools
import keyword
import re

from PySide6.QtCore import (QEasingCurve, QPointF, QPropertyAnimation, QRect, QRectF, QSize, Qt,
                            Signal, Property)
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QGuiApplication, QKeySequence,
                           QPainter, QPainterPath, QPen, QPolygonF, QSyntaxHighlighter, QTextCharFormat)
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QFrame, QHBoxLayout, QLabel,
                               QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QTableWidget,
                               QTableWidgetItem, QToolButton, QToolTip, QVBoxLayout, QWidget)

from .. import spec as S
from ..schedule import ISA, Prim, layout
from .theme import Theme, font, icon, mono_font, qcolor


# ---------------------------------------------------------------------------
# Icon binding: icons are re-made when the theme changes
# ---------------------------------------------------------------------------

class Icons:
    _bound: list = []

    @classmethod
    def bind(cls, widget, name: str, token: str = "text", px: int = 16):
        widget.setIcon(icon(name, token, px))
        cls._bound.append((widget, name, token, px))
        return widget

    @classmethod
    def refresh(cls) -> None:
        alive = []
        for w, name, token, px in cls._bound:
            try:
                w.setIcon(icon(name, token, px))
                alive.append((w, name, token, px))
            except RuntimeError:  # widget deleted
                pass
        cls._bound = alive


def repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


def label(text: str = "", role: str | None = None, wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if role:
        lb.setProperty("role", role)
    lb.setWordWrap(wrap)
    if wrap:
        lb.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lb


def button(text: str, glyph: str | None = None, accent: bool = False, tip: str = "") -> QPushButton:
    b = QPushButton(text)
    if glyph:
        Icons.bind(b, glyph, "on_accent" if accent else "text")
    if accent:
        b.setProperty("accent", True)
    if tip:
        b.setToolTip(tip)
    return b


def tool(text: str, glyph: str, tip: str = "", show_text: bool = True) -> QToolButton:
    b = QToolButton()
    b.setText(text)
    Icons.bind(b, glyph)
    b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon if show_text
                         else Qt.ToolButtonStyle.ToolButtonIconOnly)
    b.setToolTip(tip or text)
    b.setAutoRaise(True)
    return b


def divider() -> QFrame:
    f = QFrame()
    f.setProperty("divider", True)
    return f


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

class NavItem(QAbstractButton):
    def __init__(self, glyph: str, text: str, parent=None, checkable: bool = True):
        super().__init__(parent)
        self.glyph = glyph
        self.setText(text)
        self.setCheckable(checkable)
        self.setFixedHeight(36)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setToolTip(text)
        self._hover = False

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def sizeHint(self):
        return QSize(48, 36)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(4, 2, self.width() - 8, self.height() - 4)
        if self.isDown():
            bg = Theme.c("subtle_pressed")
        elif self.isChecked():
            bg = Theme.c("subtle_selected")
        elif self._hover:
            bg = Theme.c("subtle_hover")
        else:
            bg = QColor(0, 0, 0, 0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, 4, 4)
        if self.isChecked():
            p.setBrush(Theme.c("accent"))
            p.drawRoundedRect(QRectF(4, self.height() / 2 - 8, 3, 16), 1.5, 1.5)
        icon(self.glyph).paint(p, QRect(16, (self.height() - 16) // 2, 16, 16))
        if self.width() > 64:
            p.setPen(Theme.c("text"))
            p.setFont(font(14, 600 if self.isChecked() else 400))
            fm = p.fontMetrics()
            txt = fm.elidedText(self.text(), Qt.TextElideMode.ElideRight, self.width() - 60)
            p.drawText(QRectF(48, 0, self.width() - 56, self.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, txt)
        p.end()


class NavigationView(QWidget):
    """Windows 11 NavigationView in Left mode: hamburger, items, footer items."""
    currentChanged = Signal(int)
    COMPACT = 48
    OPEN = 228

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NavRail")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 8)
        lay.setSpacing(2)
        self.toggle = NavItem("nav", "Close navigation", checkable=False)
        self.toggle.clicked.connect(lambda: self.set_expanded(not self.expanded))
        lay.addWidget(self.toggle)
        lay.addSpacing(4)
        self._top = QVBoxLayout()
        self._top.setSpacing(2)
        self._bottom = QVBoxLayout()
        self._bottom.setSpacing(2)
        lay.addLayout(self._top)
        lay.addStretch(1)
        lay.addLayout(self._bottom)
        self.items: list[NavItem] = []
        self.headers: list[QLabel] = []
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.expanded = True
        self.setFixedWidth(self.OPEN)
        self.anim = QPropertyAnimation(self, b"railWidth", self)
        self.anim.setDuration(180)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _get_w(self) -> int:
        return self.width()

    def _set_w(self, w: int) -> None:
        self.setFixedWidth(int(w))

    railWidth = Property(int, _get_w, _set_w)

    def add_header(self, text: str) -> None:
        lb = label(text, "caption")
        lb.setContentsMargins(16, 10, 0, 2)
        self.headers.append(lb)
        self._top.addWidget(lb)

    def add_item(self, glyph: str, text: str, footer: bool = False) -> int:
        it = NavItem(glyph, text)
        idx = len(self.items)
        self.items.append(it)
        self.group.addButton(it, idx)
        it.clicked.connect(lambda _=False, i=idx: self.currentChanged.emit(i))
        (self._bottom if footer else self._top).addWidget(it)
        return idx

    def set_current(self, idx: int, emit: bool = True) -> None:
        self.items[idx].setChecked(True)
        if emit:
            self.currentChanged.emit(idx)

    def set_expanded(self, on: bool) -> None:
        self.expanded = on
        self.toggle.setToolTip("Close navigation" if on else "Open navigation")
        for h in self.headers:
            h.setVisible(on)
        self.anim.stop()
        self.anim.setStartValue(self.width())
        self.anim.setEndValue(self.OPEN if on else self.COMPACT)
        self.anim.start()


# ---------------------------------------------------------------------------
# Surfaces and feedback
# ---------------------------------------------------------------------------

class Card(QFrame):
    def __init__(self, title: str = "", subtitle: str = "", parent=None, spacing: int = 10):
        super().__init__(parent)
        self.setProperty("card", True)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(16, 14, 16, 16)
        self.lay.setSpacing(spacing)
        if title:
            self.lay.addWidget(label(title, "strong"))
        if subtitle:
            self.lay.addWidget(label(subtitle, "secondary", wrap=True))

    def add(self, w):
        if isinstance(w, QWidget):
            self.lay.addWidget(w)
        else:
            self.lay.addLayout(w)
        return w


class InfoBar(QFrame):
    GLYPHS = {"success": ("success", "success"), "caution": ("warning", "caution"),
              "critical": ("error", "critical"), "info": ("info", "info")}

    def __init__(self, closable: bool = True, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 8, 10)
        lay.setSpacing(12)
        self.ic = QLabel()
        self.ic.setFixedSize(16, 16)
        self.title = label("", "strong")
        self.msg = label("", wrap=True)
        self.msg.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lay.addWidget(self.ic, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(self.title, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(self.msg, 1)
        if closable:
            x = tool("", "close", "Close", show_text=False)
            x.clicked.connect(self.hide)
            lay.addWidget(x, 0, Qt.AlignmentFlag.AlignTop)
        self.severity = "info"
        self.hide()

    def show_message(self, severity: str, title: str, message: str) -> None:
        self.severity = severity
        self.setProperty("infobar", severity)
        glyph, token = self.GLYPHS.get(severity, self.GLYPHS["info"])
        self.ic.setPixmap(icon(glyph, token).pixmap(16, 16))
        self.title.setText(title)
        self.msg.setText(message)
        repolish(self)
        self.show()

    def refresh_theme(self) -> None:
        if self.isVisible():
            glyph, token = self.GLYPHS.get(self.severity, self.GLYPHS["info"])
            self.ic.setPixmap(icon(glyph, token).pixmap(16, 16))


class ToggleSwitch(QAbstractButton):
    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setText(text)
        self._hover = False
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self):
        w = 40
        if self.text():
            w += 10 + int(QFontMetricsF(font(14)).horizontalAdvance(self.text())) + 4
        return QSize(w, 24)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(0.5, 2.5, 40, 19)
        enabled = self.isEnabled()
        r = 7 if (self._hover and enabled) else 6
        if self.isChecked():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(Theme.c("accent") if enabled else Theme.c("text_disabled"))
            p.drawRoundedRect(track, 9.5, 9.5)
            p.setBrush(Theme.c("on_accent"))
            p.drawEllipse(QPointF(track.right() - 10, track.center().y()), r, r)
        else:
            p.setPen(QPen(Theme.c("stroke_strong"), 1))
            p.setBrush(Theme.c("ctrl"))
            p.drawRoundedRect(track, 9.5, 9.5)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(Theme.c("text2") if enabled else Theme.c("text_disabled"))
            p.drawEllipse(QPointF(track.left() + 10, track.center().y()), r - 1, r - 1)
        if self.text():
            p.setPen(Theme.c("text") if enabled else Theme.c("text_disabled"))
            p.setFont(font(14))
            p.drawText(QRectF(50, 0, self.width() - 50, self.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
        p.end()


class PageHeader(QWidget):
    def __init__(self, title: str, description: str = "", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 4)
        lay.setSpacing(4)
        self.title = label(title, "title")
        lay.addWidget(self.title)
        if description:
            self.desc = label(description, "secondary", wrap=True)
            lay.addWidget(self.desc)


class Form(QWidget):
    """Vertical form: header text above each field, help or error text below."""

    def __init__(self, parent=None, spacing: int = 14):
        super().__init__(parent)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(spacing)
        self.rows: dict[str, QWidget] = {}
        self.errors: dict[str, QLabel] = {}

    def add(self, key: str, header: str, widget: QWidget, help_text: str = "") -> QWidget:
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        if header:
            v.addWidget(label(header))
        v.addWidget(widget)
        err = label("", "error", wrap=True)
        err.hide()
        v.addWidget(err)
        if help_text:
            v.addWidget(label(help_text, "caption", wrap=True))
        self.lay.addWidget(box)
        self.rows[key] = box
        self.errors[key] = err
        return widget

    def add_widget(self, w: QWidget) -> QWidget:
        self.lay.addWidget(w)
        return w

    def set_error(self, key: str, text: str) -> None:
        lb = self.errors.get(key)
        if lb is None:
            return
        lb.setText(text)
        lb.setVisible(bool(text))

    def show_row(self, key: str, visible: bool) -> None:
        if key in self.rows:
            self.rows[key].setVisible(visible)


def scroll_page(inner: QWidget, max_width: int = 1100) -> QScrollArea:
    """Wrap a page body in a vertical scroll area with Fluent page margins."""
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.Shape.NoFrame)
    host = QWidget()
    host.setObjectName("PageBody")
    h = QHBoxLayout(host)
    h.setContentsMargins(36, 28, 36, 36)
    inner.setMaximumWidth(max_width)
    h.addWidget(inner)
    sa.setWidget(host)
    sa.viewport().setAutoFillBackground(False)
    host.setAutoFillBackground(False)
    return sa


# ---------------------------------------------------------------------------
# Expression editor
# ---------------------------------------------------------------------------

class ExprHighlighter(QSyntaxHighlighter):
    KEYWORDS = {"for", "in", "if", "else", "and", "or", "not", "lambda", "is", "None", "True", "False"}
    FUNCS = {"sum", "quicksum", "value", "which", "num", "min", "max", "abs", "len", "range",
             "exp", "log", "sqrt", "inequality", "sorted", "list", "enumerate", "zip"}
    TOKEN = re.compile(r"[A-Za-z_]\w*|\d+\.?\d*(?:[eE][+-]?\d+)?|#.*$")

    def __init__(self, doc, names_fn=lambda: set()):
        super().__init__(doc)
        self.names_fn = names_fn

    def highlightBlock(self, text: str) -> None:
        names = self.names_fn()
        kw, fn, nm, num, com = (QTextCharFormat() for _ in range(5))
        kw.setForeground(Theme.c("accent_text") if Theme.mode == "light" else Theme.c("accent"))
        fn.setForeground(Theme.c("accent_text") if Theme.mode == "light" else Theme.c("accent"))
        fn.setFontItalic(True)
        nm.setFontWeight(QFont.Weight.DemiBold)
        num.setForeground(Theme.c("text2"))
        com.setForeground(Theme.c("text3"))
        for mt in self.TOKEN.finditer(text):
            tok = mt.group(0)
            fmt = None
            if tok.startswith("#"):
                fmt = com
            elif tok[0].isdigit():
                fmt = num
            elif tok in self.KEYWORDS or keyword.iskeyword(tok):
                fmt = kw
            elif tok in self.FUNCS:
                fmt = fn
            elif tok in names:
                fmt = nm
            if fmt is not None:
                self.setFormat(mt.start(), len(tok), fmt)


class ExprEdit(QPlainTextEdit):
    """Monospace editor for Python/Pyomo expressions."""
    edited = Signal(str)

    def __init__(self, lines: int = 2, placeholder: str = "", names_fn=lambda: set(), parent=None):
        super().__init__(parent)
        self.setProperty("code", True)
        self.setFont(mono_font(13))
        self.setTabChangesFocus(lines <= 4)
        self.setPlaceholderText(placeholder)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        fm = self.fontMetrics()
        self.setFixedHeight(int(fm.lineSpacing() * lines + 18))
        self.hl = ExprHighlighter(self.document(), names_fn)
        self._loading = False
        self._last = ""
        self.textChanged.connect(self._changed)

    def _changed(self):
        # textChanged also fires for format-only changes such as rehighlight()
        # on a theme switch; only a real text change is an edit.
        text = self.toPlainText()
        if text == self._last:
            return
        self._last = text
        if not self._loading:
            self.edited.emit(text)

    def set_text(self, text: str) -> None:
        self._loading = True
        self.setPlainText(text or "")
        self._last = self.toPlainText()
        self._loading = False

    def text(self) -> str:
        return self.toPlainText()


# ---------------------------------------------------------------------------
# Parameter data grid
# ---------------------------------------------------------------------------

class ParamGrid(QTableWidget):
    """Spreadsheet editor for parameter values.

    * 1 index set of 1 position: one value column.
    * 2 index sets of 1 position each: a matrix (rows x columns).
    * anything else: long format (index columns and a value column).
    Paste from Excel with Ctrl+V. Empty cells use the default value.
    """
    changed = Signal()
    MAX_ROWS = 20000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = "none"
        self._loading = False
        self._rows_keys: list = []
        self._cols_keys: list = []
        self.npos = 0
        self.setAlternatingRowColors(True)
        self.itemChanged.connect(self._item_changed)
        self.setMinimumHeight(220)
        self.verticalHeader().setDefaultSectionSize(28)

    def load(self, items: list[S.IndexItem], sets: dict, rows: list) -> str:
        """Fill the grid. Return a message ('' when all is good)."""
        self._loading = True
        self.clear()
        self.setRowCount(0)
        self.setColumnCount(0)
        values = {S.norm_key(tuple(r[:-1])): r[-1] for r in rows if len(r) >= 2}
        msg = ""
        dims = [S.set_dimen(sets.get(it.set_name, [])) for it in items]
        try:
            if len(items) == 1 and dims[0] == 1:
                self.mode = "column"
                els = sets[items[0].set_name]
                self._rows_keys = els
                self.setRowCount(len(els))
                self.setColumnCount(1)
                self.setHorizontalHeaderLabels(["Value"])
                self.setVerticalHeaderLabels([S.format_element(e) for e in els])
                for i, e in enumerate(els):
                    self._set(i, 0, values.get(e))
            elif len(items) == 2 and dims == [1, 1]:
                self.mode = "matrix"
                r_els, c_els = sets[items[0].set_name], sets[items[1].set_name]
                self._rows_keys, self._cols_keys = r_els, c_els
                self.setRowCount(len(r_els))
                self.setColumnCount(len(c_els))
                self.setHorizontalHeaderLabels([S.format_element(e) for e in c_els])
                self.setVerticalHeaderLabels([S.format_element(e) for e in r_els])
                for i, re_ in enumerate(r_els):
                    for j, ce in enumerate(c_els):
                        self._set(i, j, values.get((re_, ce)))
            else:
                self.mode = "long"
                keys = [k for k, _ in itertools.islice(S.iter_index(items, sets), self.MAX_ROWS)]
                self.npos = sum(dims)
                self._rows_keys = keys
                self.setRowCount(len(keys))
                self.setColumnCount(1)
                self.setHorizontalHeaderLabels(["Value"])
                self.setVerticalHeaderLabels([S.format_key(k) for k in keys])
                for i, k in enumerate(keys):
                    self._set(i, 0, values.get(k))
                if len(keys) == self.MAX_ROWS:
                    msg = f"The grid shows the first {self.MAX_ROWS} index values. Use a formula or import a CSV file."
        except (KeyError, S.SpecError) as exc:
            self.mode = "none"
            msg = f"The grid cannot show the index: {exc}"
        self._loading = False
        self.resizeColumnsToContents()
        return msg

    def _set(self, r: int, c: int, val) -> None:
        it = QTableWidgetItem("" if val is None else S.format_element(val))
        it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setItem(r, c, it)

    def _item_changed(self, it: QTableWidgetItem):
        if self._loading:
            return
        txt = it.text().strip()
        ok = txt == "" or isinstance(S.parse_scalar(txt), (int, float))
        it.setBackground(QBrush(qcolor(Theme.t["critical_bg"])) if not ok else QBrush())
        it.setToolTip("" if ok else "Write a number.")
        self.changed.emit()

    def rows(self) -> list:
        out = []

        def num(it):
            if it is None or not it.text().strip():
                return None
            v = S.parse_scalar(it.text())
            return v if isinstance(v, (int, float)) else None
        if self.mode in ("column", "long"):
            for i, k in enumerate(self._rows_keys):
                v = num(self.item(i, 0))
                if v is not None:
                    parts = list(k) if isinstance(k, tuple) else [k]
                    out.append(parts + [v])
        elif self.mode == "matrix":
            for i, rk in enumerate(self._rows_keys):
                for j, ck in enumerate(self._cols_keys):
                    v = num(self.item(i, j))
                    if v is not None:
                        out.append([rk, ck, v])
        return out

    # Clipboard: Excel uses tab-separated rows.
    def keyPressEvent(self, e):
        if e.matches(QKeySequence.StandardKey.Paste):
            self.paste_text(QGuiApplication.clipboard().text())
            return
        if e.matches(QKeySequence.StandardKey.Copy):
            self.copy_selection()
            return
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and not self.state() == QTableWidget.State.EditingState:
            self._loading = True
            for it in self.selectedItems():
                it.setText("")
            self._loading = False
            self.changed.emit()
            return
        super().keyPressEvent(e)

    def paste_text(self, text: str) -> None:
        r0, c0 = max(0, self.currentRow()), max(0, self.currentColumn())
        lines = [ln for ln in text.splitlines() if ln.strip() != ""]
        self._loading = True
        for i, ln in enumerate(lines):
            for j, cell in enumerate(ln.split("\t")):
                r, c = r0 + i, c0 + j
                if r < self.rowCount() and c < self.columnCount():
                    self._set(r, c, S.parse_scalar(cell) if cell.strip() else None)
        self._loading = False
        self.changed.emit()

    def copy_selection(self) -> None:
        rng = self.selectedRanges()
        if not rng:
            return
        r = rng[0]
        lines = []
        for i in range(r.topRow(), r.bottomRow() + 1):
            lines.append("\t".join((self.item(i, j).text() if self.item(i, j) else "")
                                   for j in range(r.leftColumn(), r.rightColumn() + 1)))
        QGuiApplication.clipboard().setText("\n".join(lines))

    def import_csv(self, text: str) -> int:
        """Read CSV in the grid shape (matrix with headers) or long format."""
        rows = [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
        if not rows:
            return 0
        n = 0
        self._loading = True
        if self.mode == "matrix" and len(rows[0]) >= 2:
            head = [S.parse_scalar(c) for c in rows[0][1:]]
            col_of = {k: j for j, k in enumerate(self._cols_keys)}
            row_of = {k: i for i, k in enumerate(self._rows_keys)}
            for r in rows[1:]:
                i = row_of.get(S.parse_scalar(r[0]))
                if i is None:
                    continue
                for h, cell in zip(head, r[1:]):
                    j = col_of.get(h)
                    if j is not None and cell.strip():
                        self._set(i, j, S.parse_scalar(cell))
                        n += 1
        else:
            index_of = {k: i for i, k in enumerate(self._rows_keys)}
            for r in rows:
                if len(r) < 2:
                    continue
                key = S.norm_key(tuple(S.parse_scalar(c) for c in r[:-1]))
                if isinstance(key, tuple) and self.mode == "matrix":
                    i, j = self._rows_keys.index(key[0]) if key[0] in self._rows_keys else None, \
                        self._cols_keys.index(key[1]) if key[1] in self._cols_keys else None
                    if i is not None and j is not None:
                        self._set(i, j, S.parse_scalar(r[-1]))
                        n += 1
                    continue
                i = index_of.get(key)
                val = S.parse_scalar(r[-1])
                if i is not None and isinstance(val, (int, float)):
                    self._set(i, 0, val)
                    n += 1
        self._loading = False
        self.changed.emit()
        return n

    def export_csv(self) -> str:
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        if self.mode == "matrix":
            w.writerow([""] + [S.format_element(c) for c in self._cols_keys])
            for i, rk in enumerate(self._rows_keys):
                w.writerow([S.format_element(rk)] + [(self.item(i, j).text() if self.item(i, j) else "")
                                                      for j in range(self.columnCount())])
        else:
            for r in self.rows():
                w.writerow([S.format_element(x) for x in r])
        return buf.getvalue()


# ---------------------------------------------------------------------------
# Schedule graphic (ISA-101)
# ---------------------------------------------------------------------------

class GanttView(QWidget):
    """Paints the renderer-neutral schedule primitives with QPainter."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.sched = None
        self.zoom = 1.0
        self.avail_width = 1000
        self.prims: list[Prim] = []
        self.title = ""
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

    def set_schedule(self, sched, title: str = "") -> None:
        self.sched = sched
        self.title = title
        self.relayout()

    def set_available_width(self, w: int) -> None:
        self.avail_width = max(480, w)
        self.relayout()

    def set_zoom(self, z: float) -> None:
        self.zoom = max(0.5, min(8.0, z))
        self.relayout()

    def relayout(self) -> None:
        if self.sched is None or not self.sched.tasks:
            self.prims = []
            self.setFixedSize(self.avail_width, 160)
        else:
            self.prims, w, h = layout(self.sched, self.avail_width * self.zoom, title=self.title)
            self.setFixedSize(int(w), int(h))
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.fillRect(self.rect(), QColor(ISA["bg"]))
        if not self.prims:
            p.setPen(QColor(ISA["text_dim"]))
            p.setFont(font(14))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "No schedule. Solve a model that has a schedule view.")
            p.end()
            return
        for pr in self.prims:
            pen = QPen(QColor(pr.stroke), pr.width) if pr.stroke else Qt.PenStyle.NoPen
            if pr.stroke and pr.dash:
                pen.setDashPattern([5 / max(pr.width, 1), 4 / max(pr.width, 1)])
            if pr.kind == "rect":
                p.setPen(pen)
                p.setBrush(QColor(pr.fill) if pr.fill else Qt.BrushStyle.NoBrush)
                p.drawRect(QRectF(pr.x, pr.y, pr.w, pr.h))
            elif pr.kind == "line":
                p.setPen(pen)
                (xa, ya), (xb, yb) = pr.points[0], pr.points[1]
                p.drawLine(QPointF(xa, ya), QPointF(xb, yb))
            elif pr.kind == "poly":
                p.setPen(pen)
                p.setBrush(QColor(pr.fill) if pr.fill else Qt.BrushStyle.NoBrush)
                p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in pr.points]))
            elif pr.kind == "text":
                f = font(int(round(pr.size)), 600 if pr.bold else 400)
                p.setFont(f)
                p.setPen(QColor(pr.color))
                x = pr.x
                if pr.anchor != "start":
                    w = QFontMetricsF(f).horizontalAdvance(pr.text)
                    x -= w / 2 if pr.anchor == "middle" else w
                p.drawText(QPointF(x, pr.y), pr.text)
        p.end()

    def _hit(self, pos) -> Prim | None:
        x, y = pos.x(), pos.y()
        for pr in reversed(self.prims):
            if not pr.tip:
                continue
            if pr.kind == "rect" and pr.x <= x <= pr.x + pr.w and pr.y <= y <= pr.y + pr.h:
                return pr
            if pr.kind == "poly":
                path = QPainterPath()
                path.addPolygon(QPolygonF([QPointF(a, b) for a, b in pr.points]))
                if path.contains(QPointF(x, y)):
                    return pr
        return None

    def mouseMoveEvent(self, e):
        pr = self._hit(e.position())
        if pr:
            QToolTip.showText(e.globalPosition().toPoint(), pr.tip, self)
        else:
            QToolTip.hideText()

    def to_image(self):
        return self.grab()


class GanttScroll(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = GanttView()
        self.setWidget(self.view)
        self.setWidgetResizable(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumHeight(260)
        self.setStyleSheet(f"QScrollArea {{ background: {ISA['bg']}; border-radius: 4px; }}")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.view.set_available_width(self.viewport().width())
