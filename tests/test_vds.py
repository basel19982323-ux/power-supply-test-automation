"""VDS Turn-off test: plan, simulated pass/fail, and auto-range retry."""
import testtypes
from core.runner import run_test


def test_vds_plan():
    t = testtypes.get_test("vds_turnoff")
    plan = t.plan(t.default_config())
    assert len(plan) == 2
    assert plan[0]["ac_condition"] == "264Vac/50Hz"


def test_vds_sim_pass(tmp_path):
    t = testtypes.get_test("vds_turnoff")
    res = run_test(t, t.default_config(), simulate=True, output_root=str(tmp_path))
    assert res.error is None and res.aborted is False
    assert res.summary["total"] == 2 and res.summary["fail"] == 0
    for row in res.rows:
        assert row["clipped"] is False
        assert row["retries"] == 0


def test_vds_autorange_retry(tmp_path):
    t = testtypes.get_test("vds_turnoff")
    cfg = t.default_config()
    cfg["simulation"] = {"vds_reflected": 100.0, "vds_spike_factor": 3.0}
    cfg["ac_conditions"] = [{"label": "264Vac/50Hz", "voltage": 264, "frequency": 50}]
    res = run_test(t, cfg, simulate=True, output_root=str(tmp_path))
    row = res.rows[0]
    assert row["retries"] >= 1          # initial full-scale clipped -> widened
    assert row["clipped"] is False      # converged to an un-clipped capture
    assert row["vds_max_v"] > 1000      # ~1420 V captured
    assert row["result"] == "FAIL"      # far above the rating


def test_vds_fail_when_rating_low(tmp_path):
    t = testtypes.get_test("vds_turnoff")
    cfg = t.default_config()
    cfg["ac_conditions"] = [{"label": "264Vac/50Hz", "voltage": 264, "frequency": 50}]
    cfg["limits"] = {"fet_vds_rating_v": 500.0, "derating_pct": 90.0}  # limit 450 V
    res = run_test(t, cfg, simulate=True, output_root=str(tmp_path))
    assert res.rows[0]["result"] == "FAIL"   # ~568 V > 450 V
