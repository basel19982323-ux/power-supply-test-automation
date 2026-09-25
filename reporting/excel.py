"""Excel report builder — default layout and template-fill mode."""
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.utils.cell import coordinate_to_tuple

_RED = PatternFill("solid", fgColor="FFC7CE")
_GREEN = PatternFill("solid", fgColor="C6EFCE")
_BOLD = Font(bold=True)


def build_excel(rows, test, config, out_path, template=None, mapping=None):
    if template:
        return _fill_template(rows, test, config, out_path, template, mapping or {})
    return _default(rows, test, config, out_path)


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


def _default(rows, test, config, out_path):
    wb = Workbook()
    summary = test.summarize(rows)
    date = rows[0]["timestamp"][:10] if rows else ""

    ws = wb.active
    ws.title = "Summary"
    ws["A1"] = f"{test.name} — Summary"
    ws["A1"].font = Font(bold=True, size=14)
    for i, (k, v) in enumerate([
        ("DUT", config.get("dut_name", "")),
        ("Test points", summary["total"]),
        ("PASS", summary["pass"]),
        ("FAIL", summary["fail"]),
        ("Date", date),
    ], start=3):
        ws.cell(i, 1, k).font = _BOLD
        ws.cell(i, 2, v)

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
                cell.fill = _GREEN if row.get("result") == "PASS" else _RED
    for c in range(1, len(cols) + 1):
        ws2.column_dimensions[get_column_letter(c)].width = 15

    wb.save(out_path)
    return out_path


def _fill_template(rows, test, config, out_path, template, mapping):
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
