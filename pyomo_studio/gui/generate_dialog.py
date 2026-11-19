"""Dialog: generate a random crude terminal and refinery model."""
from __future__ import annotations

import random

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout,
                               QSpinBox, QVBoxLayout)

from .. import generate as G
from .widgets import ToggleSwitch, label, tool


class GenerateDialog(QDialog):
    INT_FIELDS = [("vessels", "Vessels", 1, 40), ("berths", "Berths", 1, 10), ("grades", "Crude grades", 1, len(G.CRUDES)),
                  ("tanks_per_grade", "Tanks per grade", 1, 6), ("cdus", "Crude units", 1, 6),
                  ("periods", "Periods", 6, 400)]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generate a random model")
        self.setMinimumWidth(420)
        v = QVBoxLayout(self)
        v.addWidget(label("Makes a crude terminal and refinery model with berth, tank farm and crude unit layers "
                          "and random data. The same seed always gives the same model.", "secondary", wrap=True))
        form = QFormLayout()
        self.preset = QComboBox()
        self.preset.addItems(list(G.PRESETS))
        self.preset.setCurrentText("small")
        form.addRow("Size", self.preset)
        self.seed = QSpinBox()
        self.seed.setRange(0, 2**31 - 1)
        self.seed.setValue(1)
        b_rand = tool("Random", "refresh", "Select a random seed")
        b_rand.clicked.connect(lambda: self.seed.setValue(random.randint(1, 99999)))
        row = QHBoxLayout()
        row.addWidget(self.seed, 1)
        row.addWidget(b_rand)
        form.addRow("Seed", row)
        self.ints: dict[str, QSpinBox] = {}
        for key, text, lo, hi in self.INT_FIELDS:
            sb = QSpinBox()
            sb.setRange(lo, hi)
            self.ints[key] = sb
            form.addRow(text, sb)
        self.period_h = QDoubleSpinBox()
        self.period_h.setRange(0.25, 24)
        self.period_h.setDecimals(2)
        form.addRow("Period length (h)", self.period_h)
        self.tank_modes = ToggleSwitch("Tanks do not receive and send in one period")
        form.addRow("", self.tank_modes)
        self.congestion = self._fraction(0.5)
        form.addRow("Congestion (0 to 1)", self.congestion)
        self.tightness = self._fraction(0.5)
        form.addRow("Tank tightness (0 to 1)", self.tightness)
        self.scenarios = QSpinBox()
        self.scenarios.setRange(0, 50)
        self.scenarios.setSpecialValueText("none (deterministic)")
        form.addRow("Arrival-delay scenarios", self.scenarios)
        v.addLayout(form)
        v.addWidget(label("Congestion moves the vessel arrivals closer together. Tightness reduces the tank space. "
                          "Scenarios make a stochastic model with the berth plan as the first stage.",
                          "caption", wrap=True))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Generate")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.preset.currentTextChanged.connect(self._preset)
        self.scenarios.valueChanged.connect(lambda n: self.scenarios.setValue(2) if n == 1 else None)
        self._preset("small")

    @staticmethod
    def _fraction(val: float) -> QDoubleSpinBox:
        sb = QDoubleSpinBox()
        sb.setRange(0, 1)
        sb.setSingleStep(0.1)
        sb.setDecimals(2)
        sb.setValue(val)
        return sb

    def _preset(self, name: str):
        p = G.PRESETS[name]
        for key, sb in self.ints.items():
            sb.setValue(int(p[key]))
        self.period_h.setValue(float(p["period_h"]))
        self.tank_modes.setChecked(bool(p["tank_modes"]))

    def options(self) -> G.GenOptions:
        o = G.GenOptions(seed=self.seed.value(), preset=self.preset.currentText(),
                         congestion=self.congestion.value(), tightness=self.tightness.value(),
                         scenarios=self.scenarios.value(), period_h=self.period_h.value(),
                         tank_modes=self.tank_modes.isChecked())
        for key, sb in self.ints.items():
            setattr(o, key, sb.value())
        return o
