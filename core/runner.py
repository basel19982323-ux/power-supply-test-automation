"""Generic test executor — hardware-agnostic, UI-agnostic.

Given a TestType + config, it: creates a timestamped run folder, builds the
instruments (real or simulated), runs the test's point plan, persists a
results.csv, and reports progress through callbacks. Instruments are always shut
down and partial results are always saved (the original tool's safety guarantee:
AC/load off and a written CSV even if a point raises mid-matrix).

The same runner backs both the CLI (`cli.py`) and the GUI worker thread — only
the callbacks differ.
"""
import os
import threading

from .instruments.factory import build_instruments
from .results import new_run_dir, write_csv
from .test_base import AbortError, Callbacks, RunContext


class RunResult:
    def __init__(self, run_dir, csv_path, rows, summary,
                 aborted=False, error=None):
        self.run_dir = run_dir
        self.csv_path = csv_path
        self.rows = rows
        self.summary = summary
        self.aborted = aborted
        self.error = error


def run_test(test, config, *, simulate=False, callbacks=None,
             abort_event=None, output_root=None):
    """Execute `test` with `config`. Returns a RunResult. Never raises for a
    point-level failure — errors are captured on the result and teardown runs."""
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
    )

    rows = []
    error = None
    aborted = False
    instruments = {}
    try:
        instruments = build_instruments(
            test.required_instruments, config, simulate, prompt_fn=ctx.prompt
        )
        test.prepare(instruments, config, ctx)

        plan = test.plan(config)
        callbacks.on_start(len(plan))
        for i, point in enumerate(plan):
            if abort_event.is_set():
                aborted = True
                ctx.status("Run aborted by operator.")
                break
            ctx.status(f"[{i + 1}/{len(plan)}] {point.get('label', '')}")
            row = test.execute_point(point, instruments, config, ctx)
            rows.append(row)
            callbacks.on_point_done(i, row)
            shot = row.get("screenshot")
            if shot:
                callbacks.on_screenshot(os.path.join(run_dir, shot))
    except AbortError:
        aborted = True
        ctx.status("Run aborted by operator.")
    except Exception as e:  # capture, don't crash the UI thread
        error = str(e)
        ctx.status(f"ERROR: {e}")
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
        summary = test.summarize(rows)
        ctx.status(f"Saved {len(rows)} rows -> {csv_path}  "
                   f"({summary['pass']} PASS / {summary['fail']} FAIL)")

    return RunResult(run_dir, csv_path, rows, test.summarize(rows),
                     aborted=aborted, error=error)


def _wrap_prompt(prompt_fn, abort_event):
    """Give every prompt an abort check, so aborting also releases a waiting prompt."""
    def _p(message):
        if abort_event.is_set():
            raise AbortError("aborted")
        prompt_fn(message)
        if abort_event.is_set():
            raise AbortError("aborted")
    return _p
