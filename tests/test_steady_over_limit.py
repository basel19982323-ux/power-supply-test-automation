"""A steady VDS that is already above the limit (for example 700 V on a 650 V
FET with a 585 V limit) is FAIL STEADY_OVER_LIMIT: no test event is started
(no single-shot armed, no AC cut as an event, the feedback loop never broken),
the run stops, and the bench is turned off. Tested through the whole run:
runner, CSV, shutdown, Excel report, Sequence, CLI and the real drivers."""
import math

import pytest
from openpyxl import load_workbook

import cli
import core.instruments.simulator as sim
import core.runner
import reporting
import testtypes
from core.config import save_config
from core.results import new_run_dir, read_csv
from core.runner import run_test
from core.sequence import run_sequence
from core.test_base import Callbacks
from core.verdict import ERROR, FAIL, NOT_RUN, PASS, PointError, StopRunError
from testtypes.common import check_steady_below_limit, check_steady_vds
from tools import fake_bench as fb

LIMIT = 585.0          # default: 650 V FET x 90 % derating


def _reflected_for(steady_v, ac_v):
    """Simulator setting that makes the steady VDS peak read `steady_v`."""
    return steady_v - ac_v * 1.41421


def _cfg(test_id, steady_v, ac_v):
    t = testtypes.get_test(test_id)
    cfg = t.default_config()
    cfg["simulation"] = {"vds_reflected": _reflected_for(steady_v, ac_v)}
    first = [c for c in cfg["ac_conditions"] if c["voltage"] == ac_v]
    others = [c for c in cfg["ac_conditions"] if c["voltage"] != ac_v]
    cfg["ac_conditions"] = first + others
    return t, cfg


@pytest.fixture
def events(monkeypatch):
    """Record every test event the simulated scope sees, and keep the instruments."""
    log = {"arm": 0, "wait": 0, "inst": {}}
    arm, wait = sim.SimScope.arm_single, sim.SimScope.wait_trigger

    def _arm(self):
        log["arm"] += 1
        return arm(self)

    def _wait(self, *a, **k):
        log["wait"] += 1
        return wait(self, *a, **k)

    build = core.runner.build_instruments

    def _build(*a, **k):
        log["inst"] = build(*a, **k)
        return log["inst"]

    monkeypatch.setattr(sim.SimScope, "arm_single", _arm)
    monkeypatch.setattr(sim.SimScope, "wait_trigger", _wait)
    monkeypatch.setattr(core.runner, "build_instruments", _build)
    return log


# ---- the rule itself ----------------------------------------------------- #
def test_steady_above_the_limit_is_fail_and_stops_the_run():
    with pytest.raises(StopRunError) as e:
        check_steady_below_limit(700.0, LIMIT, "Cutting the AC as a test event")
    assert (e.value.result, e.value.code) == (FAIL, "STEADY_OVER_LIMIT")
    assert e.value.values["vds_max_v"] == "≥ 700.0"


@pytest.mark.parametrize("steady", [425.0, LIMIT])     # normal / exactly at the limit
def test_steady_at_or_below_the_limit_goes_on_to_the_event(steady):
    assert check_steady_below_limit(steady, LIMIT, "x") == steady


# ---- the whole run: VDS at AC turn-off ------------------------------------ #
@pytest.mark.parametrize("steady, ac_v", [
    (700.0, 264),      # the case asked about: 700 V on a 650 V FET
    (700.0, 90),       # same at low line (passes the probe check, fails the limit)
    (600.0, 264),      # above the 585 V limit but below the 650 V rating: still FAIL
])
def test_turnoff_run_stops_before_any_test_event(events, tmp_path, steady, ac_v):
    t, cfg = _cfg("vds_turnoff", steady, ac_v)
    res = run_test(t, cfg, simulate=True, output_root=str(tmp_path))

    assert [r["result"] for r in res.rows] == [FAIL, NOT_RUN]
    assert res.rows[0]["error_code"] == "STEADY_OVER_LIMIT"
    assert res.rows[0]["vds_max_v"].startswith("≥ ")
    assert res.rows[1]["error_code"] == "RUN_ENDED_EARLY"
    assert res.overall == FAIL and res.error.startswith("STEADY_OVER_LIMIT")
    assert events["arm"] == 0 and events["wait"] == 0     # no capture was ever armed
    ac = events["inst"]["ac_source"]
    assert sum(c.startswith("APPLY") for c in ac.commands) == 1   # powered up once only
    assert ac.bench.ac_on is False and res.warnings == []          # and left OFF
    assert read_csv(res.csv_path)[0]["error_code"] == "STEADY_OVER_LIMIT"


