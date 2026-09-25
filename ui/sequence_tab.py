"""Sequence tab — assemble an ordered suite of tests and run them in succession.

Each step is a (test type + saved config) pair. Run all runs them one after
another via SequenceWorker (reusing the same engine and POWER-Z prompt handling
as single runs), streaming live status and per-step outcomes, then can generate
a combined report.
"""
import os

from PySide6.QtCore import Qt, QThread, QThreadPool
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog,
                               QDialogButtonBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QListWidget, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

import testtypes
from core import config as configmod

from .qt_workers import FnWorker
from .sequence_worker import SequenceWorker


class AddStepDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Add sequence step")
        form = QFormLayout(self)
        self.test_combo = QComboBox()
        for tid, name, _desc in testtypes.list_tests():
            self.test_combo.addItem(name, tid)
        self.cfg_combo = QComboBox()
        self.test_combo.currentIndexChanged.connect(self._rebuild_cfgs)
        self._rebuild_cfgs()
        form.addRow("Test type:", self.test_combo)
        form.addRow("Config:", self.cfg_combo)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _rebuild_cfgs(self):
        self.cfg_combo.clear()
        self.cfg_combo.addItem("(built-in defaults)", None)
        for name, path in configmod.list_configs():
            self.cfg_combo.addItem(name, path)

    def step(self):
        return {
            "test_id": self.test_combo.currentData(),
            "config_path": self.cfg_combo.currentData(),
            "name": self.cfg_combo.currentText(),
        }


class SequenceTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.pool = QThreadPool.globalInstance()
        self._steps = []
        self._thread = None
        self._worker = None
        self._results = None
        self._seq_dir = None

        outer = QVBoxLayout(self)

        # ---- steps builder ---- #
        builder = QGroupBox("Test sequence")
        bl = QHBoxLayout(builder)
        self.steps_list = QListWidget()
        self.steps_list.setSelectionMode(QAbstractItemView.SingleSelection)
        bl.addWidget(self.steps_list, 1)
        col = QVBoxLayout()
        for label, slot in [("Add…", self._add), ("Remove", self._remove),
                            ("Move up", self._up), ("Move down", self._down)]:
            b = QPushButton(label)
            b.clicked.connect(slot)
            col.addWidget(b)
        col.addStretch(1)
        bl.addLayout(col)
        outer.addWidget(builder)

        # ---- run controls ---- #
        bar = QHBoxLayout()
        self.run_btn = QPushButton("Run sequence")
        self.run_btn.clicked.connect(self._run)
        self.abort_btn = QPushButton("Abort")
        self.abort_btn.setEnabled(False)
        self.abort_btn.clicked.connect(self._abort)
        self.step_lbl = QLabel("")
        self.step_lbl.setStyleSheet("font-weight: bold;")
        bar.addWidget(self.run_btn)
        bar.addWidget(self.abort_btn)
        bar.addSpacing(16)
        bar.addWidget(self.step_lbl, 1)
        outer.addLayout(bar)

        self.overall = QProgressBar()
        self.overall.setFormat("Step %v / %m")
        self.step_progress = QProgressBar()
        self.step_progress.setFormat("Point %v / %m")
        outer.addWidget(self.overall)
        outer.addWidget(self.step_progress)

        # ---- per-step summary ---- #
        self.summary = QTableWidget(0, 6)
        self.summary.setHorizontalHeaderLabels(
            ["#", "Test", "Points", "PASS", "FAIL", "Outcome"])
        self.summary.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.summary.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.summary, 1)

        # ---- log + report ---- #
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(4000)
        self.log.setFixedHeight(120)
        outer.addWidget(self.log)

        rep = QHBoxLayout()
        self.report_btn = QPushButton("Generate combined report")
        self.report_btn.setEnabled(False)
        self.report_btn.clicked.connect(self._report)
        self.open_btn = QPushButton("Open sequence folder")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open)
        self.rep_status = QLabel("")
        self.rep_status.setStyleSheet("color: gray;")
        rep.addWidget(self.report_btn)
        rep.addWidget(self.open_btn)
        rep.addWidget(self.rep_status, 1)
        outer.addLayout(rep)

    def refresh(self):
        pass

    # ---- steps builder actions ----------------------------------------- #
    def _add(self):
        dlg = AddStepDialog(self)
        if dlg.exec() == QDialog.Accepted:
            step = dlg.step()
            self._steps.append(step)
            self._redraw_steps()

    def _remove(self):
        r = self.steps_list.currentRow()
        if 0 <= r < len(self._steps):
            self._steps.pop(r)
            self._redraw_steps()

    def _up(self):
        r = self.steps_list.currentRow()
        if r > 0:
            self._steps[r - 1], self._steps[r] = self._steps[r], self._steps[r - 1]
            self._redraw_steps()
            self.steps_list.setCurrentRow(r - 1)

    def _down(self):
        r = self.steps_list.currentRow()
        if 0 <= r < len(self._steps) - 1:
            self._steps[r + 1], self._steps[r] = self._steps[r], self._steps[r + 1]
            self._redraw_steps()
            self.steps_list.setCurrentRow(r + 1)

    def _redraw_steps(self):
        from core.sequence import step_label
        self.steps_list.clear()
        for step in self._steps:
            self.steps_list.addItem(step_label(step))

    # ---- run / abort ---------------------------------------------------- #
    def _run(self):
        if self._thread is not None:
            return
        if not self._steps:
            QMessageBox.information(self, "Empty sequence", "Add at least one step.")
            return

        self.summary.setRowCount(0)
        self.log.clear()
        self.overall.setMaximum(len(self._steps))
        self.overall.setValue(0)
        self.step_progress.setValue(0)
        self.report_btn.setEnabled(False)
        self.open_btn.setEnabled(False)
        self.rep_status.setText("")

        self._worker = SequenceWorker(list(self._steps), self.win.simulate)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.step_started.connect(self._on_step_started)
        self._worker.point_done.connect(self._on_point_done)
        self._worker.status.connect(self._on_status)
        self._worker.screenshot.connect(lambda p: None)
        self._worker.need_prompt.connect(self._on_need_prompt)
        self._worker.step_finished.connect(self._on_step_finished)
        self._worker.sequence_finished.connect(self._on_sequence_finished)

        self.run_btn.setEnabled(False)
        self.abort_btn.setEnabled(True)
        self._thread.start()

    def _abort(self):
        if self._worker:
            self._worker.request_abort()
            self._on_status("Abort requested — finishing current point safely…")
            self.abort_btn.setEnabled(False)

    # ---- worker signals ------------------------------------------------- #
    def _on_step_started(self, index, name, total):
        self.step_lbl.setText(f"Step {index + 1}: {name}")
        self.step_progress.setMaximum(max(total, 1))
        self.step_progress.setValue(0)

    def _on_point_done(self, step_index, point_index, row):
        self.step_progress.setValue(self.step_progress.value() + 1)

    def _on_status(self, message):
        self.log.appendPlainText(message)
        self.win.status(message)

    def _on_need_prompt(self, message):
        box = QMessageBox(self)
        box.setWindowTitle("Operator action required")
        box.setIcon(QMessageBox.Information)
        box.setText(message)
        cont = box.addButton("Continue", QMessageBox.AcceptRole)
        box.addButton("Abort run", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is cont:
            self._worker.resolve_prompt()
        else:
            self._worker.request_abort()

    def _on_step_finished(self, index, result):
        s = result.summary
        if result.error:
            outcome = "ERROR"
        elif result.aborted:
            outcome = "ABORTED"
        elif s["fail"] == 0:
            outcome = "PASS"
        else:
            outcome = "FAIL"
        r = self.summary.rowCount()
        self.summary.insertRow(r)
        vals = [str(index + 1), self.step_lbl.text().split(": ", 1)[-1],
                str(s["total"]), str(s["pass"]), str(s["fail"]), outcome]
        for c, v in enumerate(vals):
            item = QTableWidgetItem(v)
            if c == 5:
                item.setBackground(_outcome_color(outcome))
                item.setTextAlignment(Qt.AlignCenter)
            self.summary.setItem(r, c, item)
        self.overall.setValue(self.overall.value() + 1)

    def _on_sequence_finished(self, results):
        self.abort_btn.setEnabled(False)
        self.run_btn.setEnabled(True)
        self._results = results
        self._seq_dir = (os.path.dirname(results[0]["result"].run_dir)
                         if results else None)
        passed = sum(1 for st in results if st["result"].summary["fail"] == 0
                     and not st["result"].error and not st["result"].aborted)
        self._on_status(f"Sequence complete: {passed}/{len(results)} steps passed.")
        self.step_lbl.setText("Done.")
        if results:
            self.report_btn.setEnabled(True)
            self.open_btn.setEnabled(True)

        self._thread.quit()
        self._thread.wait()
        self._worker.deleteLater()
        self._thread.deleteLater()
        self._worker = None
        self._thread = None

    # ---- combined report ------------------------------------------------ #
    def _report(self):
        if not self._results or not self._seq_dir:
            return
        from reporting.sequence import generate_sequence_reports
        self.report_btn.setEnabled(False)
        self.rep_status.setText("Generating…")
        worker = FnWorker(generate_sequence_reports, self._seq_dir, self._results)
        worker.signals.result.connect(self._on_report_done)
        worker.signals.error.connect(self._on_report_err)
        self.pool.start(worker)

    def _on_report_done(self, paths):
        self.report_btn.setEnabled(True)
        self.rep_status.setText(f"Wrote {os.path.basename(paths.get('summary', ''))} "
                                f"+ per-step reports.")

    def _on_report_err(self, msg):
        self.report_btn.setEnabled(True)
        self.rep_status.setText("")
        QMessageBox.critical(self, "Report failed", msg)

    def _open(self):
        if self._seq_dir and hasattr(os, "startfile"):
            try:
                os.startfile(self._seq_dir)  # noqa: S606
            except OSError as e:
                QMessageBox.warning(self, "Could not open folder", str(e))


def _outcome_color(outcome):
    from PySide6.QtGui import QColor
    return {
        "PASS": QColor(198, 239, 206),
        "FAIL": QColor(255, 199, 206),
    }.get(outcome, QColor(255, 235, 156))
