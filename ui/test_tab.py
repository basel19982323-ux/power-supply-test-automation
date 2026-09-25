"""Test tab — pick the test type and name the DUT."""
from PySide6.QtWidgets import (QComboBox, QFormLayout, QGroupBox, QLabel, QLineEdit,
                               QVBoxLayout, QWidget)

import testtypes


class TestTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self._building = False

        layout = QVBoxLayout(self)
        box = QGroupBox("Test selection")
        form = QFormLayout(box)

        self.combo = QComboBox()
        for tid, name, _desc in testtypes.list_tests():
            self.combo.addItem(name, tid)
        self.combo.currentIndexChanged.connect(self._on_test_changed)

        self.desc = QLabel()
        self.desc.setWordWrap(True)

        self.dut = QLineEdit()
        self.dut.setPlaceholderText("e.g. DUT-01 — used in filenames and reports")
        self.dut.textChanged.connect(self._on_dut_changed)

        form.addRow("Test type:", self.combo)
        form.addRow("Description:", self.desc)
        form.addRow("DUT name:", self.dut)

        layout.addWidget(box)
        hint = QLabel("Choose a test, then set instrument addresses on the "
                      "Instruments tab (or enable Simulation mode).")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        layout.addWidget(hint)
        layout.addStretch(1)

    def refresh(self):
        self._building = True
        idx = self.combo.findData(self.win.test.id)
        if idx >= 0:
            self.combo.setCurrentIndex(idx)
        self.desc.setText(self.win.test.description)
        self.dut.setText(str(self.win.config.get("dut_name", "")))
        self._building = False

    def _on_test_changed(self):
        if self._building:
            return
        self.win.set_test(self.combo.currentData())

    def _on_dut_changed(self, text):
        if self._building:
            return
        self.win.config["dut_name"] = text
