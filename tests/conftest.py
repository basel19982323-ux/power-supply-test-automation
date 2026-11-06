"""Put the application root on sys.path so tests import the top-level packages
(core, testtypes, reporting) the same way the app does.

Also: shared fixtures that run the REAL instrument drivers against the fake
SCPI bench (tools/fake_bench.py) over TCP."""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def fake_bench():
    """start(faults=None, **bench_settings) -> (bench, {role: VISA address}).
    Starts the three fake instruments on free ports; all are stopped after the test."""
    from tools import fake_bench as fb
    servers = []

    def start(faults=None, **settings):
        bench = fb.Bench(faults=faults, **settings)
        started = fb.start_servers(bench)
        servers.extend(started.values())
        return bench, {role: s.address for role, s in started.items()}

    yield start
    for s in servers:
        s.stop()


def quick_config(test_id, cfg):
    """Small, fast settings for fake-bench runs (no real DUT to wait for)."""
    if test_id == "dynamic_output_response":
        cfg["pd_profiles"] = cfg["pd_profiles"][:1]
        cfg["ac_conditions"] = cfg["ac_conditions"][:2]
        cfg["scope_settings"]["measure_cycles_wait_s"] = 0
    else:
        cfg["scope"]["settle_s"] = 0
        cfg["scope"]["trigger_timeout_s"] = 2
    return cfg


@pytest.fixture
def run_on_fake_bench(fake_bench, tmp_path, monkeypatch):
    """run(test_id, faults=None, cfg=None, **bench_settings) -> (result, bench, prompts)

    Runs a test type with the REAL drivers (simulate=False) against a fake bench.
    The drivers' fixed waits for a real DUT (AC settle, PD renegotiation) are
    skipped - there is no DUT; the scope's trigger polling is kept."""
    import core.instruments.itech_ac as itech_ac
    import core.instruments.itech_load as itech_load
    import core.instruments.powerz as powerz
    import testtypes
    from core.runner import run_test
    from core.test_base import Callbacks

    no_wait = types.SimpleNamespace(sleep=lambda s: None)
    for module in (itech_ac, itech_load, powerz):
        monkeypatch.setattr(module, "time", no_wait)

    def run(test_id, faults=None, cfg=None, **settings):
        t = testtypes.get_test(test_id)
        cfg = quick_config(test_id, cfg or t.default_config())
        bench, addrs = fake_bench(faults, **settings)
        cfg["instruments"] = {r: a for r, a in addrs.items() if r in t.required_instruments}
        prompts = []
        res = run_test(t, cfg, simulate=False, output_root=str(tmp_path),
                       callbacks=Callbacks(prompt=prompts.append))
        return res, bench, prompts

    return run
