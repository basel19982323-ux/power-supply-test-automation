"""PowerPoint report builder — default layout and template-base mode.

Default: a title slide plus one slide per test point (waveform + key numbers).
Template mode: open the company deck as the base Presentation so its theme,
master, colors, and logo carry through, then add the same content slides. When
the real template arrives, per-placeholder mapping can be layered on here.
"""
import os

from pptx import Presentation
from pptx.util import Inches, Pt


def build_pptx(rows, test, config, out_path, run_dir, template=None):
    prs = Presentation(template) if template else Presentation()
    summary = test.summarize(rows)
    date = rows[0]["timestamp"][:10] if rows else ""

    # ---- title slide ---- #
    title_layout = prs.slide_layouts[0]
    s = prs.slides.add_slide(title_layout)
    if s.shapes.title is not None:
        s.shapes.title.text = test.name
    subtitle = (f"{config.get('dut_name', '')}  |  {date}\n"
                f"{summary['total']} test points: "
                f"{summary['pass']} PASS, {summary['fail']} FAIL")
    _set_subtitle(s, subtitle)

    # ---- one slide per test point ---- #
    blank = _blank_layout(prs)
    cols = test.result_columns
    # Slide title = the point's identity (e.g. "5V | 90Vac/60Hz") + result;
    # the error code and reason go in the side text, not the title.
    text_cols = [c for c in cols if c.kind == "text"
                 and c.key not in ("error_code", "reason")]
    for row in rows:
        s = prs.slides.add_slide(blank)

        heading = " | ".join(str(row.get(c.key, "")) for c in text_cols[:2])
        heading = f"{heading} | {row.get('result', '')}".strip(" |")
        tb = s.shapes.add_textbox(Inches(0.4), Inches(0.2), Inches(9.2), Inches(0.6))
        p = tb.text_frame.paragraphs[0]
        p.text = heading or "Test point"
        p.font.size = Pt(20)
        p.font.bold = True

        shot = os.path.join(run_dir, row.get("screenshot", "") or "")
        if row.get("screenshot") and os.path.exists(shot):
            s.shapes.add_picture(shot, Inches(0.6), Inches(1.0), width=Inches(6.8))
        else:
            miss = s.shapes.add_textbox(Inches(0.6), Inches(2.5), Inches(6), Inches(1))
            miss.text_frame.text = "(screenshot missing)"

        side = s.shapes.add_textbox(Inches(7.6), Inches(1.1), Inches(2.3), Inches(4))
        tf = side.text_frame
        tf.word_wrap = True
        first = True
        for col in cols:
            line = f"{col.label}: {row.get(col.key, '')}"
            if first:
                tf.text = line
                first = False
            else:
                tf.add_paragraph().text = line
        for para in tf.paragraphs:
            para.font.size = Pt(13)

    prs.save(out_path)
    return out_path


def _set_subtitle(slide, text):
    """Write into the subtitle/body placeholder if the layout has one."""
    for ph in slide.placeholders:
        if ph.placeholder_format.idx == 1:
            ph.text = text
            return
    box = slide.shapes.add_textbox(Inches(0.5), Inches(3.0), Inches(9), Inches(1.5))
    box.text_frame.text = text


def _blank_layout(prs):
    """Pick a blank-ish layout: prefer one named 'Blank', else fewest placeholders."""
    best, best_count = None, 1e9
    for layout in prs.slide_layouts:
        if (layout.name or "").strip().lower() == "blank":
            return layout
        n = len(layout.placeholders)
        if n < best_count:
            best, best_count = layout, n
    return best or prs.slide_layouts[-1]
