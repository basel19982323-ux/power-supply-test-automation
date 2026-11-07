"""The run mode label (SIMULATION / FAKE BENCH / LIVE) comes from three
separate pieces of evidence - how the instrument was built, its VISA address
and its *IDN? reply - never from the *IDN? reply alone. LIVE only when all
three say "real". It is saved in the run folder and shown in the reports."""
import json
import os

import pytest
from openpyxl import load_workbook
from pptx import Presentation

import reporting
import testtypes
from core.instruments.simulator import SimACSource, SimBench
from core.run_mode import (FAKE_BENCH, LIVE, MIXED, NOT_CONNECTED, RUN_INFO_FILE,
                           SIMULATION, UNKNOWN, address_is_this_pc, classify_instrument,
                           classify_run, read_run_info)
from core.runner import run_test

LAN = "TCPIP0::192.168.10.20::5025::SOCKET"
LOCAL = "TCPIP0::127.0.0.1::5025::SOCKET"
REAL_IDN = "ITECH Ltd.,IT7321,800999011747520001,1.06-1.04"


class _RealDriver:
    """Stands in for a real driver object (not built by the simulator)."""
    role = "ac_source"

    def __init__(self, idn):
        self.idn = idn


# ---- the rule -------------------------------------------------------------- #
@pytest.mark.parametrize("address, local", [
    (LOCAL, True), ("TCPIP::localhost::inst0::INSTR", True),
    ("TCPIP0::[::1]::5025::SOCKET", True), (LAN, False),
    ("USB0::0x0B21::0x0039::91HC12345::INSTR", False), ("GPIB0::7::INSTR", False),
])
def test_address_on_this_pc(address, local):
    assert address_is_this_pc(address) is local


@pytest.mark.parametrize("address, idn, kind", [
    (LAN, REAL_IDN, LIVE),                                # all three say real
    (LOCAL, REAL_IDN, FAKE_BENCH),       # a real-looking IDN can't make it LIVE
    (LAN, "SIM,ITECH-IT7300,FAKE-BENCH,1.0", FAKE_BENCH),   # the IDN says fake
    (LOCAL, "SIM,ITECH-IT7300,FAKE-BENCH,1.0", FAKE_BENCH),
    (LAN, "", LIVE),                     # no IDN: address and driver decide
])
def test_real_driver_classification(address, idn, kind):
    info = classify_instrument(_RealDriver(idn), address, simulate=False)
    assert info["kind"] == kind and info["why"]


def test_a_simulated_instrument_is_simulation_whatever_it_says():
    dev = SimACSource(SimBench())
    dev.idn = REAL_IDN                                   # even with a "real" IDN
    assert classify_instrument(dev, LAN, simulate=False)["kind"] == SIMULATION


@pytest.mark.parametrize("devices, mode", [
    ({"ac_source": (LAN, REAL_IDN), "scope": (LAN, "YOKOGAWA,DLM2024,C1,1")}, LIVE),
    ({"ac_source": (LOCAL, REAL_IDN), "scope": (LOCAL, "x")}, FAKE_BENCH),
    ({"ac_source": (LAN, REAL_IDN), "scope": (LOCAL, "x")}, MIXED),
    ({}, NOT_CONNECTED),
])
def test_run_mode_from_all_instruments(devices, mode):
    inst = {r: _RealDriver(idn) for r, (_, idn) in devices.items()}
    cfg = {"instruments": {r: a for r, (a, _) in devices.items()}}
    assert classify_run(inst, cfg, simulate=False)[0] == mode


def test_simulate_flag_wins_even_with_lab_addresses():
    cfg = {"instruments": {"ac_source": LAN}}
    mode, info = classify_run({"ac_source": SimACSource(SimBench())}, cfg, simulate=True)
    assert mode == SIMULATION and info["ac_source"]["kind"] == SIMULATION


