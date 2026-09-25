"""Best-effort extraction of a MOSFET's V_DS (drain-source) voltage rating from a
datasheet PDF.

Datasheets vary enormously, so this never silently picks a number for pass/fail
— it returns ranked candidate ratings and the UI asks the operator to confirm
one. Manual entry is always the fallback.
"""
import re

# Labels that denote the drain-source voltage rating (not VGS, which is separate).
_LABELS = [
    r"V\s*\(?\s*BR\s*\)?\s*DSS",              # V(BR)DSS
    r"V\s*DSS?",                              # VDS / VDSS
    r"Drain[-\s]*(?:to[-\s]*)?Source\s*Voltage",
    r"Drain[-\s]*Source\s*Breakdown\s*Voltage",
]
_LABEL_RE = re.compile("|".join(_LABELS), re.IGNORECASE)
_VOLT_RE = re.compile(r"(\d{2,4})\s*V\b")


def extract_text(pdf_path):
    """Return all extractable text from the PDF (empty string if unreadable)."""
    from pypdf import PdfReader

    reader = PdfReader(pdf_path)
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            pass
    return "\n".join(parts)


def rank_candidates(text, vmin=20, vmax=2000):
    """Rank VDS-rating candidates from already-extracted text.

    Looks for a voltage value in a small window around each drain-source-voltage
    label. Ranked largest-first (the breakdown rating is usually the biggest
    VDS-labelled number). Returns [{'value': float, 'context': str}], best first.
    """
    text = re.sub(r"[ \t]+", " ", text or "")
    candidates = {}
    for m in _LABEL_RE.finditer(text):
        window = text[max(0, m.start() - 20): m.end() + 60]
        for vm in _VOLT_RE.finditer(window):
            val = float(vm.group(1))
            if vmin <= val <= vmax and val not in candidates:
                candidates[val] = " ".join(window.split())[:80]
    ranked = sorted(candidates.items(), key=lambda kv: -kv[0])
    return [{"value": v, "context": c} for v, c in ranked]


def extract_vds_rating(pdf_path, vmin=20, vmax=2000):
    """Extract VDS-rating candidates from a datasheet PDF (best first)."""
    return rank_candidates(extract_text(pdf_path), vmin=vmin, vmax=vmax)
