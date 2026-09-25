"""Small reusable background-task helpers for the GUI.

FnWorker runs a plain function on a QThreadPool thread and delivers the result
or error back on the GUI thread via signals — used for one-shot tasks like VISA
scan and per-instrument connection tests so the UI never freezes. The long test
run has its own dedicated worker (see run_tab).
"""
from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class _FnSignals(QObject):
    result = Signal(object)
    error = Signal(str)


class FnWorker(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self.signals = _FnSignals()

    @Slot()
    def run(self):
        try:
            result = self._fn(*self._args, **self._kwargs)
        except Exception as e:  # noqa: BLE001 - report any failure to the UI
            self.signals.error.emit(str(e))
        else:
            self.signals.result.emit(result)
