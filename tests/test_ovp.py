"""VDS-at-OVP test: plan and simulated capture (CH2-triggered, with e-load)."""
import testtypes
from core.runner import run_test


def test_ovp_plan():
    t = testtypes.get_test("vds_ovp")
    plan = t.plan(t.default_config())
    assert len(plan) == 1
    assert plan[0]["ac_condition"] == "230Vac/50Hz"


def test_ovp_sim_pass(tmp_path):
    t = testtypes.get_test("vds_ovp")
    res = run_test(t, t.default_config(), simulate=True, output_root=str(tmp_path))
    assert res.error is None and res.aborted is False
    assert res.summary == {"total": 1, "pass": 1, "fail": 0}
    row = res.rows[0]
    assert row["load_a"] == 1.0
    assert abs(row["vout_ovp_v"] - 28.0) < 0.1     # output peak at OVP (CH2)
    assert row["clipped"] is False
    # VDS at OVP: 230*1.414+100 = 425.3; x1.3 = 552.9; limit 585 -> PASS
    assert 540 < row["vds_max_v"] < 565
    assert row["result"] == "PASS"


def test_ovp_fail_when_rating_low(tmp_path):
    t = testtypes.get_test("vds_ovp")
    cfg = t.default_config()
    cfg["limits"] = {"fet_vds_rating_v": 500.0, "derating_pct": 90.0}  # limit 450 V
    res = run_test(t, cfg, simulate=True, output_root=str(tmp_path))
    assert res.rows[0]["result"] == "FAIL"          # ~553 V > 450 V