def test_a_healthy_dut_still_gets_its_test_event(events, tmp_path):
    t, cfg = _cfg("vds_turnoff", 473.0, 264)
    res = run_test(t, cfg, simulate=True, output_root=str(tmp_path))
    assert [r["result"] for r in res.rows] == [PASS, PASS]
    assert events["arm"] == 2 and events["wait"] == 2


def test_steady_just_below_the_limit_is_measured_and_fails_on_the_spike(events, tmp_path):
    # 580 V steady is allowed to go on; the turn-off spike (x1.2 = 696 V) is a normal FAIL.
    t, cfg = _cfg("vds_turnoff", 580.0, 264)
    res = run_test(t, cfg, simulate=True, output_root=str(tmp_path))
    assert res.rows[0]["result"] == FAIL and res.rows[0]["error_code"] == ""
    assert events["arm"] >= 1


# ---- the whole run: VDS at OVP -------------------------------------------- #
def test_ovp_run_never_breaks_the_feedback_loop(events, tmp_path):
    t, cfg = _cfg("vds_ovp", 700.0, 230)
    res = run_test(t, cfg, simulate=True, output_root=str(tmp_path))
    assert [r["result"] for r in res.rows] == [FAIL]
    assert res.rows[0]["error_code"] == "STEADY_OVER_LIMIT"
    assert "Breaking the feedback loop was not done" in res.rows[0]["reason"]
    assert events["arm"] == 0 and events["wait"] == 0
    bench = events["inst"]["ac_source"].bench
    assert bench.ac_on is False and bench.load_on is False and res.warnings == []


# ---- Excel report, Sequence and CLI --------------------------------------- #
def test_excel_report_shows_the_fail_and_why(tmp_path):
    t, cfg = _cfg("vds_turnoff", 700.0, 264)
    res = run_test(t, cfg, simulate=True, output_root=str(tmp_path))
    wb = load_workbook(reporting.generate(res.run_dir, t, cfg, rows=res.rows,
                                          pptx=False)["excel"])
    summary = {wb["Summary"].cell(r, 1).value: wb["Summary"].cell(r, 2).value
               for r in range(3, 11)}
    assert (summary["FAIL"], summary["NOT RUN"], summary["Overall result"]) == (1, 1, FAIL)
    sheet = wb["Results"]
    header = [c.value for c in sheet[1]]
    row = {h: sheet.cell(2, i + 1).value for i, h in enumerate(header)}
    assert "STEADY_OVER_LIMIT" in str(row)


def test_sequence_stops_after_a_steady_over_limit_fail(tmp_path):
    t, cfg = _cfg("vds_turnoff", 700.0, 264)
    path = str(tmp_path / "hot.yaml")
    save_config(cfg, path)
    steps = [{"test_id": "vds_turnoff", "config_path": path},
             {"test_id": "vds_ovp", "config_path": None}]
    seq = run_sequence(steps, simulate=True, output_root=str(tmp_path),
                       on_status=lambda m: None)
    assert [st["outcome"] for st in seq.steps] == [FAIL, NOT_RUN]
    assert seq.steps[1]["code"] == "RUN_ENDED_EARLY" and seq.overall == FAIL


