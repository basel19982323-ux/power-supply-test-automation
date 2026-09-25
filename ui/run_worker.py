"""Background worker that runs a test off the GUI thread.

core.runner.run_test is synchronous and blocking (it sleeps, talks to
instruments, and — in manual POWER-Z mode — waits for the operator). Running it
on a QThread keeps the UI responsive and lets progress stream in through Qt
signals. The manual POWER-Z pause is handled by emitting need_prompt and
blocking the worker thread on an Event until the GUI resolves it.
"""
import threading

from PySide6.QtCore import QObject, Signal, Slot

from core.runner import run_test
from core.test_base import Callbacks


class RunWorker(QObject):
    started_run = Signal(int)       # total number of points
    status = Signal(str)            # human-readable progress line
    point_done = Signal(int, dict)  # index, result row
    screenshot = Signal(str)        # absolute path to a captured screenshot
    need_prompt = Signal(str)       # operator action required (POWER-Z manual)
    finished_run = Signal(object)   # core.runner.RunResult

    def __init__(self, test, config, simulate):
        super().__init__()
        self._test = test
        self._config = config
        self._simulate = simulate
        self.abort_event = threading.Event()
        self._prompt_event = threading.Event()

    @Slot()
    def run(self):
        callbacks = Callbacks(
            on_start=lambda n: self.started_run.emit(n),
            on_point_done=lambda i, row: self.point_done.emit(i, row),
            on_status=lambda m: self.status.emit(m),
            on_screenshot=lambda p: self.screenshot.emit(p),
            prompt=self._prompt,
        )
        result = run_test(self._test, self._config, simulate=self._simulate,
                          callbacks=callbacks, abort_event=self.abort_event)
        self.finished_run.emit(result)

    # ---- prompt round-trip (worker thread <-> GUI thread) --------------- #
    def _prompt(self, message):
        """Called on the worker thread; blocks until the GUI resolves it."""
        self._prompt_event.clear()
        self.need_prompt.emit(message)
        self._prompt_event.wait()
        # The runner's wrapped prompt re-checks abort_event after we return.

    def resolve_prompt(self):
        """Called on the GUI thread when the operator confirms the dialog."""
        self._prompt_event.set()

    def request_abort(self):
        """Called on the GUI thread; also releases a waiting prompt."""
        self.abort_event.set()
        self._prompt_event.set()
