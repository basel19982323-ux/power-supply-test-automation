"""Run tab — start/abort, live progress, results table, waveform preview, log."""
import os

from PySide6.QtCore import QEvent, Qt, QThread
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QGroupBox, QHBoxLayout, QLabel,
                               QMessageBox, QPlainTextEdit, QProgressBar,
                               QPushButton, QScrollArea, QSlider, QSplitter,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from core.verdict import counts_text, overall, result_color, summarize

from .run_worker import RunWorker


def _qcolor(result):
    return QColor("#" + result_color(result))


class RunTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self._thread = None
        self._worker = None
        self._cols = []
        self._rows = []           # rows shown so far (for the live counts)
        self._current_pix = None
        self._current_path = None
        self._fit = True          # fit-to-panel vs. manual zoom
        self._zoom = 1.0

        outer = QVBoxLayout(self)

        # ---- control bar ---- #
        bar = QHBoxLayout()
        self.start_btn = QPushButton("Start run")
        self.start_btn.clicked.connect(self._start)
        self.abort_btn = QPushButton("Abort")
        self.abort_btn.setEnabled(False)
        self.abort_btn.clicked.connect(self._abort)
        self.mode_lbl = QLabel()
        self.mode_lbl.setStyleSheet("font-weight: bold;")
        bar.addWidget(self.start_btn)
        bar.addWidget(self.abort_btn)
        bar.addSpacing(16)
        bar.addWidget(self.mode_lbl)
        bar.addStretch(1)
        self.counts_lbl = QLabel("")
        bar.addWidget(self.counts_lbl)
        outer.addLayout(bar)

        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        outer.addWidget(self.progress)

        # ---- main split: results table | waveform preview (draggable divider) ---- #
        self.split = QSplitter(Qt.Horizontal)
        self.table = QTableWidget(0, 0)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.split.addWidget(self.table)

        preview_box = QGroupBox("Latest waveform")
        pv = QVBoxLayout(preview_box)

        zbar = QHBoxLayout()
        zbar.addWidget(QLabel("Zoom"))
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(25, 400)      # percent
        self.zoom_slider.setValue(100)
        self.zoom_slider.setToolTip("Zoom the waveform (25–400%)")
        self.zoom_slider.valueChanged.connect(self._on_zoom_slider)
        self.zoom_pct = QLabel("Fit")
        self.zoom_pct.setMinimumWidth(40)
        self.zoom_pct.setAlignment(Qt.AlignCenter)
        self.fit_btn = QPushButton("Fit")
        self.fit_btn.setToolTip("Scale the waveform to fit the panel")
        self.fit_btn.clicked.connect(self._on_fit)
        zbar.addWidget(self.zoom_slider, 1)
        zbar.addWidget(self.zoom_pct)
        zbar.addWidget(self.fit_btn)
        pv.addLayout(zbar)

        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(False)
        self.preview_scroll.setAlignment(Qt.AlignCenter)
        self.preview_scroll.viewport().installEventFilter(self)   # re-fit on resize
        self.preview = QLabel("No capture yet.")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("color: gray;")
        self.preview.setToolTip("Double-click to open the full-size image")
        self.preview.installEventFilter(self)                     # double-click to open
        self.preview_scroll.setWidget(self.preview)
        pv.addWidget(self.preview_scroll, 1)

        self.split.addWidget(preview_box)
        self.split.setStretchFactor(0, 3)
        self.split.setStretchFactor(1, 4)
        self.split.setSizes([520, 620])
        outer.addWidget(self.split, 1)

        # ---- log ---- #
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.setFixedHeight(150)
        outer.addWidget(self.log)

    def refresh(self):
        self.mode_lbl.setText("SIMULATION" if self.win.simulate else "LIVE HARDWARE")
        self.mode_lbl.setStyleSheet(
            "font-weight: bold; color: %s;" % ("#0a7" if self.win.simulate else "#b60"))

    # ---- start / abort -------------------------------------------------- #
    def _start(self):
        if self._thread is not None:
            return
        if not self.win.simulate:
            addrs = self.win.config.get("instruments") or {}
            roles = [r for r in self.win.test.required_instruments if r != "powerz"]
            missing = [r for r in roles if not addrs.get(r)]
            if missing:
                QMessageBox.warning(
                    self, "Missing instrument addresses",
                    "Set VISA addresses for: " + ", ".join(missing) +
                    "\n\nor enable Simulation mode on the Instruments tab.")
                return
            if any("192.168.1." in str(addrs.get(r, "")) for r in roles):
                ret = QMessageBox.question(
                    self, "Example addresses detected",
                    "The instrument addresses look like the example placeholders "
                    "(192.168.1.x) — a LIVE run will fail with VI_ERROR_RSRC_NFOUND "
                    "because nothing is there.\n\n"
                    "To run without hardware:\n"
                    "  • turn ON Simulation mode (Instruments tab), or\n"
                    "  • click 'Use fake bench' on the Instruments tab (with "
                    "tools/fake_bench.py running).\n\n"
                    "Continue with a LIVE run against these addresses anyway?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if ret != QMessageBox.Yes:
                    return

        self._reset_view()
        self._worker = RunWorker(self.win.test, self.win.config, self.win.simulate)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.started_run.connect(self._on_started)
        self._worker.status.connect(self._on_status)
        self._worker.point_done.connect(self._on_point_done)
        self._worker.screenshot.connect(self._on_screenshot)
        self._worker.need_prompt.connect(self._on_need_prompt)
        self._worker.finished_run.connect(self._on_finished)

        self.start_btn.setEnabled(False)
        self.abort_btn.setEnabled(True)
        self._thread.start()

    def _abort(self):
        if self._worker:
            self._worker.request_abort()
            self._on_status("Abort requested — finishing current point safely…")
            self.abort_btn.setEnabled(False)

    # ---- worker signal handlers ---------------------------------------- #
    def _on_started(self, total):
        self.progress.setMaximum(total)
        self.progress.setValue(0)
        self._on_status(f"Starting {total} test points "
                        f"({'simulation' if self.win.simulate else 'live'}).")

    def _on_status(self, message):
        self.log.appendPlainText(message)
        self.win.status(message)

    def _on_point_done(self, index, row):
        r = self.table.rowCount()
        self.table.insertRow(r)
        for c, col in enumerate(self._cols):
            value = row.get(col.key, "")
            if col.kind == "number" and value != "":
                try:
                    text = f"{float(value):.{col.digits}f}"
                except (TypeError, ValueError):
                    text = str(value)
            else:
                text = str(value)
            item = QTableWidgetItem(text)
            if col.kind == "result":
                item.setBackground(_qcolor(value))
                item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(r, c, item)
        self.table.scrollToBottom()

        self._rows.append(row)
        self._update_counts()
        self.progress.setValue(self.progress.value() + 1)

    def _on_screenshot(self, path):
        pix = QPixmap(path)
        if pix.isNull():
            return
        self._current_pix = pix
        self._current_path = path
        self._render_preview()

    # ---- waveform preview zoom ----------------------------------------- #
    def _on_zoom_slider(self, value):
        self._fit = False
        self._zoom = value / 100.0
        self._render_preview()

    def _on_fit(self):
        self._fit = True
        self._render_preview()

    def _render_preview(self):
        if self._current_pix is None or self._current_pix.isNull():
            return
        if self._fit:
            vp = self.preview_scroll.viewport().size()
            target = self._current_pix.scaled(
                max(vp.width() - 4, 32), max(vp.height() - 4, 32),
                Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.zoom_pct.setText("Fit")
        else:
            w = int(self._current_pix.width() * self._zoom)
            h = int(self._current_pix.height() * self._zoom)
            target = self._current_pix.scaled(
                w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.zoom_pct.setText(f"{int(self._zoom * 100)}%")
        self.preview.setPixmap(target)
        self.preview.resize(target.size())

    def eventFilter(self, obj, event):
        if (obj is self.preview_scroll.viewport()
                and event.type() == QEvent.Resize and self._fit):
            self._render_preview()
        elif (obj is self.preview
                and event.type() == QEvent.MouseButtonDblClick
                and self._current_path and hasattr(os, "startfile")):
            try:
                os.startfile(self._current_path)  # noqa: S606 (Windows, intended)
            except OSError:
                pass
        return super().eventFilter(obj, event)

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

    def _on_finished(self, result):
        self.abort_btn.setEnabled(False)
        self.start_btn.setEnabled(True)
        self.win.last_run = result
        s = result.summary
        if result.error:
            self._on_status(f"Run ended with error: {result.error}")
            msg = result.error
            if any(k in msg for k in ("RSRC_NFOUND", "not present", "VI_ERROR", "timed out")):
                msg += ("\n\nThe app couldn't reach an instrument at its configured "
                        "VISA address. Options:\n"
                        "  • Check the addresses on the Instruments tab.\n"
                        "  • Turn ON Simulation mode to run with no hardware.\n"
                        "  • Start tools/fake_bench.py and click 'Use fake bench' on "
                        "the Instruments tab (Simulation OFF).")
            QMessageBox.critical(self, "Run stopped", msg)
        elif result.aborted:
            self._on_status("Run aborted. Partial results saved.")
        self._on_status(f"Done: {counts_text(s)}. Overall result: {result.overall}")
        self._update_counts(result.overall)
        self._on_status(f"Output folder: {result.run_dir}")
        if result.warnings:                    # safety first: AC/load not confirmed off
            QMessageBox.warning(self, "Bench may still be ON", "\n\n".join(result.warnings))

        self._thread.quit()
        self._thread.wait()
        self._worker.deleteLater()
        self._thread.deleteLater()
        self._worker = None
        self._thread = None

        # let the Report tab pick up the new run
        self.win.report_tab.refresh()

    # ---- helpers -------------------------------------------------------- #
    def _reset_view(self):
        self.refresh()
        self._cols = list(self.win.test.result_columns)
        self.table.clear()
        self.table.setRowCount(0)
        self.table.setColumnCount(len(self._cols))
        self.table.setHorizontalHeaderLabels([c.label for c in self._cols])
        self.table.horizontalHeader().setStretchLastSection(True)
        self._rows = []
        self._update_counts()
        self.progress.setValue(0)
        self.log.clear()
        self._current_pix = None
        self._current_path = None
        self.preview.setPixmap(QPixmap())
        self.preview.setText("No capture yet.")
        self.preview.adjustSize()

    def _update_counts(self, final=None):
        s = summarize(self._rows)
        text = (f"PASS {s['pass']}   FAIL {s['fail']}   ERROR {s['error']}   "
                f"NOT RUN {s['not_run']}")
        if final or self._rows:
            text += f"   |   Overall: {final or overall(self._rows)}"
        self.counts_lbl.setText(text)
