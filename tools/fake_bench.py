"""Fake bench — a virtual AC source + e-load + oscilloscope that speaks SCPI over
TCP sockets, so the app's REAL instrument drivers can be exercised without any
hardware.

Unlike the app's built-in Simulation mode (which replaces the drivers entirely),
this makes the app open real VISA resources and send real SCPI: it validates the
PyVISA usage, command/response plumbing, binary screenshot transfer, trigger-
state polling, and the whole run/abort/prompt flow over a real transport.

Run it, then in the app turn Simulation mode OFF and point the Instruments tab at
the printed TCPIP::...::SOCKET addresses (or load configs/fake_bench_vds.yaml).

    python tools/fake_bench.py

Needs pyvisa-py on the app side (the @py backend supports raw sockets):
    pip install pyvisa-py

CAVEAT: this fake answers the exact SCPI my drivers send, so it validates the
plumbing — NOT whether those SCPI strings match your real DLM/ITECH models. Only
a real instrument (or a vendor-accurate simulator) proves the command syntax.

The VDS Turn-off test is fully realistic here (AC + scope over sockets, shared
state so cutting AC completes the scope's single-shot, real waveform PNGs). The
Dynamic Output Response test runs too, but its PD voltage comes from POWER-Z
(manual/out-of-band), so the fake scope reports a fixed nominal (--pd-nominal).
"""
import argparse
import os
import re
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.instruments.simulator import (_draw_dynamic_waveform,  # noqa: E402
                                        _draw_ovp, _draw_vds_split,
                                        _draw_vds_turnoff)

_NUM = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def last_num(s, default=0.0):
    m = _NUM.findall(s)
    return float(m[-1]) if m else default


def chan_of(u, default=1):
    m = re.search(r"CHAN\w*?(\d+)", u)
    return int(m.group(1)) if m else default


def block(data):
    """IEEE-488.2 definite-length binary block: #<ndigits><length><bytes>."""
    n = str(len(data)).encode()
    return b"#" + str(len(n)).encode() + n + data


class Bench:
    """Shared state across the three fake instruments (like the app's SimBench)."""

    def __init__(self, reflected=100.0, spike_factor=1.2, pd_nominal=5.0,
                 steady_out=20.0, ovp_vout=28.0, ovp_vds_factor=1.3):
        self.ac_voltage = 0.0
        self.ac_freq = 50.0
        self.ac_on = False
        self.reflected = reflected
        self.spike_factor = spike_factor
        self.pd_nominal = pd_nominal
        self.steady_out = steady_out
        self.ovp_vout = ovp_vout
        self.ovp_vds_factor = ovp_vds_factor
        self.vdivs = {}              # per-channel volts/div
        self.offsets = {}            # per-channel vertical offset
        self.armed = False
        self.forced = False
        self.polls_since_arm = 0     # :STAT? polls since the last :STARt
        self.zoom_on = False
        self.main_window = 0.5
        self.zoom_window = 0.05
        self.mode = "dynamic"
        self.vds_setup = False       # set once VDS-style setup (peak-detect/zoom) seen
        self.trig_source = None      # trigger source channel (2 => OVP-style test)
        self.last_vds = (0.0, 0.0, 0.0, False)
        self.ovp = {"vds": 0.0, "vds_top": 0.0, "vds_clip": False,
                    "vout": 0.0, "vout_top": 0.0}

    def steady_vds(self):
        return self.ac_voltage * 1.41421 + self.reflected

    def screen_top(self, ch=1):
        if ch not in self.vdivs:
            return 1e12
        return self.offsets.get(ch, 0.0) + self.vdivs[ch] * 4  # 8 divisions / 2


# --------------------------------------------------------------------------- #
# SCPI command handlers (return None=no reply, str=text reply, ("BINARY",bytes))
# --------------------------------------------------------------------------- #
def ac_handler(bench, cmd):
    u = cmd.upper()
    if u.startswith("*IDN?"):
        return "SIM,ITECH-IT7300,FAKE-BENCH,1.0"
    if u.startswith("*RST") or u.startswith("*CLS"):
        return None
    if u.startswith("MEAS"):                       # MEASure:VOLTage?
        return f"{(bench.ac_voltage if bench.ac_on else 0.0):.3f}"
    if u.startswith("OUTP"):
        bench.ac_on = "ON" in u
        return None
    if u.startswith("VOLT"):
        bench.ac_voltage = last_num(cmd)
        return None
    if u.startswith("FREQ"):
        bench.ac_freq = last_num(cmd)
        return None
    return None


