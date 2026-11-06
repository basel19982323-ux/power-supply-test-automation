"""Probe check (rule 4): an impossible steady-state reading is ERROR
PROBE_CHECK, found BEFORE the AC is cut or the OVP event is started."""
import pytest

import testtypes
from core.instruments.factory import build_instruments
from core.runner import run_test
from core.test_base import RunContext
from core.verdict import ERROR, PointError
from testtypes.common import check_steady_output, check_steady_vds


def _run(test_id, tmp_path, **sim):
    t = testtypes.get_test(test_id)
    cfg = t.default_config()
    cfg["simulation"] = sim
    return run_test(t, cfg, simulate=True, output_root=str(tmp_path))


# ---- the rule itself ----------------------------------------------------- #
@pytest.mark.parametrize("value", [473.0, 200.0, 900.0])   # 230 Vac: AC peak 325 V, range 163..976 V
def test_possible_steady_vds_passes_the_check(value):
    assert check_steady_vds(value, 230, {}) == value


@pytest.mark.parametrize("value, hint", [
    (0.3, "probe disconnected"),      # about 0 V: probe not connected
    (100.0, "probe disconnected"),    # below the bulk voltage: impossible while running
    (4730.0, "attenuation"),          # 10x too high: probe ratio set wrong
])
def test_impossible_steady_vds_is_probe_check(value, hint):
    with pytest.raises(PointError) as e:
        check_steady_vds(value, 230, {})
    assert e.value.code == "PROBE_CHECK" and hint in e.value.reason


def test_probe_check_limits_come_from_the_config():
    with pytest.raises(PointError):
        check_steady_vds(473.0, 230, {"probe_check_max_x": 1.2})   # 473 > 1.2 x 325


def test_nan_steady_vds_is_no_reading():
    with pytest.raises(PointError) as e:
        check_steady_vds(float("nan"), 230, {})
    assert e.value.code == "NO_READING"


@pytest.mark.parametrize("vout", [0.0, 5.0, 22.0, 30.0])
def test_ovp_steady_output_must_be_normal_and_below_the_trigger(vout):
    with pytest.raises(PointError) as e:
        check_steady_output(vout, expected_v=20.0, trigger_v=22.0)
    assert e.value.code == "PROBE_CHECK"
    assert check_steady_output(20.0, expected_v=20.0, trigger_v=22.0) == 20.0


# ---- through a simulated run ---------------------------------------------- #
@pytest.mark.parametrize("test_id", ["vds_turnoff", "vds_ovp"])
def test_disconnected_probe_is_error_probe_check(test_id, tmp_path):
    res = _run(test_id, tmp_path, probe_disconnected=True)
    assert res.rows and all(r["result"] == ERROR for r in res.rows)
    assert {r["error_code"] for r in res.rows} == {"PROBE_CHECK"}


@pytest.mark.parametrize("steady_out", [5.0, 25.0])
def test_ovp_wrong_output_reading_is_probe_check(steady_out, tmp_path):
    res = _run("vds_ovp", tmp_path, steady_out=steady_out)
    assert res.rows[0]["result"] == ERROR
    assert res.rows[0]["error_code"] == "PROBE_CHECK"


def test_probe_check_happens_before_ac_is_cut(tmp_path):
    t = testtypes.get_test("vds_turnoff")
    cfg = t.default_config()
    cfg["simulation"] = {"probe_disconnected": True}
    inst = build_instruments(t.required_instruments, cfg, simulate=True)
    armed = []
    inst["scope"].arm_single = lambda: armed.append(True) or True
    ctx = RunContext(run_dir=str(tmp_path), screenshot_dir=str(tmp_path), simulate=True,
                     prompt=lambda m: None, status=lambda m: None)
    with pytest.raises(PointError):
        t.execute_point(t.plan(cfg)[0], inst, cfg, ctx)
    assert armed == []                         # never armed, never measured a "turn-off"
    assert inst["ac_source"].bench.ac_on is False   # and the DUT was left off
