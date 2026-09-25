"""Helpers for running an ordered suite of tests in succession.

A "step" is a small dict: {"test_id": str, "config_path": str|None, "name": str}.
resolve_step() turns it into a (TestType, config) pair; make_sequence_dir()
creates one parent folder so every step's run lands together. The actual loop
(threaded, with live signals) lives in ui/sequence_worker.py and reuses
core.runner.run_test for each step.
"""
import os
from datetime import datetime

from .config import load_config
from .results import OUTPUT_ROOT


def make_sequence_dir(output_root=None):
    root = output_root or OUTPUT_ROOT
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(root, "sequences", f"SEQ_{stamp}")
    os.makedirs(path, exist_ok=True)
    return path


def resolve_step(step):
    """Return (test, config) for a step. Uses the step's saved config file if
    present, otherwise the test's built-in defaults."""
    import testtypes

    test = testtypes.get_test(step["test_id"])
    cfg_path = step.get("config_path")
    if cfg_path and os.path.exists(cfg_path):
        config = load_config(cfg_path)
    else:
        config = test.default_config()
    return test, config


def step_label(step):
    """Human label for the steps list, e.g. 'VDS Max — AC Turn-off  ·  high-line'."""
    import testtypes

    try:
        name = testtypes.get_test(step["test_id"]).name
    except Exception:
        name = step.get("test_id", "?")
    cfg = step.get("name") or "(built-in defaults)"
    return f"{name}  ·  {cfg}"
