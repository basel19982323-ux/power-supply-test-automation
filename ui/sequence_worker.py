"""Background worker that runs a sequence of test steps in succession.

Loops the steps on a QThread, running each via core.runner.run_test, and streams
the same kind of signals as the single RunWorker (with a step index added) so the
Sequence tab can show live progress. One shared abort event stops the whole run;
the POWER-Z manual prompt round-trip is preserved per step.
"""
import threading

from PySide6.QtCore import QObject, Signal, Slot

from core.sequence import run_sequence
from core.test_base import Callbacks


class SequenceWorker(QObject):
    step_started = Signal(int, str, int)     # index, test name, total points
    point_done = Signal(int, int, dict)      # step index, point index, row
    status = Signal(str)
    screenshot = Signal(str)
    need_prompt = Signal(str)
    step_finished = Signal(int, object)      # index, step dict (name, outcome, result)
    sequence_finished = Signal(object)       # core.sequence.SequenceResult

    def __init__(self, steps, simulate):
        super().__init__()
        self._steps = steps
        self._simulate = simulate
        self.abort_event = threading.Event()
        self._prompt_event = threading.Event()

    @Slot()
    def run(self):
        seq = run_sequence(
            self._steps, simulate=self._simulate, abort_event=self.abort_event,
            callbacks_for=self._callbacks, on_status=self.status.emit,
            on_step_finished=lambda i, step: self.step_finished.emit(i, step))
        self.sequence_finished.emit(seq)

    def _callbacks(self, i, test):
        return Callbacks(
            on_start=(lambda n: self.step_started.emit(i, test.name, n)),
            on_point_done=(lambda pi, row: self.point_done.emit(i, pi, row)),
            on_status=(lambda m: self.status.emit(m)),
            on_screenshot=(lambda p: self.screenshot.emit(p)),
            prompt=self._prompt,
        )

    # ---- prompt round-trip (same pattern as RunWorker) ------------------ #
    def _prompt(self, message):
        self._prompt_event.clear()
        self.need_prompt.emit(message)
        self._prompt_event.wait()

    def resolve_prompt(self):
        self._prompt_event.set()

    def request_abort(self):
        self.abort_event.set()
        self._prompt_event.set()
