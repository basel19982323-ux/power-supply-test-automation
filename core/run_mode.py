"""How was a run made: SIMULATION, FAKE BENCH or LIVE?

The label is decided from three separate pieces of evidence for each VISA
instrument, not from one reply:

  1. how the app built it - the built-in simulator, or a real driver;
  2. its VISA address     - on this PC (127.0.0.1 / localhost / ::1) or not;
  3. its *IDN? reply      - does it say SIM / FAKE?

LIVE is claimed only when all three point to a real instrument. Any doubt
makes it "not LIVE", so a fake bench can't pass as a real one by giving a
real-looking *IDN? reply, and a real instrument behind a local tunnel is
labelled FAKE BENCH (the safe mistake) rather than LIVE.

The result is decided by the runner at run time and saved in the run folder
(run_info.json), so a report made later from that folder shows it too.
"""
import json
import os
import re

SIMULATION = "SIMULATION"
FAKE_BENCH = "FAKE BENCH"
LIVE = "LIVE"
MIXED = "MIXED"                 # some instruments real, some not
NOT_CONNECTED = "NOT CONNECTED"  # no instrument was connected
UNKNOWN = "UNKNOWN"             # older run folder, the mode was not recorded

MODE_NOTES = {
    SIMULATION: "Simulated instruments: NOT a measurement of a real DUT.",
    FAKE_BENCH: "Fake SCPI bench on this PC (real drivers, fake instruments): "
                "NOT a measurement of a real DUT.",
    LIVE: "Real instruments.",
    MIXED: "Some instruments were not real: do NOT use as a real measurement.",
    NOT_CONNECTED: "No instrument could be connected.",
    UNKNOWN: "The run mode was not recorded (older run folder).",
}

VISA_ROLES = ("ac_source", "e_load", "scope")   # POWER-Z is not a VISA instrument
RUN_INFO_FILE = "run_info.json"


_TCPIP_HOST = re.compile(r"^\s*TCPIP\d*::(\[[^\]]*\]|[^:]+)", re.IGNORECASE)


def _host(address):
    """Host part of a TCPIP VISA address, or None for USB / GPIB / serial.
    An IPv6 host is written in brackets ([::1]) because it contains '::'."""
    m = _TCPIP_HOST.match(str(address or ""))
    return m.group(1).strip("[]").lower() if m else None


def address_is_this_pc(address):
    host = _host(address)
    return host is not None and (host == "localhost" or host.startswith("127.")
                                 or host in ("::1", "0.0.0.0"))


def idn_says_not_real(idn):
    text = str(idn or "").upper()
    return text.startswith("SIM,") or "SIMULAT" in text or "FAKE" in text


def classify_instrument(dev, address, simulate):
    """{"kind": SIMULATION / FAKE_BENCH / LIVE, "address", "idn", "why": [...]}."""
    from core.instruments import simulator
    idn = str(getattr(dev, "idn", "") or "")
    if simulate or type(dev).__module__ == simulator.__name__:
        return {"kind": SIMULATION, "address": "", "idn": idn,
                "why": ["built by the app's simulator (Simulation mode)"]}
    why = []
    if address_is_this_pc(address):
        why.append(f"its address {address} is on this PC, not on a lab instrument")
    if idn_says_not_real(idn):
        why.append(f"it identifies itself as {idn!r}")
    if why:
        return {"kind": FAKE_BENCH, "address": address, "idn": idn, "why": why}
    return {"kind": LIVE, "address": address, "idn": idn,
            "why": ["real driver", f"address {address} is not on this PC",
                    f"it identifies itself as {idn!r}"]}


def classify_run(instruments, config, simulate):
    """Return (mode, {role: instrument info})."""
    addresses = (config or {}).get("instruments") or {}
    info = {role: classify_instrument(instruments[role], addresses.get(role, ""), simulate)
            for role in VISA_ROLES if instruments.get(role) is not None}
    kinds = {i["kind"] for i in info.values()}
    if simulate:
        mode = SIMULATION
    elif not info:
        mode = NOT_CONNECTED
    elif kinds == {LIVE}:
        mode = LIVE
    elif kinds == {FAKE_BENCH}:
        mode = FAKE_BENCH
    else:
        mode = MIXED
    return mode, info


def write_run_info(run_dir, mode, instruments, shutdown):
    data = {"mode": mode, "note": MODE_NOTES.get(mode, ""),
            "instruments": instruments, "shutdown": shutdown}
    with open(os.path.join(run_dir, RUN_INFO_FILE), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def read_run_info(run_dir):
    """The saved run info, or an UNKNOWN one for an older run folder."""
    try:
        with open(os.path.join(run_dir, RUN_INFO_FILE), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    mode = data.get("mode") or UNKNOWN
    return {"mode": mode, "note": data.get("note") or MODE_NOTES.get(mode, ""),
            "instruments": data.get("instruments") or {},
            "shutdown": data.get("shutdown") or {}}
