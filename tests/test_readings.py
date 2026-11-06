"""Safe readings and judging (rules 1 and 2): a broken, missing or clipped
reading must never become a PASS."""
import math

import pytest

import testtypes
from core.instruments.replies import parse_number
from core.runner import run_test
from core.verdict import (ERROR, FAIL, PASS, StopRunError, judge_upper,
                          judge_window)
from testtypes.common import clip_check


# ---- parse_number: text reply -> number --------------------------------- #
@pytest.mark.parametrize("reply, value", [
    ("5.02", 5.02),
    ("5.02E+00\n", 5.02),
    ("  -1.5e-3 ", -0.0015),
    ("5.02 V", 5.02),
    ("5.02V", 5.02),
    (":MEASURE:CHANNEL1:MAXIMUM:VALUE 5.02E+00", 5.02),   # reply with a header
])
def test_parse_number_accepts_normal_replies(reply, value):
    assert parse_number(reply, unit="V") == pytest.approx(value)


@pytest.mark.parametrize("reply", ["9.91E+37", "9.9E37", "-9.9E+37", "NAN", "nan"])
def test_parse_number_scpi_no_value_becomes_nan(reply):
    # 9.91E37 is SCPI's "not a number"; it must not look like a real 9.9e37 V.
    assert math.isnan(parse_number(reply, unit="V"))


@pytest.mark.parametrize("reply", ["", "garbage", "OK", "5.0.2", "#9xyz", None])
def test_parse_number_garbage_is_bad_reply(reply):
    with pytest.raises(StopRunError) as e:
        parse_number(reply, unit="V")
    assert e.value.code == "BAD_REPLY"


def test_parse_number_wrong_unit():
    # Realistic case: the query went to the current channel / wrong measurement
    # and the scope answers in amps instead of volts.
    with pytest.raises(StopRunError) as e:
        parse_number("1.500E+00A", unit="V", what="CH1 max")
    assert e.value.code == "WRONG_UNIT"
    assert "CH1 max" in e.value.reason


# ---- judge_upper: VDS max vs limit ------------------------------------- #
def test_upper_pass_and_fail():
    assert judge_upper(568.0, 585.0).result == PASS
    j = judge_upper(600.0, 585.0)
    assert j.result == FAIL and j.code == "" and "600.0" in j.reason


@pytest.mark.parametrize("value", [float("nan"), None, float("inf"), "", "568"])
def test_upper_no_valid_reading_is_error_never_pass(value):
    # Note: nan > 585 is False, so the old "FAIL if > limit else PASS" logic
    # would have said PASS here.
    j = judge_upper(value, 585.0)
    assert j.result == ERROR and j.code == "NO_READING"


@pytest.mark.parametrize("limit", [0, -5, float("nan"), None])
def test_upper_bad_limit_is_bad_config(limit):
    j = judge_upper(400.0, limit)
    assert j.result == ERROR and j.code == "BAD_CONFIG"


def test_clipped_above_limit_is_fail_shown_as_at_least_x():
    j = judge_upper(700.0, 585.0, clipped=True, screen_top=700.0)
    assert j.result == FAIL
    assert j.shown == "≥ 700.0"            # the true peak is even higher


def test_clipped_below_limit_is_error_clipped():
    j = judge_upper(500.0, 585.0, clipped=True, screen_top=500.0)
    assert j.result == ERROR and j.code == "CLIPPED"


def test_clipped_with_unknown_full_scale_is_error():
    j = judge_upper(700.0, 585.0, clipped=True, screen_top=float("nan"))
    assert j.result == ERROR and j.code == "CLIPPED"


@pytest.mark.parametrize("reading, top, clipped", [
    (400.0, 800.0, False),
    (799.0, 800.0, True),                  # within 2 % of the top
    (800.0, 800.0, True),
    (400.0, float("nan"), True),           # top unknown -> assume clipped (safe side)
    (float("nan"), 800.0, False),          # no reading -> NO_READING, not CLIPPED
])
def test_clip_check(reading, top, clipped):
    assert clip_check(reading, top) is clipped


# ---- judge_window: Dynamic Vmin / Vmax --------------------------------- #
def test_window_results():
    assert judge_window(4.9, 5.1, 4.75, 5.25).result == PASS
    low = judge_window(4.5, 5.1, 4.75, 5.25)
    assert low.result == FAIL and "Vmin" in low.reason
    high = judge_window(4.9, 5.4, 4.75, 5.25)
    assert high.result == FAIL and "Vmax" in high.reason


@pytest.mark.parametrize("vmin, vmax", [(float("nan"), 5.1), (4.9, float("nan")),
                                        (None, None), (5.2, 4.8)])
def test_window_invalid_reading_is_error(vmin, vmax):
    j = judge_window(vmin, vmax, 4.75, 5.25)
    assert j.result == ERROR and j.code == "NO_READING"


# ---- the same rules through a full simulated run ----------------------- #
def _run(test_id, tmp_path, **sim):
    t = testtypes.get_test(test_id)
    cfg = t.default_config()
    cfg["simulation"] = sim
    return run_test(t, cfg, simulate=True, output_root=str(tmp_path))


@pytest.mark.parametrize("test_id", ["vds_turnoff", "vds_ovp", "dynamic_output_response"])
def test_scope_no_value_is_error_in_every_test(test_id, tmp_path):
    res = _run(test_id, tmp_path, scope_nan=True)
    assert res.rows and all(r["result"] == ERROR for r in res.rows)
    assert {r["error_code"] for r in res.rows} == {"NO_READING"}
    assert res.overall == ERROR


def test_scope_range_limit_below_limit_is_error_not_pass(tmp_path):
    # The scope can only show 500 V; the real peak is ~568 V. The app asked for
    # a bigger range, so the OLD clip check (using the app's own number) would
    # think "not clipped" and PASS a 500 V reading. Reading the range back from
    # the scope shows the capture is clipped below the 585 V limit -> ERROR.
    res = _run("vds_turnoff", tmp_path, scope_max_top=500)
    row = res.rows[0]
    assert row["result"] == ERROR and row["error_code"] == "CLIPPED"
    assert row["clipped"] is True


def test_scope_range_limit_above_limit_is_fail_at_least_x(tmp_path):
    # Real peak ~1420 V, scope can only show 700 V, limit 585 V: even the clipped
    # value is above the limit, so it's a real FAIL, recorded as "≥ 700.0".
    res = _run("vds_turnoff", tmp_path, scope_max_top=700, vds_spike_factor=3.0)
    row = res.rows[0]
    assert row["result"] == FAIL
    assert row["vds_max_v"] == "≥ 700.0"
    assert row["retries"] == 3              # it tried all retries first
