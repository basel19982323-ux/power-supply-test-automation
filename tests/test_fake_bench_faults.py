"""Fault injection: the REAL drivers run against a fake SCPI bench that
misbehaves like real instruments can. For every fault:

  * no point is PASS,
  * the point gets the right fixed ERROR code (the rest NOT RUN when the
    fault stops the run),
  * the AC source and the e-load were both SENT their OFF command AND
    CONFIRMED off by the instrument itself (read from the fake bench's own
    log, and checked against the app's shutdown record) - or, when that is
    impossible (lost connection), the app shows the "may still be ON" warning.
"""
import pytest

from core.verdict import ERROR, NOT_RUN, PASS


def assert_safe_failure(res, bench, code, *, stops_run):
    results = [r["result"] for r in res.rows]
    assert PASS not in results, results
    assert res.rows[0]["result"] == ERROR and res.rows[0]["error_code"] == code, res.rows[0]
    if stops_run:
        assert res.error.startswith(code)
        assert all(r == NOT_RUN for r in results[1:])
        assert {r["error_code"] for r in res.rows[1:]} <= {"RUN_ENDED_EARLY"}
    else:                                           # a point error: the run goes on
        assert res.error is None
        assert all(r["result"] == ERROR and r["error_code"] == code for r in res.rows)
    for role in res.shutdown:                       # every powered instrument used
        assert bench.off_state(role) == (True, True), role       # instrument's view
        assert res.shutdown[role]["off_sent"] is True, role       # app: command sent
        assert res.shutdown[role]["confirmed_off"] is True, role  # app: confirmed
    assert res.warnings == []


# ---- communication faults ------------------------------------------------- #
@pytest.mark.parametrize("fault, code", [
    ("ac_no_reply_once", "TIMEOUT"),         # instrument does not answer
    ("scope_garbage_reply", "BAD_REPLY"),    # 'ABC' instead of a number
    ("scope_wrong_unit", "WRONG_UNIT"),      # '5.680E+02A' - amps, not volts
])
def test_communication_fault_stops_the_run_safely(run_on_fake_bench, fault, code):
    res, bench, _ = run_on_fake_bench("vds_turnoff", faults={fault: True})
    assert_safe_failure(res, bench, code, stops_run=True)
    assert "ac_source" in res.shutdown


def test_wrong_unit_reply_is_never_read_as_volts(run_on_fake_bench):
    res, bench, _ = run_on_fake_bench("vds_turnoff", faults={"scope_wrong_unit": True})
    assert "A'" in res.rows[0]["reason"]           # the reason quotes the amps reply
    assert not any(c.startswith(":STAR") for c in bench.sent("scope"))   # never armed


def test_the_ac_is_never_cut_as_a_test_event_after_a_bad_reply(run_on_fake_bench):
    # The steady reading failed BEFORE the event: the scope was never armed.
    res, bench, _ = run_on_fake_bench("vds_turnoff", faults={"scope_garbage_reply": True})
    assert not any(c.startswith(":STAR") for c in bench.sent("scope"))


# ---- scope faults (point errors: each point ERROR, the run goes on) ------- #
VDS_TESTS = ["vds_turnoff", "vds_ovp"]


@pytest.mark.parametrize("test_id", VDS_TESTS)
def test_scope_never_triggers_is_no_trigger_without_a_forced_capture(run_on_fake_bench,
                                                                    test_id):
    res, bench, _ = run_on_fake_bench(test_id, faults={"scope_never_triggers": True})
    assert_safe_failure(res, bench, "NO_TRIGGER", stops_run=False)
    scope = bench.sent("scope")
    assert ":STOP" in scope                                   # acquisition stopped
    assert not any("FORC" in c for c in scope)                # never forced
    assert not any("<PNG>" == r for ro, _, r in bench.log if ro == "scope")  # no screenshot


@pytest.mark.parametrize("test_id", VDS_TESTS)
def test_scope_not_rearmed_is_stale_capture(run_on_fake_bench, test_id):
    res, bench, prompts = run_on_fake_bench(test_id, faults={"scope_not_rearmed": True})
    assert_safe_failure(res, bench, "STALE_CAPTURE", stops_run=False)
    assert prompts == []          # OVP: the operator is never asked to break feedback


@pytest.mark.parametrize("test_id", VDS_TESTS)
def test_probe_disconnected_is_probe_check_before_any_event(run_on_fake_bench, test_id):
    res, bench, prompts = run_on_fake_bench(test_id, faults={"probe_disconnected": True})
    assert_safe_failure(res, bench, "PROBE_CHECK", stops_run=False)
    assert not any(c.startswith(":STAR") for c in bench.sent("scope"))   # never armed
    assert prompts == []
