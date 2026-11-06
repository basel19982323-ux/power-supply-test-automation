"""Combined report for a test sequence: per-step Excel/PPTX plus a top-level
summary workbook listing every step's result (PASS / FAIL / ERROR / NOT RUN)."""
import os

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from core.sequence import step_outcome
from core.verdict import combine, result_color

from . import generate

HEADERS = ["#", "Test", "Points", "PASS", "FAIL", "ERROR", "NOT RUN", "Result",
           "Code", "Reason", "Run folder"]


def generate_sequence_reports(seq_dir, results, per_step=True):
    """Generate a summary workbook (+ optional per-step reports). Returns paths.
    A per-step report that fails is listed in out["step_errors"] (not hidden)."""
    out = {"step_errors": []}
    if per_step:
        for step in results:
            r = step.get("result")
            if r is None:
                continue                      # NOT RUN step: nothing to report
            try:
                generate(r.run_dir, step["test"], step["config"], rows=r.rows)
            except Exception as e:  # noqa: BLE001 - keep going with the other steps
                out["step_errors"].append(f"{step['name']}: {type(e).__name__}: {e}")
    out["summary"] = _summary(seq_dir, results)
    return out


def _fill(result):
    return PatternFill("solid", fgColor=result_color(result))


def _summary(seq_dir, results):
    wb = Workbook()
    ws = wb.active
    ws.title = "Sequence"
    ws["A1"] = "Test Sequence Summary"
    ws["A1"].font = Font(bold=True, size=14)

    outcomes = [step_outcome(step) for step in results]
    seq_result = combine(o[0] for o in outcomes)
    ws["A2"] = "Sequence result"
    ws["A2"].font = Font(bold=True)
    ws["B2"] = seq_result
    ws["B2"].fill = _fill(seq_result)
    ws["B2"].font = Font(bold=True)

    for c, h in enumerate(HEADERS, 1):
        ws.cell(3, c, h).font = Font(bold=True)

    for i, (step, (outcome, code, reason)) in enumerate(zip(results, outcomes), 1):
        r = step.get("result")
        s = r.summary if r is not None else {}
        row = 3 + i
        values = [i, step["name"], s.get("total", ""), s.get("pass", ""),
                  s.get("fail", ""), s.get("error", ""), s.get("not_run", ""),
                  outcome, code, reason,
                  os.path.basename(r.run_dir) if r is not None else ""]
        for c, v in enumerate(values, 1):
            ws.cell(row, c, v)
        ws.cell(row, 8).fill = _fill(outcome)

    for c in range(1, len(HEADERS) + 1):
        ws.column_dimensions[ws.cell(3, c).column_letter].width = 14
    ws.column_dimensions["B"].width = 34
    ws.column_dimensions["J"].width = 60
    path = os.path.join(seq_dir, "sequence_summary.xlsx")
    wb.save(path)
    return path
