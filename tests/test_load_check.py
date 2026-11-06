"""Load check (rule 6): if the e-load did not really draw its current, the
Dynamic / OVP result can't be trusted -> ERROR LOAD_NOT_REACHED."""
import pytest

import testtypes
from core.instruments.itech_load import ITechLoad
from core.runner import run_test
from core.verdict import ERROR, PASS, PointError, StopRunError
from testtypes.common import check_load_current


def _run(test_id, tmp_path, cfg_edit=None, **sim):
    t = testtypes.get_test(test_id)
    cfg = t.default_config()
    cfg["simulation"] = sim
    if cfg_edit:
        cfg_edit(cfg)
    return run_test(t, cfg, simulate=True, output_root=str(tmp_path))


# ---- the rule itself ----------------------------------------------------- #
def test_load_reached():
    assert check_load_current(1.48, 1.5, 90, "test") == 1.48     # 98.7 % is fine


@pytest.mark.parametrize("measured", [0.0, 0.75, 1.34])           # below 90 % of 1.5 A
def test_load_not_reached(measured):
    with pytest.raises(PointError) as e:
        check_load_current(measured, 1.5, 90, "0<->3 A transient")
    assert e.value.code == "LOAD_NOT_REACHED"
    assert e.value.values["load_avg_a"] == round(measured, 3)


def test_no_load_set_means_nothing_to_check():
    assert check_load_current(0.0, 0.0, 90, "no load") == 0.0


def test_load_reading_nan_is_no_reading():
    with pytest.raises(PointError) as e:
        check_load_current(float("nan"), 1.5, 90, "x")
    assert e.value.code == "NO_READING"


# ---- through a simulated run ---------------------------------------------- #
def test_dynamic_records_the_measured_load(tmp_path):
    res = _run("dynamic_output_response", tmp_path)
    assert {r["result"] for r in res.rows} == {PASS}
    assert res.rows[0]["load_avg_a"] == 1.5           # 0 <-> 3 A at 50 % duty


def test_dynamic_load_not_reached_is_error_and_the_run_continues(tmp_path):
    res = _run("dynamic_output_response", tmp_path, load_reach_factor=0.5)
    assert len(res.rows) == 16
    assert all(r["result"] == ERROR for r in res.rows)       # ERROR, not NOT RUN
    assert {r["error_code"] for r in res.rows} == {"LOAD_NOT_REACHED"}
    assert res.rows[0]["load_avg_a"] == 0.75


def test_ovp_static_load_not_reached(tmp_path):
    res = _run("vds_ovp", tmp_path, load_reach_factor=0.5)
    assert res.rows[0]["result"] == ERROR
    assert res.rows[0]["error_code"] == "LOAD_NOT_REACHED"


def test_load_check_percent_is_a_setting(tmp_path):
    def loose(cfg):
        cfg["e_load_settings"]["load_check_pct"] = 40
    res = _run("dynamic_output_response", tmp_path, cfg_edit=loose, load_reach_factor=0.5)
    assert {r["result"] for r in res.rows} == {PASS}          # 50 % >= 40 %


# ---- the real ITECH driver with a fake VISA connection ------------------- #
class _FakeVisa:
    def __init__(self, reply):
        self.reply = reply
        self.timeout = None

    def write(self, cmd):
        pass

    def query(self, cmd):
        return "ITECH,IT8800,FAKE,1.0" if cmd == "*IDN?" else self.reply

    def close(self):
        pass


def test_driver_reads_current_in_amps():
    assert ITechLoad(_FakeVisa("1.500A")).measure_current() == 1.5
    assert ITechLoad(_FakeVisa("1.5E+00")).measure_current() == 1.5


def test_driver_current_in_volts_is_wrong_unit():
    with pytest.raises(StopRunError) as e:
        ITechLoad(_FakeVisa("20.01V")).measure_current()   # answered the voltage
    assert e.value.code == "WRONG_UNIT"
