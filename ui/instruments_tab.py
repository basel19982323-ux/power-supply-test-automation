"""Instruments tab — simulation toggle, VISA addresses per role, scan, test."""
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget)

from .qt_workers import FnWorker

ROLE_LABELS = {
    "ac_source": "AC source",
    "e_load": "Electronic load",
    "scope": "Oscilloscope",
    "powerz": "POWER-Z",
}


class InstrumentsTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.pool = QThreadPool.globalInstance()
        self._addr_widgets = {}   # role -> {"combo","status","test_btn"}
        self._building = False

        outer = QVBoxLayout(self)

        self.sim_chk = QCheckBox(
            "Simulation mode — run with simulated instruments (no hardware needed)")
        self.sim_chk.toggled.connect(self._on_sim_toggled)
        outer.addWidget(self.sim_chk)

        top = QHBoxLayout()
        self.scan_btn = QPushButton("Scan for instruments")
        self.scan_btn.clicked.connect(self._on_scan)
        self.fake_btn = QPushButton("Use fake bench")
        self.fake_btn.setToolTip("Fill localhost socket addresses for tools/fake_bench.py "
                                 "and turn Simulation OFF")
        self.fake_btn.clicked.connect(self._use_fake_bench)
        self.scan_status = QLabel("")
        self.scan_status.setStyleSheet("color: gray;")
        top.addWidget(self.scan_btn)
        top.addWidget(self.fake_btn)
        top.addWidget(self.scan_status, 1)
        outer.addLayout(top)

        self.box = QGroupBox("Instrument connections")
        self.form = QFormLayout(self.box)
        outer.addWidget(self.box)
        outer.addStretch(1)

    # ---- refresh (rebuilds rows: required roles vary by test type) ------- #
    def refresh(self):
        self._building = True
        self.sim_chk.setChecked(self.win.simulate)
        while self.form.rowCount():
            self.form.removeRow(0)
        self._addr_widgets = {}

        for role in self.win.test.required_instruments:
            label = ROLE_LABELS.get(role, role)
            if role == "powerz":
                combo = QComboBox()
                combo.addItems(["manual", "gui"])
                combo.setCurrentText((self.win.config.get("powerz") or {}).get("mode", "manual"))
                combo.currentTextChanged.connect(self._set_powerz_mode)
                self.form.addRow(f"{label} mode:", combo)
            else:
                self.form.addRow(f"{label}:", self._make_addr_row(role))

        self._apply_sim_enabled()
        self._building = False

    def _make_addr_row(self, role):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)

        combo = QComboBox()
        combo.setEditable(True)
        combo.setMinimumWidth(320)
        addr = (self.win.config.get("instruments") or {}).get(role, "")
        combo.setEditText(addr or "")
        combo.editTextChanged.connect(lambda t, r=role: self._set_addr(r, t))

        test_btn = QPushButton("Test")
        test_btn.clicked.connect(lambda _=False, r=role: self._on_test_conn(r))

        status = QLabel("")
        status.setStyleSheet("color: gray;")

        h.addWidget(combo, 3)
        h.addWidget(test_btn)
        h.addWidget(status, 2)
        self._addr_widgets[role] = {"combo": combo, "status": status, "test_btn": test_btn}
        return row

    # ---- state writers -------------------------------------------------- #
    def _set_addr(self, role, text):
        if self._building:
            return
        self.win.config.setdefault("instruments", {})[role] = text

    def _set_powerz_mode(self, mode):
        if self._building:
            return
        self.win.config.setdefault("powerz", {})["mode"] = mode

    def _on_sim_toggled(self, checked):
        self.win.simulate = checked
        self._apply_sim_enabled()

    def _apply_sim_enabled(self):
        """In simulation mode, addresses/scan are irrelevant — disable them."""
        live = not self.win.simulate
        self.scan_btn.setEnabled(live)
        for w in self._addr_widgets.values():
            w["combo"].setEnabled(live)
            w["test_btn"].setEnabled(live)
        self.scan_status.setText("" if live else "Simulation mode — no hardware used.")

    # ---- fake bench (localhost sockets) --------------------------------- #
    _FAKE_PORTS = {"ac_source": 5025, "e_load": 5026, "scope": 5027}

    def _use_fake_bench(self):
        instr = self.win.config.setdefault("instruments", {})
        for role in self.win.test.required_instruments:
            if role in self._FAKE_PORTS:
                instr[role] = f"TCPIP0::127.0.0.1::{self._FAKE_PORTS[role]}::SOCKET"
        self.win.simulate = False          # run the real drivers against the fake bench
        self.win.refresh_all()
        self.win.status("Filled fake-bench addresses (Simulation OFF). Make sure "
                        "tools/fake_bench.py is running, then go to Run.")

    # ---- scan ----------------------------------------------------------- #
    def _on_scan(self):
        from core.visa import scan
        self.scan_btn.setEnabled(False)
        self.scan_status.setText("Scanning…")
        worker = FnWorker(scan)
        worker.signals.result.connect(self._on_scan_done)
        worker.signals.error.connect(self._on_scan_error)
        self.pool.start(worker)

    def _on_scan_done(self, found):
        self.scan_btn.setEnabled(True)
        if not found:
            self.scan_status.setText("No VISA instruments found.")
            return
        self.scan_status.setText(f"Found {len(found)} instrument(s) — pick from each dropdown.")
        for w in self._addr_widgets.values():
            combo = w["combo"]
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            for r in found:
                combo.addItem(r["address"])
                combo.setItemData(combo.count() - 1, r["idn"], 3)  # tooltip role
            combo.setEditText(current)
            combo.blockSignals(False)

    def _on_scan_error(self, msg):
        self.scan_btn.setEnabled(True)
        self.scan_status.setText(f"Scan failed: {msg}")

    # ---- per-instrument connection test --------------------------------- #
    def _on_test_conn(self, role):
        from core.visa import identify
        widgets = self._addr_widgets[role]
        addr = widgets["combo"].currentText().strip()
        if not addr:
            widgets["status"].setText("Enter an address first.")
            return
        widgets["status"].setText("Connecting…")
        widgets["test_btn"].setEnabled(False)
        worker = FnWorker(identify, addr)
        worker.signals.result.connect(lambda idn, r=role: self._on_conn_ok(r, idn))
        worker.signals.error.connect(lambda msg, r=role: self._on_conn_err(r, msg))
        self.pool.start(worker)

    def _on_conn_ok(self, role, idn):
        w = self._addr_widgets[role]
        w["test_btn"].setEnabled(True)
        w["status"].setStyleSheet("color: green;")
        w["status"].setText(f"OK: {idn}")

    def _on_conn_err(self, role, msg):
        w = self._addr_widgets[role]
        w["test_btn"].setEnabled(True)
        w["status"].setStyleSheet("color: #b00;")
        w["status"].setText(f"Failed: {msg}")
