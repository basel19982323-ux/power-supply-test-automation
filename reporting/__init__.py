"""Report generation: Excel + PowerPoint from a run's results.

Two modes per format:
  * default  — a clean built-in layout (summary + colored results; title slide +
               one slide per test point with the waveform and key numbers).
  * template — fill a company file. Excel: write into cells named by a mapping
               (see mapping.example.yaml). PPTX: use the company deck as the base
               so its theme/master branding carries through.

The data pipeline is identical either way, honoring the plan's "decide later":
drop a template into reporting/templates/, point the Report tab at it (+ a
mapping for Excel), and the same rows fill your format with no code change.
"""
import os

from core.results import read_csv

from .excel import build_excel
from .pptx import build_pptx


def generate(run_dir, test, config, rows=None, *, excel=True, pptx=True,
             template_excel=None, template_pptx=None, mapping=None):
    """Generate reports for a run folder. Returns {'excel': path, 'pptx': path}."""
    if rows is None:
        rows = read_csv(os.path.join(run_dir, "results.csv"))
    dut = config.get("dut_name", "DUT")
    mapping = mapping or {}
    out = {}
    if excel:
        out["excel"] = build_excel(
            rows, test, config, os.path.join(run_dir, f"{dut}_report.xlsx"),
            template=template_excel, mapping=mapping.get("excel"))
    if pptx:
        out["pptx"] = build_pptx(
            rows, test, config, os.path.join(run_dir, f"{dut}_report.pptx"),
            run_dir, template=template_pptx)
    return out