# ---- through real runs ----------------------------------------------------- #
def _report_texts(res, test_id):
    t = testtypes.get_test(test_id)
    cfg = t.default_config()
    paths = reporting.generate(res.run_dir, t, cfg, rows=res.rows)
    ws = load_workbook(paths["excel"])["Summary"]
    excel = {ws.cell(r, 1).value: ws.cell(r, 2).value for r in range(3, 12)}
    title = "\n".join(sh.text_frame.text for sh in Presentation(paths["pptx"]).slides[0].shapes
                      if sh.has_text_frame)
    return excel, ws, title


def test_simulation_run_is_labelled_simulation_everywhere(tmp_path):
    t = testtypes.get_test("vds_turnoff")
    res = run_test(t, t.default_config(), simulate=True, output_root=str(tmp_path))
    assert res.mode == SIMULATION
    saved = json.load(open(os.path.join(res.run_dir, RUN_INFO_FILE), encoding="utf-8"))
    assert saved["mode"] == SIMULATION and "NOT a measurement" in saved["note"]
    excel, ws, title = _report_texts(res, "vds_turnoff")
    assert excel["Run mode"] == SIMULATION
    assert "NOT a measurement of a real DUT" in ws["A13"].value
    assert "Run mode: SIMULATION" in title


def test_fake_bench_run_is_labelled_fake_bench_not_live(run_on_fake_bench):
    # Real drivers, simulate=False: without the evidence this would look LIVE.
    res, bench, _ = run_on_fake_bench("vds_turnoff")
    assert res.mode == FAKE_BENCH
    for role, info in res.instruments.items():
        assert info["kind"] == FAKE_BENCH
        assert len(info["why"]) == 2         # address on this PC AND the IDN says fake
    excel, ws, title = _report_texts(res, "vds_turnoff")
    assert excel["Run mode"] == FAKE_BENCH and "Run mode: FAKE BENCH" in title
    # the instrument table also shows "sent vs confirmed" at the end of the run
    rows = {ws.cell(r, 1).value: (ws.cell(r, 2).value, ws.cell(r, 4).value)
            for r in range(16, 20) if ws.cell(r, 1).value}
    assert rows["ac_source"] == (FAKE_BENCH, "OFF confirmed by the instrument")


def test_old_run_folder_without_run_info_is_unknown(tmp_path):
    assert read_run_info(str(tmp_path))["mode"] == UNKNOWN


# ---- the CI demo: cli.py --simulate --report ------------------------------ #
def test_cli_report_says_simulation(tmp_path, monkeypatch, capsys):
    import cli
    import core.runner
    from core.results import new_run_dir
    monkeypatch.setattr(core.runner, "new_run_dir",
                        lambda dut, root=None: new_run_dir(dut, str(tmp_path / "out")))
    assert cli.main(["--test", "vds_ovp", "--simulate", "--report"]) == 0
    out = capsys.readouterr().out
    assert "Run mode: SIMULATION" in out
    run_dir = os.path.join(tmp_path, "out", os.listdir(tmp_path / "out")[0])
    xlsx = [f for f in os.listdir(run_dir) if f.endswith(".xlsx")]
    pptx = [f for f in os.listdir(run_dir) if f.endswith(".pptx")]
    assert xlsx and pptx
    ws = load_workbook(os.path.join(run_dir, xlsx[0]))["Summary"]
    assert {ws.cell(r, 1).value: ws.cell(r, 2).value
            for r in range(3, 12)}["Run mode"] == SIMULATION
    slide = Presentation(os.path.join(run_dir, pptx[0])).slides[0]
    assert any("Run mode: SIMULATION" in sh.text_frame.text
               for sh in slide.shapes if sh.has_text_frame)


def test_cli_report_failure_is_a_failed_exit_code(tmp_path, monkeypatch, capsys):
    import cli
    import core.runner
    from core.results import new_run_dir
    monkeypatch.setattr(core.runner, "new_run_dir",
                        lambda dut, root=None: new_run_dir(dut, str(tmp_path / "out")))

    def broken(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(reporting, "generate", broken)
    assert cli.main(["--test", "vds_ovp", "--simulate", "--report"]) == cli.EXIT_REPORT_FAILED
    assert "could not be written" in capsys.readouterr().err
