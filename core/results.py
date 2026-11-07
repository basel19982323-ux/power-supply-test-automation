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
    base = os.path.join(output_root, f"{_safe(dut_name)}_{stamp}")
    os.makedirs(output_root, exist_ok=True)
    # Two runs started in the same second (quick simulated runs, Sequence
    # steps) must not share a folder - they would overwrite each other's
    # results.csv and reports. os.mkdir fails if the folder already exists.
    for n in range(1, 1000):
        run_dir = base if n == 1 else f"{base}_{n}"
        try:
            os.mkdir(run_dir)
            break
        except FileExistsError:
            continue
    else:
        raise OSError(f"could not create a new run folder next to {base}")
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
