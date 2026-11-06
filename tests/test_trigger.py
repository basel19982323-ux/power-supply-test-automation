"""Single-shot trigger rules: new capture only (rule 3), no trigger -> ERROR
NO_TRIGGER without a forced capture (rule 5), and the bench is turned off when
a point fails."""
import threading
import time

import pytest

import testtypes
from core.instruments.factory import build_instruments
from core.instruments.yokogawa_scope import YokogawaScope
from core.runner import run_test
from core.test_base import AbortError, RunContext
from core.verdict import ERROR, PASS, PointError, StopRunError


def _run(test_id, tmp_path, **sim):
    t = testtypes.get_test(test_id)
    cfg = t.default_config()
    cfg["simulation"] = sim
    return run_test(t, cfg, simulate=True, output_root=str(tmp_path))


# ---- through a full simulated run ------------------------------------- #
def test_turnoff_no_trigger_is_error_without_forced_capture(tmp_path):
    res = _run("vds_turnoff", tmp_path, scope_never_triggers=True)
    assert [r["result"] for r in res.rows] == [ERROR, ERROR]   # the run continued
    for row in res.rows:
        assert row["error_code"] == "NO_TRIGGER"
        assert row["reason"].startswith("no capture above ")
        assert row["vds_max_v"] == ""       # no reading was taken from a forced capture
        assert row["screenshot"] == ""


def test_ovp_no_trigger_says_the_output_never_rose(tmp_path):
    res = _run("vds_ovp", tmp_path, scope_never_triggers=True)
    row = res.rows[0]
    assert row["result"] == ERROR and row["error_code"] == "NO_TRIGGER"
    assert "the output never rose above 22.0 V" in row["reason"]


@pytest.mark.parametrize("test_id", ["vds_turnoff", "vds_ovp"])
def test_scope_not_rearmed_is_stale_capture(test_id, tmp_path):
    res = _run(test_id, tmp_path, scope_not_rearmed=True)
    assert res.rows and all(r["result"] == ERROR for r in res.rows)
    assert {r["error_code"] for r in res.rows} == {"STALE_CAPTURE"}
    assert PASS not in [r["result"] for r in res.rows]


# ---- the bench is left off when a point fails ------------------------- #
def _ctx(tmp_path, messages):
    return RunContext(run_dir=str(tmp_path), screenshot_dir=str(tmp_path),
                      simulate=True, prompt=lambda m: None, status=messages.append)


def test_failed_point_turns_ac_and_load_off(tmp_path):
    t = testtypes.get_test("vds_ovp")
    cfg = t.default_config()
    cfg["simulation"] = {"scope_never_triggers": True}
    inst = build_instruments(t.required_instruments, cfg, simulate=True)
    calls = []
    inst["e_load"].stop = lambda: calls.append("load off")
    real_off = inst["ac_source"].off
    inst["ac_source"].off = lambda: (calls.append("ac off"), real_off())
    point = t.plan(cfg)[0]
    with pytest.raises(PointError):
        t.execute_point(point, inst, cfg, _ctx(tmp_path, []))
    assert calls[-2:] == ["load off", "ac off"]       # load first, then AC
    assert inst["ac_source"].bench.ac_on is False


def test_a_failing_off_does_not_hide_the_real_error(tmp_path):
    t = testtypes.get_test("vds_ovp")
    cfg = t.default_config()
    cfg["simulation"] = {"scope_never_triggers": True}
    inst = build_instruments(t.required_instruments, cfg, simulate=True)

    def broken():
        raise OSError("load not answering")
    inst["e_load"].stop = broken
    messages = []
    with pytest.raises(PointError) as e:
        t.execute_point(t.plan(cfg)[0], inst, cfg, _ctx(tmp_path, messages))
    assert e.value.code == "NO_TRIGGER"                    # the real error is kept
    assert any("could not turn the e-load off" in m for m in messages)
    assert inst["ac_source"].bench.ac_on is False          # AC was still turned off


# ---- the real Yokogawa driver, with a fake VISA connection ------------- #
class _FakeVisa:
    """Answers queries from a dict (a value or a callable); records writes."""

    def __init__(self, answers):
        self.answers = {"*IDN?": "YOKOGAWA,DLM,FAKE,1.0", **answers}
        self.writes = []
        self.timeout = None

    def write(self, cmd):
        self.writes.append(cmd)

    def query(self, cmd):
        ans = self.answers[cmd]
        return ans() if callable(ans) else ans

    def close(self):
        pass


def test_arm_single_confirms_the_scope_is_running():
    assert YokogawaScope(_FakeVisa({":STATus:CONDition?": "1"})).arm_single() is True
    assert YokogawaScope(_FakeVisa({":STATus:CONDition?": "0"})).arm_single() is False


def test_wait_trigger_no_longer_hides_a_timeout():
    def tmo():
        raise Exception("VI_ERROR_TMO (-1073807339): Timeout expired before operation completed.")
    scope = YokogawaScope(_FakeVisa({":STATus:CONDition?": tmo}))
    with pytest.raises(Exception, match="VI_ERROR_TMO"):
        scope.wait_trigger(5)


def test_wait_trigger_garbage_status_is_bad_reply():
    scope = YokogawaScope(_FakeVisa({":STATus:CONDition?": "BUSY"}))
    with pytest.raises(StopRunError) as e:
        scope.wait_trigger(5)
    assert e.value.code == "BAD_REPLY"


def test_wait_trigger_times_out_and_stop_interrupts_it():
    scope = YokogawaScope(_FakeVisa({":STATus:CONDition?": "1"}))   # never triggers
    assert scope.wait_trigger(0.2) is False

    stop = threading.Event()
    threading.Timer(0.2, stop.set).start()

    def cancel():
        if stop.is_set():
            raise AbortError("stopped")
    t0 = time.time()
    with pytest.raises(AbortError):
        scope.wait_trigger(30, cancel=cancel)
    assert time.time() - t0 < 5


def test_read_screen_top_uses_the_scope_values():
    scope = YokogawaScope(_FakeVisa({":CHANnel1:VDIV?": "5.000E+01",
                                     ":CHANnel1:OFFSet?": "2.000E+02"}))
    scope.set_vertical(1, 100.0, offset=400.0)       # what the app ASKED for: 0..800 V
    assert scope.screen_top(1) == 800.0
    assert scope.read_screen_top(1) == 400.0         # what the scope REALLY shows
