"""Engine tests: registry, plan, limits, and simulated runs (no hardware, no Qt)."""
import os

import testtypes
from core.runner import run_test


def test_registry():
    ids = [t[0] for t in testtypes.list_tests()]
    assert "dynamic_output_response" in ids
    t = testtypes.get_test("dynamic_output_response")
    assert t.required_instruments == ["powerz", "ac_source", "e_load", "scope"]


def test_plan_yields_16_points_profile_first():
    t = testtypes.default_test()
    plan = t.plan(t.default_config())
    assert len(plan) == 16
    # PD profile is the outer loop: new_profile marks the first AC condition of
    # each of the 4 profiles, so the POWER-Z step happens once per voltage.
    firsts = [i for i, p in enumerate(plan) if p["new_profile"]]
    assert firsts == [0, 4, 8, 12]


def test_limits_default_tolerance():
    t = testtypes.default_test()
    cfg = t.default_config()
    point = t.plan(cfg)[0]              # 5 V nominal
    vmin_l, vmax_l = t._limits(cfg, point)
    assert round(vmin_l, 3) == 4.75
    assert round(vmax_l, 3) == 5.25


def test_limits_absolute_override():
    t = testtypes.default_test()
    cfg = t.default_config()
    cfg["limits"]["overrides"] = {"5V": {"vmin_abs": 4.9, "vmax_abs": 5.1}}
    point = t.plan(cfg)[0]
    assert t._limits(cfg, point) == (4.9, 5.1)


def test_run_sim_all_pass(tmp_path):
    t = testtypes.default_test()
    res = run_test(t, t.default_config(), simulate=True, output_root=str(tmp_path))
    assert res.error is None and res.aborted is False
    assert res.summary == {"total": 16, "pass": 16, "fail": 0, "error": 0, "not_run": 0}
    assert res.overall == "PASS"
    assert os.path.exists(res.csv_path)
    shots = os.listdir(os.path.join(res.run_dir, "screenshots"))
    assert len(shots) == 16


def test_run_sim_fault_profile_fails(tmp_path):
    t = testtypes.default_test()
    cfg = t.default_config()
    cfg["simulation"] = {"fault_profiles": ["9V"]}   # force 9V out of ±5%
    res = run_test(t, cfg, simulate=True, output_root=str(tmp_path))
    # 9V has 4 AC conditions → 4 FAIL, the other 12 PASS.
    assert res.summary["fail"] == 4
    assert res.summary["pass"] == 12
