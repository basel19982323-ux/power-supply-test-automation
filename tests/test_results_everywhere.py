"""Rule 11: ERROR and NOT RUN are shown everywhere - Excel, template filling,
PPTX, CSV, Sequence (and its report) and the CLI exit code."""
import os

import pytest
from openpyxl import Workbook, load_workbook
from pptx import Presentation

import cli
import core.runner
import reporting
import testtypes
from core.config import save_config
from core.results import new_run_dir, read_csv
from core.runner import run_test
from core.sequence import run_sequence
from core.verdict import (ERROR, FAIL, NOT_RUN, PASS, RESULT_COLORS, counts_text,
                          result_color)
from reporting.sequence import generate_sequence_reports


def _run(test_id, tmp_path, **sim):
    t = testtypes.get_test(test_id)
    cfg = t.default_config()
    cfg["simulation"] = sim
    return t, cfg, run_test(t, cfg, simulate=True, output_root=str(tmp_path))


def _mixed(tmp_path):
    """Dynamic run that stops on point 1 (sanity abort): 1 ERROR + 15 NOT RUN."""
    return _run("dynamic_output_response", tmp_path, reading_scale=10)


# ---- shared helpers ------------------------------------------------------- #
def test_counts_text_always_shows_all_four():
    s = {"total": 4, "pass": 1, "fail": 1, "error": 1, "not_run": 1}
    assert counts_text(s) == "1 PASS / 1 FAIL / 1 ERROR / 1 NOT RUN of 4"


def test_every_result_has_its_own_colour_and_unknown_looks_like_error():
    assert len(set(RESULT_COLORS.values())) == 4
    assert result_color("weird") == RESULT_COLORS[ERROR]


# ---- CSV ------------------------------------------------------------------ #
def test_csv_keeps_error_and_not_run_with_codes(tmp_path):
    _, _, res = _mixed(tmp_path)
    rows = read_csv(res.csv_path)
    assert rows[0]["result"] == ERROR and rows[0]["error_code"] == "SANITY_ABORT"
    assert rows[1]["result"] == NOT_RUN and rows[1]["error_code"] == "RUN_ENDED_EARLY"


# ---- Excel ---------------------------------------------------------------- #
def test_excel_summary_counts_and_colours(tmp_path):
    t, cfg, res = _mixed(tmp_path)
    paths = reporting.generate(res.run_dir, t, cfg, rows=res.rows, pptx=False)
    wb = load_workbook(paths["excel"])
    summary = {wb["Summary"].cell(r, 1).value: wb["Summary"].cell(r, 2).value
               for r in range(3, 11)}
    assert summary["Test points"] == 16            # still B4, as before
    assert summary["ERROR"] == 1 and summary["NOT RUN"] == 15
    assert summary["Overall result"] == ERROR
    results = wb["Results"]
    col = [c.value for c in results[1]].index("Result") + 1
    assert results.cell(2, col).fill.fgColor.rgb.endswith(RESULT_COLORS[ERROR])
    assert results.cell(3, col).fill.fgColor.rgb.endswith(RESULT_COLORS[NOT_RUN])


def test_template_fill_has_error_not_run_and_overall(tmp_path):
    t, cfg, res = _mixed(tmp_path)
    tpl = tmp_path / "tpl.xlsx"
    wb = Workbook()
    wb.active.title = "Summary"
    wb.save(tpl)
    mapping = {"excel": {"summary_sheet": "Summary",
                         "cells": {"error": "B7", "not_run": "B8", "overall": "B9"}}}
    paths = reporting.generate(res.run_dir, t, cfg, rows=res.rows, pptx=False,
                               template_excel=str(tpl), mapping=mapping)
    ws = load_workbook(paths["excel"])["Summary"]
    assert (ws["B7"].value, ws["B8"].value, ws["B9"].value) == (1, 15, ERROR)


# ---- PPTX ----------------------------------------------------------------- #
def _slide_text(slide):
    return "\n".join(sh.text_frame.text for sh in slide.shapes if sh.has_text_frame)


def test_pptx_shows_counts_overall_and_why_a_point_was_not_run(tmp_path):
    t, cfg, res = _mixed(tmp_path)
    paths = reporting.generate(res.run_dir, t, cfg, rows=res.rows, excel=False)
    slides = Presentation(paths["pptx"]).slides
    title = _slide_text(slides[0])
    assert "1 ERROR / 15 NOT RUN" in title and "Overall result: ERROR" in title
    assert "NOT RUN - this point was not measured" in _slide_text(slides[2])


