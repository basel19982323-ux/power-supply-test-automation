"""Run-output persistence.

Each run gets its own timestamped folder so results never overwrite each other
(a change from the original single-file results.csv). Layout:

    output/<DUT>_<YYYYMMDD-HHMMSS>/
        results.csv
        screenshots/<...>.png
        (reports written here later by the reporting module)
"""
import csv
import os
import re
from datetime import datetime

from .paths import app_base

OUTPUT_ROOT = os.path.join(app_base(), "output")


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(name)).strip("_") or "run"


def new_run_dir(dut_name: str, output_root: str = OUTPUT_ROOT) -> str:
    """Create and return a fresh timestamped run folder (+ screenshots subdir)."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = os.path.join(output_root, f"{_safe(dut_name)}_{stamp}")
    os.makedirs(os.path.join(run_dir, "screenshots"), exist_ok=True)
    return run_dir


def write_csv(path: str, fields: list, rows: list) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return path


def read_csv(path: str) -> list:
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))
