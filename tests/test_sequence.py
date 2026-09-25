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
