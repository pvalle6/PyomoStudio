"""Tanks page: tank inventory schematic and trends of the last solve."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QSlider, QSpinBox, QSplitter, QVBoxLayout,
                               QWidget)

from .. import inventory as I
from .widgets import PageHeader, PrimScroll, label, tool


class TanksPage(QWidget):
    def __init__(self, studio):
        super().__init__()
        from .pages import Metric, h_row
        self.studio = studio
        self.inv: I.Inventory | None = None
        self.geom: I.TrendGeometry | None = None
        self._width = 1000
        outer = QVBoxLayout(self)
        outer.setContentsMargins(36, 28, 36, 20)
        outer.setSpacing(12)
        outer.addWidget(PageHeader("Tanks", "Tank stock and flows of the last solve as a process graphic (ISA-101). "
                                            "Select a period with the slider, or click the trend. Amber with a 2 is "
                                            "a warning (high level or at heel); red with a 1 is an alarm."))
        self.scenario = QComboBox()
        self.layer = QComboBox()
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(1)
        self.slider.setMinimumWidth(220)
        self.period = QSpinBox()
        self.period.setMinimum(1)
        self.b_prev = tool("", "up", "Previous period", show_text=False)
        self.b_next = tool("", "down", "Next period", show_text=False)
        self.b_play = tool("Play", "solve", "Step through the periods")
        self.b_play.setCheckable(True)
        self.b_svg = tool("Export SVG", "export")
        self.b_csv = tool("Export CSV", "export")
        outer.addLayout(h_row(label("Scenario"), self.scenario, label("Tank farm"), self.layer, label("Period"),
                              self.slider, self.period, self.b_prev, self.b_next, self.b_play, None,
                              self.b_svg, self.b_csv, stretch_end=False))
        kg = QHBoxLayout()
        kg.setSpacing(12)
        self.k_tanks, self.k_time = Metric("Tanks"), Metric("Selected period")
        self.k_warn, self.k_alarm = Metric("Warnings (tank-periods)"), Metric("Alarms")
        for m in (self.k_tanks, self.k_time, self.k_warn, self.k_alarm):
            kg.addWidget(m)
        outer.addLayout(kg)
        split = QSplitter(Qt.Orientation.Vertical)
        self.schematic = PrimScroll("No tank data. Add a Tank farm layer on the Layers page, then solve.",
                                    self._resized)
        self.trend = PrimScroll("", None)
        split.addWidget(self.schematic)
        split.addWidget(self.trend)
        split.setSizes([560, 300])
        outer.addWidget(split, 1)
        self.msg = label("", "secondary", wrap=True)
        outer.addWidget(self.msg)

        self.timer = QTimer(self)
        self.timer.setInterval(450)
        self.timer.timeout.connect(self._tick)
        self.scenario.currentIndexChanged.connect(lambda _i: self.compute())
        self.layer.currentIndexChanged.connect(lambda _i: self.compute())
        self.slider.valueChanged.connect(self._period_changed)
        self.period.valueChanged.connect(self._period_changed)
        self.b_prev.clicked.connect(lambda: self.slider.setValue(self.slider.value() - 1))
        self.b_next.clicked.connect(lambda: self.slider.setValue(self.slider.value() + 1))
        self.b_play.toggled.connect(self._play)
        self.trend.view.clicked.connect(self._trend_clicked)
        self.b_svg.clicked.connect(self.export_svg)
        self.b_csv.clicked.connect(self.export_csv)

    # -- data -------------------------------------------------------------------
    def load(self):
        """Called when the result changes."""
        res = self.studio.result
        spec = self.studio.result_spec or {}
        for cb, items in ((self.scenario, [sc.name for sc in res.scenarios] if res is not None else []),
                          (self.layer, I.tank_layers(spec) if res is not None else [])):
            cur = cb.currentText()
            cb.blockSignals(True)
            cb.clear()
            cb.addItems(items)
            if cur in items:
                cb.setCurrentText(cur)
            cb.blockSignals(False)
        self.scenario.setEnabled(res is not None and res.stochastic)
        self.layer.setEnabled(self.layer.count() > 1)
        self.compute()

    def on_show(self):
        self._resized(self.schematic.viewport().width())

    def compute(self):
        self.inv = None
        res = self.studio.result
        msg = ""
        if res is None:
            msg = "Solve a model that has a Tank farm layer."
        elif not res.ok:
            msg = "The last solve has no solution."
        elif not self.layer.count():
            msg = "The last solve has no enabled Tank farm layer."
        else:
            try:
                self.inv = I.compute(self.studio.result_spec, res, self.scenario.currentText() or None,
                                     self.layer.currentText() or None)
            except (I.InventoryError, KeyError) as exc:
                msg = f"No tank data: {exc}"
        if self.inv is not None and self.studio.results_stale:
            msg = "The model changed after this solve. Solve again to update the tanks."
        self.msg.setText(msg)
        for w in (self.slider, self.period, self.b_prev, self.b_next, self.b_play, self.b_svg, self.b_csv):
            w.setEnabled(self.inv is not None)
        if self.inv is None:
            self.b_play.setChecked(False)
            self.schematic.view.clear(self._width)
            self.trend.view.clear(self._width)
            for m in (self.k_tanks, self.k_time, self.k_warn, self.k_alarm):
                m.set("-", "")
            return
        n = self.inv.periods
        for w in (self.slider, self.period):
            w.blockSignals(True)
            w.setMaximum(n)
            w.blockSignals(False)
        c = self.inv.counts()
        grades = len(self.inv.grades_used())
        self.k_tanks.set(str(len(self.inv.tanks)), f"{grades} grade{'s' if grades != 1 else ''}")
        self.k_warn.set(str(c["warnings"]), f"of {len(self.inv.tanks) * n} tank-periods")
        self.k_alarm.set(str(c["alarms"]), "outside limits, rejected or short")
        self.redraw()

    def k(self) -> int:
        return self.slider.value()

    def _period_changed(self, k: int):
        for w in (self.slider, self.period):
            if w.value() != k:
                w.blockSignals(True)
                w.setValue(k)
                w.blockSignals(False)
        self.redraw()

    def redraw(self):
        if self.inv is None:
            return
        k = self.k()
        prims, w, h = I.layout_schematic(self.inv, k, max(900, self._width))
        self.schematic.view.set_prims(prims, w, h)
        prims, w, h, self.geom = I.layout_trends(self.inv, k, max(900, self._width))
        self.trend.view.set_prims(prims, w, h)
        text = self.inv.period_text(k)
        self.k_time.set(f"{k} / {self.inv.periods}", text.split(", ", 1)[1] if ", " in text else text)

    def _resized(self, w: int):
        if abs(w - self._width) > 4:
            self._width = w
            self.redraw()

    def _trend_clicked(self, x: float, _y: float):
        if self.geom is not None and self.geom.x0 <= x <= self.geom.x1:
            self.slider.setValue(self.geom.period_at(x))

    def _play(self, on: bool):
        if on:
            if self.slider.value() >= self.slider.maximum():
                self.slider.setValue(1)
            self.timer.start()
        else:
            self.timer.stop()

    def _tick(self):
        if self.slider.value() >= self.slider.maximum():
            self.b_play.setChecked(False)
            return
        self.slider.setValue(self.slider.value() + 1)

    # -- export -------------------------------------------------------------------
    def export_svg(self):
        if self.inv is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export tank schematic",
                                              self.studio.last_dir(f"tanks_period_{self.k()}.svg"), "SVG (*.svg)")
        if path:
            Path(path).write_text(I.schematic_svg(self.inv, self.k()), encoding="utf-8")

    def export_csv(self):
        if self.inv is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export tank inventory", self.studio.last_dir("tanks.csv"),
                                              "CSV (*.csv)")
        if path:
            Path(path).write_text(I.inventory_csv(self.inv), encoding="utf-8")