def test_cli_exit_code_is_fail(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(core.runner, "new_run_dir",
                        lambda dut, root=None: new_run_dir(dut, str(tmp_path / "out")))
    t, cfg = _cfg("vds_turnoff", 700.0, 264)
    path = str(tmp_path / "hot.yaml")
    save_config(cfg, path)
    assert cli.main(["--test", "vds_turnoff", "--config", path, "--simulate"]) == 1
    assert "Overall result: FAIL" in capsys.readouterr().out


# ---- real drivers against the fake SCPI bench ----------------------------- #
@pytest.fixture
def fake_bench():
    """Start the fake bench on free ports and log every command it receives."""
    bench = fb.Bench(reflected=_reflected_for(700.0, 230))
    log, ports = [], {}
    handlers = {"ac_source": fb.ac_handler, "e_load": fb.eload_handler,
                "scope": fb.scope_handler}
    for role, handler in handlers.items():
        def logged(b, cmd, handler=handler, role=role):
            log.append((role, cmd.upper()))
            return handler(b, cmd)
        server = fb.SCPIServer(role, "127.0.0.1", 0, logged, bench)
        assert server.bind()
        ports[role] = server.sock.getsockname()[1]
        server.start()
    return bench, log, ports


@pytest.mark.parametrize("test_id", ["vds_turnoff", "vds_ovp"])
def test_real_drivers_never_start_the_event(fake_bench, tmp_path, test_id):
    bench, log, ports = fake_bench
    t = testtypes.get_test(test_id)
    cfg = t.default_config()
    cfg["ac_conditions"] = [{"label": "230Vac/50Hz", "voltage": 230, "frequency": 50}] * 2
    cfg["instruments"] = {r: f"TCPIP0::127.0.0.1::{p}::SOCKET"
                          for r, p in ports.items() if r in t.required_instruments}
    cfg["scope"]["settle_s"] = 0
    prompts = []
    res = run_test(t, cfg, simulate=False, output_root=str(tmp_path),
                   callbacks=Callbacks(prompt=prompts.append))

    assert [r["result"] for r in res.rows] == [FAIL, NOT_RUN]
    assert res.rows[0]["error_code"] == "STEADY_OVER_LIMIT"
    assert prompts == []                         # the operator was never asked to act
    scope_cmds = [c for role, c in log if role == "scope"]
    assert not any(c.startswith(":STAR") for c in scope_cmds)     # never armed
    assert bench.ac_on is False and res.warnings == []            # AC confirmed OFF
    if test_id == "vds_ovp":
        assert bench.load["input"] is False                       # load confirmed OFF


# ---- which 10x probe-setting mistakes are caught -------------------------- #
@pytest.mark.parametrize("ac_v", [85, 90, 115, 230, 264])
def test_ten_times_too_high_is_always_caught_for_a_650v_fet(ac_v):
    true_v = math.sqrt(2) * ac_v + 100.0          # bulk + reflected, healthy DUT
    with pytest.raises(StopRunError) as e:
        check_steady_vds(10 * true_v, ac_v, {}, fet_rating_v=650.0)
    assert e.value.code == "PROBE_CHECK" and e.value.result == ERROR


@pytest.mark.parametrize("ac_v", [85, 90, 115, 230, 264])
def test_ten_times_too_low_is_always_caught(ac_v):
    true_v = math.sqrt(2) * ac_v + 250.0          # even with a large reflected voltage
    with pytest.raises(PointError) as e:
        check_steady_vds(true_v / 10, ac_v, {}, fet_rating_v=650.0)
    assert e.value.code == "PROBE_CHECK"


def test_ten_times_too_high_that_is_missed_is_still_never_a_pass():
    # 1200 V FET at 90 Vac with a DUT that is not switching (bulk only, 127 V):
    # 1273 V is below the 1800 V top, so the probe check misses it - but it is
    # above the 1080 V limit, so it is FAIL and the run stops. Never PASS.
    reading = 10 * math.sqrt(2) * 90
    assert check_steady_vds(reading, 90, {}, fet_rating_v=1200.0) == reading
    with pytest.raises(StopRunError) as e:
        check_steady_below_limit(reading, 1200.0 * 0.9, "x")
    assert e.value.result == FAIL


def test_two_times_too_low_is_not_caught_known_limit():
    # Known limit of a plausibility check: a 2x-too-LOW probe setting at 264 Vac
    # (true 633 V read as 317 V) looks normal. Only checking the probe setting
    # by hand catches this - see the check_steady_vds docstring.
    assert check_steady_vds(633.0 / 2, 264, {}, fet_rating_v=650.0) == 633.0 / 2