# ---- Sequence ------------------------------------------------------------- #
def _config_file(tmp_path, test_id, name, **sim):
    cfg = testtypes.get_test(test_id).default_config()
    cfg["simulation"] = sim
    path = str(tmp_path / f"{name}.yaml")
    save_config(cfg, path)
    return path


def test_sequence_step_that_cannot_load_is_not_run(tmp_path):
    steps = [{"test_id": "vds_turnoff", "config_path": None},
             {"test_id": "vds_turnoff", "config_path": str(tmp_path / "deleted.yaml")},
             {"test_id": "vds_ovp", "config_path": None}]
    seq = run_sequence(steps, simulate=True, output_root=str(tmp_path), on_status=lambda m: None)
    assert [st["outcome"] for st in seq.steps] == [PASS, NOT_RUN, PASS]
    assert seq.steps[1]["code"] == "STEP_NOT_LOADED"
    assert seq.overall == NOT_RUN                 # not every step was PASS


def test_sequence_stops_after_a_bench_problem(tmp_path):
    bad = _config_file(tmp_path, "vds_turnoff", "bad", disconnect_ac_after=1)
    steps = [{"test_id": "vds_turnoff", "config_path": bad},
             {"test_id": "vds_ovp", "config_path": None}]
    seq = run_sequence(steps, simulate=True, output_root=str(tmp_path), on_status=lambda m: None)
    assert [st["outcome"] for st in seq.steps] == [ERROR, NOT_RUN]
    assert seq.steps[1]["code"] == "RUN_ENDED_EARLY"
    assert seq.overall == ERROR


def test_sequence_fail_wins(tmp_path):
    low = str(tmp_path / "low.yaml")
    cfg = testtypes.get_test("vds_turnoff").default_config()
    cfg["limits"]["fet_vds_rating_v"] = 500.0           # limit 450 V < 568 V
    save_config(cfg, low)
    steps = [{"test_id": "vds_turnoff", "config_path": low},
             {"test_id": "vds_ovp", "config_path": None}]
    seq = run_sequence(steps, simulate=True, output_root=str(tmp_path), on_status=lambda m: None)
    assert seq.steps[0]["outcome"] == FAIL and seq.overall == FAIL


def test_sequence_stop_before_start_marks_every_step_stopped(tmp_path):
    import threading
    stop = threading.Event()
    stop.set()
    steps = [{"test_id": "vds_turnoff", "config_path": None}] * 2
    seq = run_sequence(steps, simulate=True, abort_event=stop,
                       output_root=str(tmp_path), on_status=lambda m: None)
    assert [(st["outcome"], st["code"]) for st in seq.steps] == [(NOT_RUN, "STOPPED")] * 2


def test_sequence_report_lists_not_run_steps_and_the_sequence_result(tmp_path):
    steps = [{"test_id": "vds_turnoff", "config_path": None},
             {"test_id": "vds_turnoff", "config_path": str(tmp_path / "deleted.yaml")}]
    seq = run_sequence(steps, simulate=True, output_root=str(tmp_path), on_status=lambda m: None)
    paths = generate_sequence_reports(seq.seq_dir, seq.steps)
    ws = load_workbook(paths["summary"])["Sequence"]
    assert ws["B2"].value == NOT_RUN                        # sequence result
    header = [c.value for c in ws[3]]
    assert header[:8] == ["#", "Test", "Points", "PASS", "FAIL", "ERROR", "NOT RUN",
                          "Result"]
    assert ws.cell(4, 8).value == PASS
    assert (ws.cell(5, 8).value, ws.cell(5, 9).value) == (NOT_RUN, "STEP_NOT_LOADED")
    assert paths["step_errors"] == []


# ---- CLI exit code = overall result --------------------------------------- #
@pytest.fixture
def cli_out(tmp_path, monkeypatch):
    monkeypatch.setattr(core.runner, "new_run_dir",
                        lambda dut, root=None: new_run_dir(dut, str(tmp_path / "out")))
    return tmp_path


@pytest.mark.parametrize("sim, rating, code", [
    ({}, 650.0, 0),                                  # PASS
    ({}, 500.0, 1),                                  # FAIL
    ({"scope_never_triggers": True}, 650.0, 2),      # ERROR
])
def test_cli_exit_code(cli_out, capsys, sim, rating, code):
    cfg = testtypes.get_test("vds_turnoff").default_config()
    cfg["simulation"] = sim
    cfg["limits"]["fet_vds_rating_v"] = rating
    path = str(cli_out / "cfg.yaml")
    save_config(cfg, path)
    assert cli.main(["--test", "vds_turnoff", "--config", path, "--simulate"]) == code
    assert "Overall result:" in capsys.readouterr().out
    assert os.listdir(cli_out / "out")               # the run went to tmp, not output/
