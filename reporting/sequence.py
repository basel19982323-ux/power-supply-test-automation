"""Combined report for a test sequence: per-step Excel/PPTX plus a top-level
summary workbook listing every step's outcome."""
import os

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from . import generate

_GREEN = PatternFill("solid", fgColor="C6EFCE")
_RED = PatternFill("solid", fgColor="FFC7CE")
_AMBER = PatternFill("solid", fgColor="FFEB9C")


def generate_sequence_reports(seq_dir, results, per_step=True):
    """Generate a summary workbook (+ optional per-step reports). Returns paths."""
    out = {}
    if per_step:
        for step in results:
            r = step["result"]
            try:
                generate(r.run_dir, step["test"], step["config"], rows=r.rows)
            except Exception:
                pass
    out["summary"] = _summary(seq_dir, results)
    return out


def _summary(seq_dir, results):
    wb = Workbook()
    ws = wb.active
    ws.title = "Sequence"
    ws["A1"] = "Test Sequence Summary"
    ws["A1"].font = Font(bold=True, size=14)

    headers = ["#", "Test", "Points", "PASS", "FAIL", "Outcome", "Run folder"]
    for c, h in enumerate(headers, 1):
        ws.cell(3, c, h).font = Font(bold=True)

    for i, step in enumerate(results, 1):
        r = step["result"]
        s = r.summary
        if r.error:
            outcome, fill = "ERROR", _AMBER
        elif r.aborted:
            outcome, fill = "ABORTED", _AMBER
        elif s["fail"] == 0:
            outcome, fill = "PASS", _GREEN
        else:
            outcome, fill = "FAIL", _RED
        row = 3 + i
        ws.cell(row, 1, i)
        ws.cell(row, 2, step["name"])
        ws.cell(row, 3, s["total"])
        ws.cell(row, 4, s["pass"])
        ws.cell(row, 5, s["fail"])
        ws.cell(row, 6, outcome).fill = fill
        ws.cell(row, 7, os.path.basename(r.run_dir))

    for col in "ABCDEFG":
        ws.column_dimensions[col].width = 18
    path = os.path.join(seq_dir, "sequence_summary.xlsx")
    wb.save(path)
    return path
