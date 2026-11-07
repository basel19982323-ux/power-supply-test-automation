"""Excel report builder — default layout and template-fill mode."""
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.utils.cell import coordinate_to_tuple

from core.run_mode import LIVE, UNKNOWN
from core.verdict import NOT_RUN, overall, result_color

_BOLD = Font(bold=True)


def _fill(result):
    """PASS green, FAIL red, ERROR amber, NOT RUN grey."""
    return PatternFill("solid", fgColor=result_color(result))


_NOT_LIVE = PatternFill("solid", fgColor="FFEB9C")   # amber: not real measurements


def build_excel(rows, test, config, out_path, template=None, mapping=None, run_info=None):
    run_info = run_info or {"mode": UNKNOWN, "note": "", "instruments": {}, "shutdown": {}}
    if template:
        return _fill_template(rows, test, config, out_path, template, mapping or {},
                              run_info)
    return _default(rows, test, config, out_path, run_info)


def _num(value, digits=None):
    """Coerce CSV strings back to numbers where possible (for real cell types)."""
    if value in ("", None):
        return value
    try:
        f = float(value)
    except (TypeError, ValueError):
        return value
    if f.is_integer() and digits is None:
        return int(f)
    return round(f, digits) if digits is not None else f


def _default(rows, test, config, out_path, run_info):
    wb = Workbook()
    summary = test.summarize(rows)
    date = rows[0]["timestamp"][:10] if rows else ""

    ws = wb.active
    ws.title = "Summary"
    ws["A1"] = f"{test.name} — Summary"
    ws["A1"].font = Font(bold=True, size=14)
    result = overall(rows)
    for i, (k, v) in enumerate([
        ("DUT", config.get("dut_name", "")),
        ("Test points", summary["total"]),
        ("PASS", summary["pass"]),
        ("FAIL", summary["fail"]),
        ("ERROR", summary["error"]),
        ("NOT RUN", summary["not_run"]),
        ("Overall result", result),
        ("Date", date),
        ("Run mode", run_info["mode"]),
    ], start=3):
        ws.cell(i, 1, k).font = _BOLD
        cell = ws.cell(i, 2, v)
        if k == "Overall result":
            cell.fill = _fill(result)
            cell.font = _BOLD
        if k == "Run mode":
            cell.font = _BOLD
            if v != LIVE:
                cell.fill = _NOT_LIVE
    ws["A12"] = ("PASS only if every point is PASS. ERROR = the measurement could not "
                 "be trusted (see Code / Reason). NOT RUN = never measured.")
    ws["A13"] = f"Run mode: {run_info['mode']} - {run_info['note']}"
    # How each instrument was judged, and its state at the end (sent vs confirmed).
    ws.cell(15, 1, "Instrument").font = _BOLD
    ws.cell(15, 2, "Mode").font = _BOLD
    ws.cell(15, 3, "Why").font = _BOLD
    ws.cell(15, 4, "At the end of the run").font = _BOLD
    roles = list(run_info["instruments"]) + [r for r in run_info["shutdown"]
                                             if r not in run_info["instruments"]]
    for r_i, role in enumerate(roles, 16):
        inst = run_info["instruments"].get(role, {})
        ws.cell(r_i, 1, role)
        ws.cell(r_i, 2, inst.get("kind", ""))
        ws.cell(r_i, 3, "; ".join(inst.get("why", [])))
        ws.cell(r_i, 4, run_info["shutdown"].get(role, {}).get("state", ""))

    ws2 = wb.create_sheet("Results")
    cols = test.result_columns
    for c, col in enumerate(cols, 1):
        ws2.cell(1, c, col.label).font = _BOLD
    for r_i, row in enumerate(rows, 2):
        for c_i, col in enumerate(cols, 1):
            val = row.get(col.key, "")
            if col.kind == "number":
                val = _num(val, col.digits)
            cell = ws2.cell(r_i, c_i, val)
            if col.kind == "result":
                cell.fill = _fill(row.get("result", NOT_RUN))
    for c in range(1, len(cols) + 1):
        ws2.column_dimensions[get_column_letter(c)].width = 15

    wb.save(out_path)
    return out_path


def _fill_template(rows, test, config, out_path, template, mapping, run_info):
    """Fill a company .xlsx. `mapping` (see mapping.example.yaml):
        summary_sheet, cells{key: A1}, results_sheet, results_start_cell.
    Missing pieces are simply skipped, so a partial mapping still works."""
    wb = load_workbook(template)
    summary = test.summarize(rows)
    data = {
        "dut": config.get("dut_name", ""),
        "date": rows[0]["timestamp"][:10] if rows else "",
        "total": summary["total"],
        "pass": summary["pass"],
        "fail": summary["fail"],
        "error": summary["error"],
        "not_run": summary["not_run"],
        "overall": overall(rows),
        "mode": run_info["mode"],
    }

    ss = mapping.get("summary_sheet")
    if ss and ss in wb.sheetnames:
        ws = wb[ss]
        for key, ref in (mapping.get("cells") or {}).items():
            ws[ref] = data.get(key, "")

    rs = mapping.get("results_sheet")
    if rs and rs in wb.sheetnames:
        ws = wb[rs]
        r0, c0 = coordinate_to_tuple(mapping.get("results_start_cell", "A2"))
        for i, row in enumerate(rows):
            for j, key in enumerate(test.csv_fields):
                ws.cell(r0 + i, c0 + j, _num(row.get(key, "")))

    wb.save(out_path)
    return out_path