def eload_handler(bench, cmd):
    if cmd.upper().startswith("*IDN?"):
        return "SIM,ITECH-IT8800,FAKE-BENCH,1.0"
    return None                                    # accept all load writes


def scope_handler(bench, cmd):
    u = cmd.upper()
    if "*IDN?" in u:                                # new connection => clean run state
        bench.armed = False
        bench.forced = False
        bench.trig_source = None
        bench.vds_setup = False
        return "SIM,YOKOGAWA-DLM,FAKE-BENCH,1.0"
    if u.startswith("*RST") or u.startswith("*CLS"):
        bench.armed = False
        bench.forced = False
        return None
    if u.startswith(":CHAN"):
        ch = chan_of(u)
        if u.endswith("?"):                          # read-back queries
            if "VDIV" in u:
                return f"{bench.vdivs.get(ch, 1.0):.6E}"
            if "OFFS" in u:
                return f"{bench.offsets.get(ch, 0.0):.6E}"
            return "0"
        if "VDIV" in u:
            bench.vdivs[ch] = max(last_num(cmd), 1e-6)
        elif "OFFS" in u:
            bench.offsets[ch] = last_num(cmd)
        return None                                     # DISPlay/COUPling/PROBe accepted
    if u.startswith(":TIM"):
        if "TDIV" in u:
            bench.main_window = last_num(cmd) * 10
        return None
    if u.startswith(":ACQ"):
        if "ENV" in u:                              # peak-detect => VDS test setup
            bench.vds_setup = True
        return None
    if u.startswith(":ZOOM"):
        if "MODE" in u:
            bench.zoom_on = "OFF" not in u
            if bench.zoom_on:
                bench.vds_setup = True
        if "TDIV" in u:
            bench.zoom_window = last_num(cmd) * 10
        return None
    if u.startswith(":STAR"):                      # arm single-shot
        bench.armed = True
        bench.forced = False
        bench.polls_since_arm = 0
        return None
    if u.startswith(":STOP"):
        bench.armed = False                         # acquisition stopped, no capture
        return None
    if u.startswith(":TRIG"):
        if "FORC" in u:
            bench.forced = True
        elif "SOUR" in u:
            bench.trig_source = int(last_num(cmd, 1))
        return None
    if u.startswith(":STAT"):                       # :STATus:CONDition?
        # Running = armed and waiting. Turn-off test: waits until AC goes off.
        # OVP test: running on the first poll (arm confirmed), then the
        # (simulated) operator opens the switch and it triggers.
        bench.polls_since_arm += 1
        ovp = (bench.trig_source == 2)
        if not bench.armed or bench.forced:
            running = False
        elif ovp:
            running = bench.polls_since_arm == 1
        else:
            running = bench.ac_on
        return "1" if running else "0"
    if ":MEAS" in u:
        if "MAX" in u and "VAL" in u:
            return f"{_scope_max(bench, chan_of(u)):.4f}"
        if "MIN" in u and "VAL" in u:
            return f"{bench.pd_nominal * 0.98:.4f}"
        return None                                 # measurement mode/state writes
    if "IMAGE" in u:
        if "SEND?" in u:
            return ("BINARY", _scope_png(bench))
        return None                                 # IMAGE:FORMAT
    return None


def _scope_max(bench, ch=1):
    ovp = (bench.trig_source == 2)
    captured = bench.armed and (ovp or not bench.ac_on or bench.forced)
    top = bench.screen_top(ch)
    if captured and ovp:                            # VDS-at-OVP capture
        val_true = (bench.ovp_vout if ch == 2
                    else bench.steady_vds() * bench.ovp_vds_factor)
        val = min(val_true, top)
        bench.mode = "ovp"
        if ch == 2:
            bench.ovp["vout"], bench.ovp["vout_top"] = val, top
        else:
            bench.ovp.update(
                vds=val, vds_top=top, vds_clip=val_true > top,
                vds_steady=bench.steady_vds(),
                bulk=bench.ac_voltage * 1.41421,
                main_ms=bench.main_window * 1000.0,
                zoom_ms=bench.zoom_window * 1000.0)
        return val
    if captured:                                    # VDS single-shot turn-off peak
        steady = bench.steady_vds()
        spike = steady * bench.spike_factor
        bench.last_vds = (steady, spike, top, spike > top)
        bench.mode = "vds"
        return min(spike, top)
    if bench.vds_setup and bench.ac_on:             # pre-arm steady (auto-range)
        bench.mode = "vds"
        return bench.steady_out if ch == 2 else bench.steady_vds()
    bench.mode = "dynamic"                           # continuous PD-output measurement
    return bench.pd_nominal * 1.02


