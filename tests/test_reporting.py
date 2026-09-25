"""Reporting tests: default layout and Excel template-fill."""
from openpyxl import Workbook, load_workbook
from pptx import Presentation

import reporting
import testtypes
from core.runner import run_test


def _sim_run(tmp_path):
    t = testtypes.default_test()
    cfg = t.default_config()
    res = run_test(t, cfg, simulate=True, output_root=str(tmp_path))
    return t, cfg, res


def test_default_reports(tmp_path):
    t, cfg, res = _sim_run(tmp_path)
    paths = reporting.generate(res.run_dir, t, cfg, rows=res.rows)
    wb = load_workbook(paths["excel"])
    assert wb.sheetnames == ["Summary", "Results"]
    assert wb["Results"].max_row == 17          # header + 16
    assert wb["Summary"]["B4"].value == 16      # test points
    assert len(Presentation(paths["pptx"]).slides) == 17  # title + 16


def test_excel_template_fill(tmp_path):
    t, cfg, res = _sim_run(tmp_path)
    # a bare "company" template with the two sheets the mapping references
    tpl = tmp_path / "tpl.xlsx"
    wb = Workbook()
    wb.active.title = "Summary"
    wb.create_sheet("Results")
    wb.save(tpl)

    mapping = {"excel": {
        "summary_sheet": "Summary",
        "cells": {"dut": "B2", "total": "B4", "pass": "B5", "fail": "B6"},
        "results_sheet": "Results",
        "results_start_cell": "A2",
    }}
    paths = reporting.generate(res.run_dir, t, cfg, rows=res.rows, pptx=False,
                               template_excel=str(tpl), mapping=mapping)
    out = load_workbook(paths["excel"])
    assert out["Summary"]["B4"].value == 16
    assert out["Summary"]["B2"].value == cfg["dut_name"]
    assert out["Results"].max_row == 17         # rows written A2..A17
