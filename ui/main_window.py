"""Main window: the tabbed shell and the single source of truth for app state.

Shared state lives here (self.test / self.config / self.simulate / self.last_run);
every tab holds a reference to the window, reads state in refresh(), and writes
changes straight back. set_test() swaps the active TestType and reloads its
default config, then refreshes all tabs.
"""
import os

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow, QMessageBox, QStatusBar, QTabWidget

import testtypes
from core import config as configmod

from .instruments_tab import InstrumentsTab
from .report_tab import ReportTab
from .run_tab import RunTab
from .sequence_tab import SequenceTab
from .setup_tab import SetupTab
from .test_tab import TestTab


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dynamic Load Test")
        self.resize(1200, 800)

        # ---- shared application state ---- #
        self.test = testtypes.default_test()
        self.config = self._load_default_config(self.test)
        self.simulate = True          # default ON so the app runs with no hardware
        self.last_run = None          # core.runner.RunResult of the most recent run

        # ---- tabbed shell ---- #
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.test_tab = TestTab(self)
        self.instruments_tab = InstrumentsTab(self)
        self.setup_tab = SetupTab(self)
        self.run_tab = RunTab(self)
        self.report_tab = ReportTab(self)
        self.sequence_tab = SequenceTab(self)
        self.tabs.addTab(self.test_tab, "1. Test")
        self.tabs.addTab(self.instruments_tab, "2. Instruments")
        self.tabs.addTab(self.setup_tab, "3. Setup")
        self.tabs.addTab(self.run_tab, "4. Run")
        self.tabs.addTab(self.report_tab, "5. Report")
        self.tabs.addTab(self.sequence_tab, "6. Sequence")

        self.setStatusBar(QStatusBar())
        self._build_menu()
        self.refresh_all()

    def _build_menu(self):
        help_menu = self.menuBar().addMenu("&Help")
        guide = QAction("User guide (README)", self)
        guide.triggered.connect(self._open_readme)
        about = QAction("About", self)
        about.triggered.connect(self._about)
        help_menu.addAction(guide)
        help_menu.addAction(about)

    def _open_readme(self):
        readme = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "README.md")
        if os.path.exists(readme) and hasattr(os, "startfile"):
            try:
                os.startfile(readme)  # noqa: S606
                return
            except OSError:
                pass
        QMessageBox.information(self, "User guide", f"See {readme}")

    def _about(self):
        QMessageBox.about(
            self, "About Dynamic Load Test",
            "Dynamic Load Test\n\n"
            "Desktop automation for bench instrument test sequences.\n"
            "First test: USB-C PD Dynamic Output Response.\n\n"
            "Pluggable test framework — add new tests without changing the GUI.")

    # ---- state helpers -------------------------------------------------- #
    def _load_default_config(self, test):
        path = configmod.default_config_path(test.id)
        if os.path.exists(path):
            try:
                return configmod.load_config(path)
            except Exception:
                pass
        return test.default_config()

    def set_test(self, test_id):
        if test_id == self.test.id:
            return
        self.test = testtypes.get_test(test_id)
        self.config = self._load_default_config(self.test)
        self.last_run = None
        self.refresh_all()

    def refresh_all(self):
        for tab in (self.test_tab, self.instruments_tab, self.setup_tab,
                    self.run_tab, self.report_tab, self.sequence_tab):
            tab.refresh()

    def status(self, message):
        self.statusBar().showMessage(message, 8000)