def _scope_png(bench):
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        if bench.mode == "ovp":
            _draw_ovp(path, bench.ovp, bench.steady_out)
        elif bench.mode == "vds":
            steady, spike, top, clipped = bench.last_vds
            if bench.zoom_on:
                _draw_vds_split(path, steady, spike, top, clipped,
                                bench.main_window, bench.zoom_window)
            else:
                _draw_vds_turnoff(path, steady, spike, top, clipped)
        else:
            _draw_dynamic_waveform(path, bench.pd_nominal * 1.02,
                                   bench.pd_nominal * 0.98, 1)
        with open(path, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# TCP SCPI server
# --------------------------------------------------------------------------- #
class SCPIServer(threading.Thread):
    def __init__(self, label, host, port, handler, bench, verbose=False):
        super().__init__(daemon=True)
        self.label = label
        self.host = host
        self.port = port
        self.handler = handler
        self.bench = bench
        self.verbose = verbose
        self.sock = None

    def bind(self):
        """Bind the port up front (no SO_REUSEADDR) so a second copy of the fake
        bench fails loudly instead of silently shadowing the first."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.sock.bind((self.host, self.port))
        except OSError as e:
            print(f"  ! {self.label}: cannot bind {self.host}:{self.port} ({e})")
            self.sock.close()
            self.sock = None
            return False
        self.sock.listen(5)
        return True

    def run(self):
        while True:
            conn, _ = self.sock.accept()
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        if self.verbose:
            print(f"[{self.label}] client connected")
        buf = b""
        try:
            while True:
                data = conn.recv(4096)
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    cmd = line.decode(errors="replace").strip()
                    if not cmd:
                        continue
                    resp = self.handler(self.bench, cmd)
                    if self.verbose:
                        print(f"[{self.label}] <- {cmd}")
                    if resp is None:
                        continue
                    if isinstance(resp, tuple) and resp and resp[0] == "BINARY":
                        conn.sendall(block(resp[1]) + b"\n")
                        if self.verbose:
                            print(f"[{self.label}] -> <PNG {len(resp[1])} bytes>")
                    else:
                        conn.sendall((str(resp) + "\n").encode())
                        if self.verbose:
                            print(f"[{self.label}] -> {resp}")
        except OSError:
            pass
        finally:
            if self.verbose:
                print(f"[{self.label}] client disconnected")
            try:
                conn.close()
            except OSError:
                pass


def main():
    ap = argparse.ArgumentParser(description="Fake SCPI bench (AC source + e-load + scope).")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--ac-port", type=int, default=5025)
    ap.add_argument("--eload-port", type=int, default=5026)
    ap.add_argument("--scope-port", type=int, default=5027)
    ap.add_argument("--reflected", type=float, default=100.0,
                    help="V added to bulk for the steady VDS peak")
    ap.add_argument("--spike-factor", type=float, default=1.2,
                    help="turn-off overshoot = steady VDS * this")
    ap.add_argument("--pd-nominal", type=float, default=5.0,
                    help="PD output the fake scope reports for the Dynamic test")
    ap.add_argument("--steady-out", type=float, default=20.0,
                    help="steady output (CH2) before OVP, for the VDS-at-OVP test")
    ap.add_argument("--ovp-vout", type=float, default=28.0,
                    help="output peak when OVP trips (CH2)")
    ap.add_argument("--ovp-vds-factor", type=float, default=1.3,
                    help="VDS during OVP = steady VDS * this")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="log every SCPI command and response")
    args = ap.parse_args()

    bench = Bench(args.reflected, args.spike_factor, args.pd_nominal,
                  args.steady_out, args.ovp_vout, args.ovp_vds_factor)
    servers = [
        SCPIServer("AC source", args.host, args.ac_port, ac_handler, bench, args.verbose),
        SCPIServer("E-load", args.host, args.eload_port, eload_handler, bench, args.verbose),
        SCPIServer("Scope", args.host, args.scope_port, scope_handler, bench, args.verbose),
    ]
    if not all([s.bind() for s in servers]):
        print("Aborting: a port is already in use — is fake_bench.py already running?")
        return
    for s in servers:
        s.start()

    def res(port):
        return f"TCPIP0::{args.host}::{port}::SOCKET"

    print("Fake bench running. In the app: turn Simulation mode OFF and use:")
    print(f"  AC source : {res(args.ac_port)}")
    print(f"  E-load    : {res(args.eload_port)}")
    print(f"  Scope     : {res(args.scope_port)}")
    print("(or load configs/fake_bench_vds.yaml). Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nfake bench stopped.")


if __name__ == "__main__":
    main()
