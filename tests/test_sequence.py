"""Sequence resolution and combined-report generation (engine level, no Qt)."""
import os

from openpyxl import load_workbook

import testtypes
from core.runner import run_test
from core.sequence import resolve_step
from reporting.sequence import generate_sequence_reports


def test_resolve_step_default():
    test, cfg = resolve_step({"test_id": "vds_turnoff", "config_path": None})
    assert test.id == "vds_turnoff"
    assert "limits" in cfg


def test_sequence_reports(tmp_path):
    parent = str(tmp_path / "seq")
    os.makedirs(parent, exist_ok=True)
    results = []
    for tid in ["dynamic_output_response", "vds_turnoff"]:
        t = testtypes.get_test(tid)
        cfg = t.default_config()
        res = run_test(t, cfg, simulate=True, output_root=parent)
        results.append({"name": t.name, "test": t, "config": cfg, "result": res})

    paths = generate_sequence_reports(parent, results)
    assert os.path.exists(paths["summary"])
    ws = load_workbook(paths["summary"])["Sequence"]
    assert ws.cell(4, 2).value == results[0]["name"]
    assert ws.cell(5, 2).value == results[1]["name"]
    # each step also got its own Excel report
    for step in results:
        dut = step["config"]["dut_name"]
        assert os.path.exists(os.path.join(step["result"].run_dir, f"{dut}_report.xlsx"))


def test_runs_started_in_the_same_second_get_their_own_folders(tmp_path):
    from core.results import new_run_dir
    dirs = {new_run_dir("DUT-01", str(tmp_path)) for _ in range(3)}
    assert len(dirs) == 3                        # never the same folder twice


def test_quick_sequence_steps_do_not_overwrite_each_other(tmp_path):
    import os

    from core.results import read_csv
    from core.sequence import run_sequence
    steps = [{"test_id": "vds_turnoff", "config_path": None},
             {"test_id": "vds_ovp", "config_path": None}]
    seq = run_sequence(steps, simulate=True, output_root=str(tmp_path),
                       on_status=lambda m: None)
    first, second = (st["result"] for st in seq.steps)
    assert first.run_dir != second.run_dir
    assert len(read_csv(os.path.join(first.run_dir, "results.csv"))) == 2    # VDS: 2 points
    assert len(read_csv(os.path.join(second.run_dir, "results.csv"))) == 1   # OVP: 1 point
