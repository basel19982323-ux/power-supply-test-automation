"""ITECH AC source driver (SCPI over PyVISA).

Commands below follow the common ITECH AC-source SCPI set (IT7300 / IT-M7700
families). If your model differs, the first run prints its *IDN? response --
check that model's programming manual and adjust CMDS only.
"""
import time

CMDS = {
    "set_voltage": "VOLTage {v}",
    "set_frequency": "FREQuency {f}",
    "output_on": "OUTPut ON",
    "output_off": "OUTPut OFF",
    "measure_voltage": "MEASure:VOLTage?",
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
        measured = float(self.inst.query(CMDS["measure_voltage"]))
        print(f"[AC source] set {voltage} V / {frequency} Hz, measured {measured:.1f} V")
        return measured

    def off(self):
        self.inst.write(CMDS["output_off"])

    def close(self):
        try:
            self.off()
        finally:
            self.inst.close()
