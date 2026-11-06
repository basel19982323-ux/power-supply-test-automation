"""ITECH electronic load driver (SCPI over PyVISA).

Implements continuous CC transient (dynamic) mode: current alternates between
level A (low) and level B (high) at a set frequency/duty with a set slew rate.

Commands follow the ITECH IT8500+/IT8800 style SCPI set. Widths are derived
from frequency + duty cycle. If your model uses TRANsient:FREQuency/DCYCle
instead of A/B widths, adjust CMDS -- the first run prints *IDN? to identify
the model.
"""
import time

from .replies import parse_number, parse_on_off

CMDS = {
    "mode_cc": "FUNCtion CURRent",
    "cc_level": "CURRent {i}",                    # static CC current level (A)
    "slew": "CURRent:SLEW {sr}",                 # A/us on most ITECH loads
    "tran_mode": "CURRent:TRANsient:MODE CONTinuous",
    "a_level": "CURRent:TRANsient:ALEVel {a}",
    "a_width": "CURRent:TRANsient:AWIDth {w}",   # seconds
    "b_level": "CURRent:TRANsient:BLEVel {b}",
    "b_width": "CURRent:TRANsient:BWIDth {w}",   # seconds
    "tran_on": "TRANsient ON",
    "tran_off": "TRANsient OFF",
    "input_on": "INPut ON",
    "input_off": "INPut OFF",
    "meas_curr": "MEASure:CURRent?",             # measured input current (A)
    "input_q": "INPut?",
}


class ITechLoad:
    role = "e_load"

    def __init__(self, resource):
        self.inst = resource
        self.inst.timeout = 5000
        self.idn = self.inst.query("*IDN?").strip()
        print(f"[E-load] {self.idn}")

    def start_transient(self, i_low, i_high, freq_hz, duty_pct, slew_a_us):
        period = 1.0 / freq_hz
        w_high = period * duty_pct / 100.0
        w_low = period - w_high
        w = self.inst.write
        w(CMDS["input_off"])
        w(CMDS["mode_cc"])
        w(CMDS["slew"].format(sr=slew_a_us))
        w(CMDS["tran_mode"])
        w(CMDS["a_level"].format(a=i_low))
        w(CMDS["a_width"].format(w=f"{w_low:.6f}"))
        w(CMDS["b_level"].format(b=i_high))
        w(CMDS["b_width"].format(w=f"{w_high:.6f}"))
        time.sleep(0.3)
        w(CMDS["input_on"])
        w(CMDS["tran_on"])
        print(f"[E-load] transient {i_low}<->{i_high} A @ {freq_hz} Hz, "
              f"duty {duty_pct}%, slew {slew_a_us} A/us")

    def set_cc(self, current):
        """Static constant-current load (not transient) — used to hold the DUT
        output under load, e.g. for the VDS-at-OVP test."""
        w = self.inst.write
        w(CMDS["input_off"])
        w(CMDS["mode_cc"])
        w(CMDS["cc_level"].format(i=current))
        w(CMDS["input_on"])
        print(f"[E-load] static CC {current} A")

    def measure_current(self):
        """The current the load really draws, in A. In transient mode this is
        the AVERAGE over the load's measuring window (the load cannot report
        the peak of each step), so the test compares it with the expected
        average current."""
        return parse_number(self.inst.query(CMDS["meas_curr"]), unit="A",
                            what="e-load measured current")

    def stop(self):
        """INPut OFF first: that is the command that really stops the current.
        (Before, TRANsient OFF was sent first, so if it failed the input stayed
        on.) Both are tried; the first error is raised after both attempts."""
        first_error = None
        for cmd in (CMDS["input_off"], CMDS["tran_off"]):
            try:
                self.inst.write(cmd)
            except Exception as e:  # noqa: BLE001 - try the other one too
                first_error = first_error or e
        if first_error is not None:
            raise first_error

    def input_is_on(self):
        """Ask the load whether its input is on (used to CONFIRM load off)."""
        return parse_on_off(self.inst.query(CMDS["input_q"]), what="e-load input")

    def close(self):
        try:
            self.stop()
        finally:
            self.inst.close()
