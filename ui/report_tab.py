"""Report tab — generate Excel/PPTX from the latest (or a chosen) run."""
import os

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFileDialog,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .qt_workers import FnWorker


class ReportTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.pool = QThreadPool.globalInstance()
        self._run_dir = None
        self._rows = None

        outer = QVBoxLayout(self)

        top = QHBoxLayout()
        self.summary = QLabel("No run yet — run a test on the Run tab.")
        self.summary.setWordWrap(True)
        browse_prev = QPushButton("Open a previous run…")
        browse_prev.clicked.connect(self._pick_previous)
        top.addWidget(self.summary, 1)
        top.addWidget(browse_prev)
        outer.addLayout(top)

        # results preview
        self.table = QTableWidget(0, 0)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        outer.addWidget(self.table, 1)

        # options
        opts = QGroupBox("Report options")
        ov = QVBoxLayout(opts)
        fmt = QHBoxLayout()
        self.excel_chk = QCheckBox("Excel (.xlsx)")
        self.excel_chk.setChecked(True)
        self.pptx_chk = QCheckBox("PowerPoint (.pptx)")
        self.pptx_chk.setChecked(True)
        fmt.addWidget(self.excel_chk)
        fmt.addWidget(self.pptx_chk)
        fmt.addStretch(1)
        ov.addLayout(fmt)

        self.tpl_chk = QCheckBox("Use company template (otherwise built-in layout)")
        self.tpl_chk.toggled.connect(self._toggle_tpl)
        ov.addWidget(self.tpl_chk)
        self._xlsx_tpl = self._file_row(ov, "Excel template:")
        self._map_tpl = self._file_row(ov, "Excel mapping:")
        self._pptx_tpl = self._file_row(ov, "PPTX template:")
        self._toggle_tpl(False)
        outer.addWidget(opts)

        # actions
        act = QHBoxLayout()
        self.gen_btn = QPushButton("Generate report")
        self.gen_btn.clicked.connect(self._generate)
        self.open_btn = QPushButton("Open output folder")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_folder)
        self.gen_status = QLabel("")
        self.gen_status.setStyleSheet("color: gray;")
        act.addWidget(self.gen_btn)
        act.addWidget(self.open_btn)
        act.addWidget(self.gen_status, 1)
        outer.addLayout(act)

    # ---- template picker rows ------------------------------------------ #
    def _file_row(self, parent_layout, label):
        row = QHBoxLayout()
        edit = QLineEdit()
        edit.setReadOnly(True)
        btn = QPushButton("Browse…")

        def browse():
            filt = ("Excel (*.xlsx)" if "Excel template" in label else
                    "YAML (*.yaml *.yml)" if "mapping" in label else
                    "PowerPoint (*.pptx)")
            start = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                 "reporting", "templates")
            path, _ = QFileDialog.getOpenFileName(self, label, start, filt)
            if path:
                edit.setText(path)

        btn.clicked.connect(browse)
        row.addWidget(QLabel(label))
        row.addWidget(edit, 1)
        row.addWidget(btn)
        parent_layout.addLayout(row)
        return {"edit": edit, "btn": btn}

    def _toggle_tpl(self, on):
        for slot in (self._xlsx_tpl, self._map_tpl, self._pptx_tpl):
            slot["edit"].setEnabled(on)
            slot["btn"].setEnabled(on)

    # ---- refresh -------------------------------------------------------- #
    def refresh(self):
        if self.win.last_run is not None:
            self._set_run(self.win.last_run.run_dir, self.win.last_run.rows)

    def _set_run(self, run_dir, rows):
        self._run_dir = run_dir
        self._rows = rows
        s = self.win.test.summarize(rows)
        self.summary.setText(
            f"Run: {run_dir}\n{s['pass']} PASS / {s['fail']} FAIL of {s['total']} points.")
        self.open_btn.setEnabled(True)

        cols = self.win.test.result_columns
        self.table.clear()
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels([c.label for c in cols])
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, col in enumerate(cols):
                item = QTableWidgetItem(str(row.get(col.key, "")))
                if col.kind == "result":
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, c, item)
        self.table.horizontalHeader().setStretchLastSection(True)

    def _pick_previous(self):
        start = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")
        run_dir = QFileDialog.getExistingDirectory(self, "Select a run folder", start)
        if not run_dir:
            return
        csv_path = os.path.join(run_dir, "results.csv")
        if not os.path.exists(csv_path):
            QMessageBox.warning(self, "Not a run folder",
                                "No results.csv found in that folder.")
            return
        from core.results import read_csv
        self._set_run(run_dir, read_csv(csv_path))

    # ---- generate ------------------------------------------------------- #
    def _generate(self):
        if not self._run_dir or not self._rows:
            QMessageBox.information(self, "Nothing to report", "Run a test first.")
            return

        mapping = None
        template_excel = template_pptx = None
        if self.tpl_chk.isChecked():
            template_excel = self._xlsx_tpl["edit"].text() or None
            template_pptx = self._pptx_tpl["edit"].text() or None
            map_path = self._map_tpl["edit"].text()
            if map_path:
                import yaml
                with open(map_path, encoding="utf-8") as f:
                    mapping = yaml.safe_load(f)

        import reporting
        self.gen_btn.setEnabled(False)
        self.gen_status.setText("Generating…")
        worker = FnWorker(
            reporting.generate, self._run_dir, self.win.test, self.win.config,
            rows=self._rows, excel=self.excel_chk.isChecked(),
            pptx=self.pptx_chk.isChecked(),
            template_excel=template_excel, template_pptx=template_pptx,
            mapping=mapping)
        worker.signals.result.connect(self._on_generated)
        worker.signals.error.connect(self._on_gen_error)
        self.pool.start(worker)

    def _on_generated(self, paths):
        self.gen_btn.setEnabled(True)
        names = ", ".join(os.path.basename(p) for p in paths.values())
        self.gen_status.setText(f"Wrote: {names}")
        self.open_btn.setEnabled(True)

    def _on_gen_error(self, msg):
        self.gen_btn.setEnabled(True)
        self.gen_status.setText("")
        QMessageBox.critical(self, "Report failed", msg)

    def _open_folder(self):
        if self._run_dir and hasattr(os, "startfile"):
            try:
                os.startfile(self._run_dir)  # noqa: S606 (Windows-only, intended)
            except OSError as e:
                QMessageBox.warning(self, "Could not open folder", str(e))
