"""Dynamic Load Test — desktop application entry point.

    python main.py

Adds the application root to sys.path (so `core`, `testtypes`, `reporting`, and
`ui` import as top-level packages whether run from source or a PyInstaller
bundle), then launches the Qt main window.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    from PySide6.QtWidgets import QApplication
    from ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Dynamic Load Test")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
