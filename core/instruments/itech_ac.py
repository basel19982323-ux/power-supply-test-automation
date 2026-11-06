"""ITECH AC source driver (SCPI over PyVISA).

Commands below follow the common ITECH AC-source SCPI set (IT7300 / IT-M7700
families). If your model differs, the first run prints its *IDN? response --
check that model's programming manual and adjust CMDS only.
"""
import time

from .replies import parse_number, parse_on_off

CMDS = {
    "set_voltage": "VOLTage {v}",
    "set_frequency": "FREQuency {f}",
    "output_on": "OUTPut ON",
    "output_off": "OUTPut OFF",
    "measure_voltage": "MEASure:VOLTage?",
    "output_q": "OUTPut?",
}


class ITechACSource:
    role = "ac_source"

    def __init__(self, resource):
        self.inst = resource
        self.inst.timeout = 5000
        self.idn = self.inst.query("*IDN?").strip()
        print(f"[AC source] {self.idn}")

    def apply(self, voltage, frequency, settle_s=2.0):
        """Set AC voltage/frequency with output OFF, then enable output."""
        self.inst.write(CMDS["output_off"])
        time.sleep(0.3)
        self.inst.write(CMDS["set_voltage"].format(v=voltage))
        self.inst.write(CMDS["set_frequency"].format(f=frequency))
        time.sleep(0.3)
        self.inst.write(CMDS["output_on"])
        time.sleep(settle_s)  # let DUT start up
        measured = parse_number(self.inst.query(CMDS["measure_voltage"]), unit="V",
                                what="AC source measured voltage")
        print(f"[AC source] set {voltage} V / {frequency} Hz, measured {measured} V")
        return measured

    def off(self):
        self.inst.write(CMDS["output_off"])

    def output_is_on(self):
        """Ask the source whether its output is on (used to CONFIRM AC off)."""
        return parse_on_off(self.inst.query(CMDS["output_q"]), what="AC source output")

    def close(self):
        try:
            self.off()
        finally:
            self.inst.close()
