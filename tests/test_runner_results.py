"""How the runner turns problems into ERROR / NOT RUN rows (rule 7, Stop,
lost instruments). Uses small stub test types, so no instruments are needed."""
import threading
import time

import pytest

import testtypes
from core import test_base as tb
from core.runner import run_test
from core.verdict import ERROR, NOT_RUN, PASS, PointError, classify_exception


class _StubTest(tb.TestType):
    """Three points, no instruments. `behaviour` maps a point index to what
    execute_point does: an exception to raise, or a callable(ctx)."""
    id = "stub"
    name = "Stub"
    required_instruments = []
    csv_fields = ["timestamp", "dut", "label", "result", "error_code", "reason"]

    def __init__(self, behaviour=None, plan_error=None):
        self.behaviour = behaviour or {}
        self.plan_error = plan_error

    def default_config(self):
        return {"dut_name": "STUB"}

    def plan(self, config):
        if self.plan_error:
            raise self.plan_error
        return [{"label": f"point {i}", "index": i} for i in range(3)]

    def execute_point(self, point, instruments, config, ctx):
        action = self.behaviour.get(point["index"])
        if isinstance(action, BaseException):
            raise action
        if callable(action):
            action(ctx)
        return self.make_row(point, config, PASS)


def run(test, **kw):
    return run_test(test, test.default_config(), simulate=True, **kw)


def results(res):
    return [r["result"] for r in res.rows]


def test_point_error_is_error_and_the_run_continues(tmp_path):
    res = run(_StubTest({1: PointError("NO_TRIGGER", "no capture above 520 V")}),
              output_root=str(tmp_path))
    assert results(res) == [PASS, ERROR, PASS]
    assert res.rows[1]["error_code"] == "NO_TRIGGER"
    assert res.rows[1]["reason"] == "no capture above 520 V"
    assert res.overall == ERROR and res.error is None


def test_lost_instrument_stops_the_run_rest_not_run(tmp_path):
    res = run(_StubTest({1: ConnectionResetError("connection reset by peer")}),
              output_root=str(tmp_path))
    assert results(res) == [PASS, ERROR, NOT_RUN]
    assert res.rows[1]["error_code"] == "DISCONNECTED"
    assert res.rows[2]["error_code"] == "RUN_ENDED_EARLY"
    assert res.error.startswith("DISCONNECTED")
    assert res.overall == ERROR


def test_stop_marks_the_remaining_points_not_run(tmp_path):
    stop = threading.Event()
    cb = tb.Callbacks(on_point_done=lambda i, row: stop.set())   # Stop after point 1
    res = run(_StubTest(), callbacks=cb, abort_event=stop, output_root=str(tmp_path))
    assert results(res) == [PASS, NOT_RUN, NOT_RUN]
    assert {r["error_code"] for r in res.rows[1:]} == {"STOPPED"}
    assert res.aborted and res.overall == NOT_RUN


def test_stop_interrupts_a_long_wait(tmp_path):
    stop = threading.Event()
    threading.Timer(0.2, stop.set).start()
    t0 = time.time()
    res = run(_StubTest({0: lambda ctx: ctx.sleep(30)}), abort_event=stop,
              output_root=str(tmp_path))
    assert time.time() - t0 < 5                  # did not wait the full 30 s
    assert results(res) == [NOT_RUN, NOT_RUN, NOT_RUN]


def test_a_broken_plan_is_error_not_a_crash(tmp_path):
    res = run(_StubTest(plan_error=KeyError("ac_conditions")), output_root=str(tmp_path))
    assert res.rows == []
    assert res.error.startswith("BAD_CONFIG")
    assert res.overall == ERROR


@pytest.mark.parametrize("exc, code", [
    (TimeoutError("timed out"), "TIMEOUT"),
    (Exception("VI_ERROR_TMO (-1073807339): Timeout expired"), "TIMEOUT"),
    (Exception("VI_ERROR_CONN_LOST: connection lost"), "DISCONNECTED"),
    (ConnectionResetError("reset"), "DISCONNECTED"),
    (ValueError("something odd"), "INSTRUMENT_ERROR"),
])
def test_unexpected_exceptions_get_a_fixed_code(exc, code):
    assert classify_exception(exc)[0] == code


def test_sanity_abort_is_error_and_the_rest_not_run(tmp_path):
    # Probe attenuation wrong by 10x: the first point reads ~51 V on a 5 V output.
    t = testtypes.get_test("dynamic_output_response")
    cfg = t.default_config()
    cfg["simulation"] = {"reading_scale": 10}
    res = run_test(t, cfg, simulate=True, output_root=str(tmp_path))
    assert results(res) == [ERROR] + [NOT_RUN] * 15
    assert res.rows[0]["error_code"] == "SANITY_ABORT"
    assert res.rows[0]["vmax_v"] > 50          # the bad reading is kept for diagnosis
    assert {r["error_code"] for r in res.rows[1:]} == {"RUN_ENDED_EARLY"}
    assert res.error.startswith("SANITY_ABORT") and res.overall == ERROR
