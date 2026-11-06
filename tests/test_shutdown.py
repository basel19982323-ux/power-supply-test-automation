"""Safe shutdown (rules 7 and 8): every instrument is turned off even if one
fails, AC-off is confirmed by asking the source, and a lost instrument stops
the run with a clear warning."""
import pytest

import testtypes
from core.instruments.itech_ac import ITechACSource
from core.instruments.itech_load import ITechLoad
from core.runner import run_test
from core.shutdown import AC_WARNING, LOAD_WARNING, shutdown_bench
from core.verdict import ERROR, NOT_RUN, PASS


def _run(test_id, tmp_path, **sim):
    t = testtypes.get_test(test_id)
    cfg = t.default_config()
    cfg["simulation"] = sim
    return run_test(t, cfg, simulate=True, output_root=str(tmp_path))


# ---- the shutdown helper -------------------------------------------------- #
class _Dev:
    def __init__(self, role, log, fail=(), on_after_off=False):
        self.role, self.log, self.fail, self.on_after_off = role, log, fail, on_after_off

    def _do(self, what):
        self.log.append(f"{self.role}.{what}")
        if what in self.fail:
            raise OSError(f"{self.role} {what} failed")

    def stop(self):
        self._do("stop")

    def off(self):
        self._do("off")

    def output_is_on(self):
        self._do("output_is_on")
        return self.on_after_off

    def input_is_on(self):
        self._do("input_is_on")
        return self.on_after_off

    def close(self):
        self._do("close")


def test_shutdown_order_load_then_ac_then_confirm_then_close():
    log = []
    inst = {"ac_source": _Dev("ac_source", log), "e_load": _Dev("e_load", log),
            "scope": _Dev("scope", log)}
    assert shutdown_bench(inst, status=lambda m: None) == []
    assert log[:4] == ["e_load.stop", "ac_source.off", "ac_source.output_is_on",
                       "e_load.input_is_on"]
    assert set(log[4:]) == {"ac_source.close", "e_load.close", "scope.close"}


def test_a_broken_load_does_not_stop_the_ac_being_turned_off():
    log = []
    inst = {"ac_source": _Dev("ac_source", log),
            "e_load": _Dev("e_load", log, fail={"stop", "input_is_on", "close"})}
    warnings = shutdown_bench(inst, status=lambda m: None)
    assert "ac_source.off" in log and "ac_source.close" in log
    assert warnings == [LOAD_WARNING]          # the load could not be confirmed off


@pytest.mark.parametrize("dev", [
    _Dev("ac_source", [], on_after_off=True),          # still says ON
    _Dev("ac_source", [], fail={"off", "output_is_on"}),  # can't be reached
])
def test_ac_not_confirmed_off_is_a_warning(dev):
    assert shutdown_bench({"ac_source": dev}, status=lambda m: None) == [AC_WARNING]


# ---- through a simulated run ---------------------------------------------- #
@pytest.mark.parametrize("test_id", ["dynamic_output_response", "vds_turnoff", "vds_ovp"])
def test_normal_run_has_no_warnings(test_id, tmp_path):
    assert _run(test_id, tmp_path).warnings == []


def test_ac_off_unconfirmed_warns_after_the_run(tmp_path):
    res = _run("vds_turnoff", tmp_path, ac_off_unconfirmed=True)
    assert AC_WARNING in res.warnings
    assert [r["result"] for r in res.rows] == [PASS, PASS]   # measurements were fine


def test_mid_run_disconnect_stops_the_run_and_warns(tmp_path):
    # The AC source answers 2 commands (2 points), then the connection is lost.
    res = _run("dynamic_output_response", tmp_path, disconnect_ac_after=2)
    results = [r["result"] for r in res.rows]
    assert results == [PASS, PASS, ERROR] + [NOT_RUN] * 13
    assert res.rows[2]["error_code"] == "DISCONNECTED"
    assert {r["error_code"] for r in res.rows[3:]} == {"RUN_ENDED_EARLY"}
    assert res.error.startswith("DISCONNECTED") and res.overall == ERROR
    assert AC_WARNING in res.warnings          # AC off could not be confirmed


# ---- the real ITECH drivers with a fake VISA connection ------------------ #
class _FakeVisa:
    def __init__(self, replies=None, fail_writes=()):
        self.replies = {"*IDN?": "ITECH,FAKE,0,1.0", **(replies or {})}
        self.fail_writes = set(fail_writes)
        self.writes = []
        self.timeout = None

    def write(self, cmd):
        self.writes.append(cmd)
        if cmd in self.fail_writes:
            raise OSError(f"write {cmd} failed")

    def query(self, cmd):
        return self.replies[cmd]

    def close(self):
        pass


def test_load_stop_sends_input_off_first():
    visa = _FakeVisa()
    ITechLoad(visa).stop()
    assert visa.writes == ["INPut OFF", "TRANsient OFF"]


def test_load_stop_still_sends_transient_off_if_input_off_fails():
    visa = _FakeVisa(fail_writes={"INPut OFF"})
    with pytest.raises(OSError):
        ITechLoad(visa).stop()
    assert visa.writes == ["INPut OFF", "TRANsient OFF"]


@pytest.mark.parametrize("reply, on", [("1", True), ("0", False), ("OFF", False), ("ON\n", True)])
def test_ac_driver_reads_back_its_output_state(reply, on):
    assert ITechACSource(_FakeVisa({"OUTPut?": reply})).output_is_on() is on
