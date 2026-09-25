"""Setup tab — a generic config editor driven by the test's config_schema().

The active TestType returns a list of Sections (tables and field groups); this
tab renders them into editable widgets and writes every change straight back to
win.config. Because it is schema-driven, a new test type gets a full editor for
free — no code here changes. Save/Load persist named configs as YAML.
"""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QScrollArea, QSpinBox,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from core import config as configmod


class SetupTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win

        outer = QVBoxLayout(self)

        # toolbar
        bar = QHBoxLayout()
        self.title = QLabel()
        self.title.setStyleSheet("font-weight: bold;")
        save_btn = QPushButton("Save config…")
        load_btn = QPushButton("Load config…")
        reset_btn = QPushButton("Reset to defaults")
        save_btn.clicked.connect(self._save)
        load_btn.clicked.connect(self._load)
        reset_btn.clicked.connect(self._reset)
        bar.addWidget(self.title, 1)
        bar.addWidget(load_btn)
        bar.addWidget(save_btn)
        bar.addWidget(reset_btn)
        outer.addLayout(bar)

        # scrollable body that holds the generated sections
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.scroll.setWidget(self.body)
        outer.addWidget(self.scroll, 1)

    # ---- (re)build the whole editor from the current test's schema ------ #
    def refresh(self):
        self.title.setText(f"{self.win.test.name} — configuration")
        # clear existing section widgets
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        for section in self.win.test.config_schema():
            if section.kind == "table":
                self.body_layout.addWidget(self._table_section(section))
            elif section.kind == "group":
                self.body_layout.addWidget(self._group_section(section))

        if getattr(self.win.test, "wants_datasheet", False) and self.win.test.datasheet_field:
            self.body_layout.addWidget(self._datasheet_box())
        self.body_layout.addStretch(1)

    # ---- datasheet assist (fills a rating field from a MOSFET PDF) ------- #
    def _datasheet_box(self):
        box = QGroupBox("Datasheet assist")
        h = QHBoxLayout(box)
        btn = QPushButton("Load FET VDS rating from datasheet (PDF)…")
        btn.clicked.connect(self._load_datasheet)
        self._ds_status = QLabel("")
        self._ds_status.setStyleSheet("color: gray;")
        h.addWidget(btn)
        h.addWidget(self._ds_status, 1)
        return box

    def _load_datasheet(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select MOSFET datasheet", "", "PDF files (*.pdf)")
        if not path:
            return
        try:
            from core.datasheet import extract_vds_rating
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                candidates = extract_vds_rating(path)
            finally:
                QApplication.restoreOverrideCursor()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Datasheet read failed", str(e))
            return
        if not candidates:
            QMessageBox.information(
                self, "No rating found",
                "Couldn't find a VDS rating automatically — please type it into the "
                "'FET VDS rating' field.")
            return
        items = [f"{c['value']:.0f} V   —   {c['context']}" for c in candidates]
        choice, ok = QInputDialog.getItem(
            self, "Confirm VDS rating",
            "Select the FET VDS rating (verify against the Absolute Maximum Ratings):",
            items, 0, False)
        if not ok:
            return
        value = candidates[items.index(choice)]["value"]
        sec_key, field_key = self.win.test.datasheet_field
        self.win.config.setdefault(sec_key, {})[field_key] = float(value)
        self.win.refresh_all()
        self.win.status(f"FET VDS rating set to {value:.0f} V from datasheet")

    # ---- table section (list of row dicts) ------------------------------ #
    def _table_section(self, section):
        box = QGroupBox(section.title)
        v = QVBoxLayout(box)
        if section.help:
            hint = QLabel(section.help)
            hint.setWordWrap(True)
            hint.setStyleSheet("color: gray;")
            v.addWidget(hint)

        rows = self.win.config.setdefault(section.key, [])
        cols = section.columns
        table = QTableWidget(len(rows), len(cols))
        table.setHorizontalHeaderLabels([c.label for c in cols])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)

        table.blockSignals(True)
        for r, row in enumerate(rows):
            for c, col in enumerate(cols):
                table.setItem(r, c, QTableWidgetItem(str(row.get(col.key, ""))))
        table.blockSignals(False)
        table.itemChanged.connect(lambda item, s=section: self._on_cell_changed(s, item))

        v.addWidget(table)

        btns = QHBoxLayout()
        add = QPushButton("Add row")
        rem = QPushButton("Remove selected")
        add.clicked.connect(lambda: self._add_row(section, table))
        rem.clicked.connect(lambda: self._remove_row(section, table))
        btns.addWidget(add)
        btns.addWidget(rem)
        btns.addStretch(1)
        v.addLayout(btns)
        return box

    def _on_cell_changed(self, section, item):
        rows = self.win.config[section.key]
        col = section.columns[item.column()]
        r = item.row()
        if r >= len(rows):
            return
        rows[r][col.key] = _coerce(item.text(), col.kind)

    def _add_row(self, section, table):
        rows = self.win.config[section.key]
        new = {c.key: ("" if c.kind == "text" else 0) for c in section.columns}
        rows.append(new)
        r = table.rowCount()
        table.blockSignals(True)
        table.insertRow(r)
        for c, col in enumerate(section.columns):
            table.setItem(r, c, QTableWidgetItem(str(new[col.key])))
        table.blockSignals(False)

    def _remove_row(self, section, table):
        r = table.currentRow()
        if r < 0:
            return
        rows = self.win.config[section.key]
        if r < len(rows):
            rows.pop(r)
        table.removeRow(r)

    # ---- group section (scalar fields) ---------------------------------- #
    def _group_section(self, section):
        box = QGroupBox(section.title)
        form = QFormLayout(box)
        if section.help:
            hint = QLabel(section.help)
            hint.setWordWrap(True)
            hint.setStyleSheet("color: gray;")
            form.addRow(hint)

        values = self.win.config.setdefault(section.key, {})
        for f in section.fields:
            current = values.get(f.key, f.default)
            widget = self._field_widget(f, current, values)
            form.addRow(f"{f.label}:", widget)
        return box

    def _field_widget(self, field, current, values):
        if field.kind == "int":
            w = QSpinBox()
            w.setRange(0, 1_000_000)
            w.setValue(int(current if current is not None else 0))
            if field.suffix:
                w.setSuffix(f" {field.suffix}")
            w.valueChanged.connect(lambda v, k=field.key: values.__setitem__(k, v))
            return w
        if field.kind == "number":
            w = QDoubleSpinBox()
            w.setRange(0.0, 1_000_000.0)
            val = float(current if current is not None else 0.0)
            small = abs(val) < 10          # times, seconds, factors -> finer steps
            w.setDecimals(4 if small else 2)
            w.setSingleStep(0.01 if small else 1.0)
            w.setValue(val)
            if field.suffix:
                w.setSuffix(f" {field.suffix}")
            w.valueChanged.connect(lambda v, k=field.key: values.__setitem__(k, v))
            return w
        # text
        w = QLineEdit(str(current if current is not None else ""))
        w.textChanged.connect(lambda t, k=field.key: values.__setitem__(k, t))
        return w

    # ---- save / load / reset ------------------------------------------- #
    def _save(self):
        os.makedirs(configmod.CONFIG_DIR, exist_ok=True)
        suggested = os.path.join(configmod.CONFIG_DIR, f"{self.win.test.id}.yaml")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save configuration", suggested, "YAML files (*.yaml *.yml)")
        if not path:
            return
        try:
            configmod.save_config(self.win.config, path)
            self.win.status(f"Saved config -> {path}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Save failed", str(e))

    def _load(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load configuration", configmod.CONFIG_DIR,
            "YAML files (*.yaml *.yml)")
        if not path:
            return
        try:
            self.win.config = configmod.load_config(path)
            self.win.status(f"Loaded config <- {path}")
            self.win.refresh_all()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Load failed", str(e))

    def _reset(self):
        if QMessageBox.question(self, "Reset configuration",
                                "Discard changes and reload defaults?") \
                == QMessageBox.Yes:
            self.win.config = self.win._load_default_config(self.win.test)
            self.win.refresh_all()


def _coerce(text, kind):
    text = text.strip()
    try:
        if kind == "int":
            return int(float(text))
        if kind == "number":
            return float(text)
    except ValueError:
        return text  # leave as-is; runner/plan will surface a clear error if invalid
    return text
