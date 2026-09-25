"""Background worker that runs a sequence of test steps in succession.

Loops the steps on a QThread, running each via core.runner.run_test, and streams
the same kind of signals as the single RunWorker (with a step index added) so the
Sequence tab can show live progress. One shared abort event stops the whole run;
the POWER-Z manual prompt round-trip is preserved per step.
"""
import threading

from PySide6.QtCore import QObject, Signal, Slot

from core.runner import run_test
from core.sequence import make_sequence_dir, resolve_step
from core.test_base import Callbacks


class SequenceWorker(QObject):
    step_started = Signal(int, str, int)     # index, test name, total points
    point_done = Signal(int, int, dict)      # step index, point index, row
    status = Signal(str)
    screenshot = Signal(str)
    need_prompt = Signal(str)
    step_finished = Signal(int, object)      # index, RunResult
    sequence_finished = Signal(object)       # list of step dicts (with results)

    def __init__(self, steps, simulate):
        super().__init__()
        self._steps = steps
        self._simulate = simulate
        self.abort_event = threading.Event()
        self._prompt_event = threading.Event()

    @Slot()
    def run(self):
        parent = make_sequence_dir()
        results = []
        for i, step in enumerate(self._steps):
            if self.abort_event.is_set():
                break
            try:
                test, config = resolve_step(step)
            except Exception as e:  # noqa: BLE001
                self.status.emit(f"Step {i + 1} skipped: {e}")
                continue
            self.status.emit(f"===== Step {i + 1}/{len(self._steps)}: {test.name} =====")
            callbacks = Callbacks(
                on_start=(lambda n, idx=i, nm=test.name: self.step_started.emit(idx, nm, n)),
                on_point_done=(lambda pi, row, idx=i: self.point_done.emit(idx, pi, row)),
                on_status=(lambda m: self.status.emit(m)),
                on_screenshot=(lambda p: self.screenshot.emit(p)),
                prompt=self._prompt,
            )
            res = run_test(test, config, simulate=self._simulate, callbacks=callbacks,
                           abort_event=self.abort_event, output_root=parent)
            results.append({"name": test.name, "test": test, "config": config, "result": res})
            self.step_finished.emit(i, res)
            if res.aborted:
                break
        self.sequence_finished.emit(results)

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
