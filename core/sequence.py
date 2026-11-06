"""Helpers for running an ordered suite of tests in succession.

A "step" is a small dict: {"test_id": str, "config_path": str|None, "name": str}.
resolve_step() turns it into a (TestType, config) pair; make_sequence_dir()
creates one parent folder so every step's run lands together. run_sequence()
is the loop itself (no Qt, so it can be tested); ui/sequence_worker.py runs it
on a thread and turns its callbacks into Qt signals.

Every step gets a result, like every test point does:
  * a step that ran          -> its run's overall result (PASS/FAIL/ERROR/NOT RUN)
  * a step that can't load   -> NOT RUN STEP_NOT_LOADED (never silently skipped)
  * steps after Stop         -> NOT RUN STOPPED
  * steps after a bench problem (lost instrument, sanity abort, bench not
    confirmed off ...)       -> NOT RUN RUN_ENDED_EARLY
The sequence result combines the steps the same way points are combined.
"""
import os
import threading
from datetime import datetime

from .config import load_config
from .results import OUTPUT_ROOT
from .runner import run_test
from .test_base import Callbacks
from .verdict import NOT_RUN, combine


def make_sequence_dir(output_root=None):
    root = output_root or OUTPUT_ROOT
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(root, "sequences", f"SEQ_{stamp}")
    os.makedirs(path, exist_ok=True)
    return path


def resolve_step(step):
    """Return (test, config) for a step. Uses the step's saved config file if
    present, otherwise the test's built-in defaults."""
    import testtypes

    test = testtypes.get_test(step["test_id"])
    cfg_path = step.get("config_path")
    if cfg_path:
        # A saved config that has gone missing is an error, not "use the
        # defaults": the defaults have different limits and would test the
        # wrong thing without anyone noticing.
        if not os.path.exists(cfg_path):
            raise FileNotFoundError(f"config file not found: {cfg_path}")
        config = load_config(cfg_path)
    else:
        config = test.default_config()
    return test, config


def step_label(step):
    """Human label for the steps list, e.g. 'VDS Max — AC Turn-off  ·  high-line'."""
    import testtypes

    try:
        name = testtypes.get_test(step["test_id"]).name
    except Exception:
        name = step.get("test_id", "?")
    cfg = step.get("name") or "(built-in defaults)"
    return f"{name}  ·  {cfg}"


class SequenceResult:
    def __init__(self, seq_dir, steps):
        self.seq_dir = seq_dir
        self.steps = steps            # one dict per step, see run_sequence()
        self.overall = combine(st["outcome"] for st in steps)


def step_outcome(step):
    """(result, code, reason) for one step dict."""
    res = step.get("result")
    if res is None:
        return NOT_RUN, step.get("code", ""), step.get("reason", "")
    code, reason = "", ""
    if res.error:
        code, _, reason = res.error.partition(": ")
    elif res.aborted:
        code, reason = "STOPPED", "the operator pressed Stop"
    if res.warnings:
        reason = "; ".join([reason] + res.warnings) if reason else "; ".join(res.warnings)
    return res.overall, code, reason


def _stop_reason(res, index):
    """Why the steps after this one must not run, or None to carry on."""
    if res.aborted:
        return "STOPPED", "not run: the operator pressed Stop"
    if res.warnings:
        return ("RUN_ENDED_EARLY", f"not run: after step {index + 1} the bench could "
                                   f"not be confirmed off")
    if res.error and not res.error.startswith("BAD_CONFIG"):
        # A bench problem (lost instrument, sanity abort, ...) - the next step
        # would use the same untrusted bench. A bad config only affects its step.
        code = res.error.split(":", 1)[0]
        return ("RUN_ENDED_EARLY", f"not run: the sequence stopped after {code} in "
                                   f"step {index + 1}")
    return None


def run_sequence(steps, *, simulate=False, abort_event=None, callbacks_for=None,
                 on_status=print, on_step_finished=None, output_root=None):
    """Run the steps in order. Returns a SequenceResult.

    callbacks_for(index, test) -> Callbacks for that step's run (GUI signals);
    on_step_finished(index, step_dict) is called after every step, also for
    steps that did not run."""
    abort_event = abort_event or threading.Event()
    parent = make_sequence_dir(output_root)
    out = []
    stop = None                  # (code, reason) once the remaining steps must not run
    for i, step in enumerate(steps):
        if stop is None and abort_event.is_set():
            stop = ("STOPPED", "not run: the operator pressed Stop")
        entry = {"name": step_label(step), "test": None, "config": None, "result": None}
        if stop is not None:
            entry["code"], entry["reason"] = stop
        else:
            try:
                test, config = resolve_step(step)
            except Exception as e:  # noqa: BLE001 - record it, don't crash
                entry["code"] = "STEP_NOT_LOADED"
                entry["reason"] = f"the step's settings could not be loaded ({e})"
                on_status(f"Step {i + 1} NOT RUN: {entry['reason']}")
            else:
                on_status(f"===== Step {i + 1}/{len(steps)}: {test.name} =====")
                cb = callbacks_for(i, test) if callbacks_for else Callbacks(on_status=on_status)
                res = run_test(test, config, simulate=simulate, callbacks=cb,
                               abort_event=abort_event, output_root=parent)
                entry.update(name=test.name, test=test, config=config, result=res)
                stop = _stop_reason(res, i)
        entry["outcome"], entry["code"], entry["reason"] = step_outcome(entry)
        out.append(entry)
        if on_step_finished:
            on_step_finished(i, entry)
    return SequenceResult(parent, out)
