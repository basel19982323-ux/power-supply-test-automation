"""Generic test executor — hardware-agnostic, UI-agnostic.

Given a TestType + config, it: creates a timestamped run folder, builds the
instruments (real or simulated), runs the test's point plan, persists a
results.csv, and reports progress through callbacks.

Every planned point ends up in the results with one of four results:

  * a point that measured normally            -> PASS or FAIL
  * a point whose measurement can't be trusted -> ERROR (code + reason), and
    the run continues with the next point (PointError)
  * a problem that makes the whole bench untrustworthy (sanity abort, timeout,
    lost connection, unexpected error) -> that point ERROR, every remaining
    point NOT RUN, and the bench is shut down
  * the operator pressed Stop                  -> the rest are NOT RUN

Instruments are always shut down and the CSV is always written, even when a
point raises in the middle of the matrix.

The same runner backs both the CLI (`cli.py`) and the GUI worker thread — only
the callbacks differ.
"""
import os
import threading

from .instruments.factory import build_instruments
from .results import new_run_dir, write_csv
from .test_base import AbortError, Callbacks, RunContext
from .verdict import (ERROR, NOT_RUN, PointError, classify_exception,
                      overall as overall_result)


class RunResult:
    def __init__(self, run_dir, csv_path, rows, summary,
                 aborted=False, error=None, overall=None):
        self.run_dir = run_dir
        self.csv_path = csv_path
        self.rows = rows
        self.summary = summary        # counts: total / pass / fail / error / not_run
        self.aborted = aborted        # True if the operator pressed Stop
        self.error = error            # "CODE: reason" if the run stopped on an error
        # PASS / FAIL / ERROR / NOT RUN for the whole run (see core.verdict)
        self.overall = overall if overall is not None else overall_result(rows, error)


def run_test(test, config, *, simulate=False, callbacks=None,
             abort_event=None, output_root=None):
    """Execute `test` with `config`. Returns a RunResult. Never raises for a
    point-level problem — it is recorded as ERROR / NOT RUN and teardown runs."""
    callbacks = callbacks or Callbacks()
    abort_event = abort_event or threading.Event()

    run_dir = (new_run_dir(config.get("dut_name", "DUT"), output_root)
               if output_root else new_run_dir(config.get("dut_name", "DUT")))
    screenshot_dir = os.path.join(run_dir, "screenshots")
    csv_path = os.path.join(run_dir, "results.csv")

    ctx = RunContext(
        run_dir=run_dir,
        screenshot_dir=screenshot_dir,
        simulate=simulate,
        prompt=_wrap_prompt(callbacks.prompt, abort_event),
        status=callbacks.on_status,
        sleep=_make_sleep(abort_event),
        check_stop=_make_check_stop(abort_event),
    )

    rows = []
    error = None
    aborted = False
    instruments = {}

    def record(index, row):
        rows.append(row)
        callbacks.on_point_done(index, row)
        shot = row.get("screenshot")
        if shot:
            callbacks.on_screenshot(os.path.join(run_dir, shot))

    def not_run_from(plan, start, code, reason):
        for j in range(start, len(plan)):
            record(j, _safe_row(test, plan[j], config, NOT_RUN, code, reason))

    try:
        try:
            plan = test.plan(config)
        except Exception as e:  # noqa: BLE001 - a broken config must not crash the app
            error = f"BAD_CONFIG: could not build the test plan ({e})"
            ctx.status(f"ERROR {error}")
            plan = []
        callbacks.on_start(len(plan))

        i = 0
        try:
            if plan:
                instruments = build_instruments(
                    test.required_instruments, config, simulate, prompt_fn=ctx.prompt)
                test.prepare(instruments, config, ctx)
            for i, point in enumerate(plan):
                if abort_event.is_set():
                    raise AbortError("aborted")
                ctx.status(f"[{i + 1}/{len(plan)}] {point.get('label', '')}")
                try:
                    row = test.execute_point(point, instruments, config, ctx)
                except PointError as e:
                    row = _safe_row(test, point, config, ERROR, e.code, e.reason, e.values)
                    ctx.status(f"    -> ERROR {e.code}: {e.reason}")
                record(i, row)
        except AbortError:
            aborted = True
            ctx.status("Run stopped by the operator.")
            not_run_from(plan, i, "STOPPED", "not measured: the operator pressed Stop")
        except Exception as e:  # noqa: BLE001 - capture, don't crash the UI thread
            code, reason = classify_exception(e)
            error = f"{code}: {reason}"
            ctx.status(f"ERROR {error}")
            if plan:
                values = getattr(e, "values", {})
                record(i, _safe_row(test, plan[i], config, ERROR, code, reason, values))
                not_run_from(plan, i + 1, "RUN_ENDED_EARLY",
                             f"not measured: the run stopped after {code} on point {i + 1}")
    finally:
        try:
            test.finish(instruments, config, ctx)
        except Exception:
            pass
        for dev in instruments.values():
            try:
                dev.close()
            except Exception:
                pass
        fields = test.csv_fields or [c.key for c in test.result_columns]
        write_csv(csv_path, fields, rows)
        s = test.summarize(rows)
        ctx.status(f"Saved {len(rows)} rows -> {csv_path}  ({s['pass']} PASS / "
                   f"{s['fail']} FAIL / {s['error']} ERROR / {s['not_run']} NOT RUN)")

    return RunResult(run_dir, csv_path, rows, test.summarize(rows),
                     aborted=aborted, error=error)


def _safe_row(test, point, config, result, code, reason, values=None):
    """Build an ERROR / NOT RUN row. If even that fails (broken config), fall
    back to a minimal row so the point is never silently missing."""
    try:
        return test.make_row(point, config, result, code, reason, **(values or {}))
    except Exception:  # noqa: BLE001
        return {"result": result, "error_code": code, "reason": reason,
                "label": point.get("label", "")}


def _make_sleep(abort_event):
    def _sleep(seconds):
        if abort_event.wait(max(0.0, float(seconds))):
            raise AbortError("aborted")
    return _sleep


def _make_check_stop(abort_event):
    def _check():
        if abort_event.is_set():
            raise AbortError("aborted")
    return _check


def _wrap_prompt(prompt_fn, abort_event):
    """Give every prompt an abort check, so aborting also releases a waiting prompt."""
    def _p(message):
        if abort_event.is_set():
            raise AbortError("aborted")
        prompt_fn(message)
        if abort_event.is_set():
            raise AbortError("aborted")
    return _p
