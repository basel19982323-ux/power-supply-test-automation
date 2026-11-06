"""Yokogawa DLM-series oscilloscope driver (PyVISA, VXI-11 or USB).

Uses the DLM colon-style command set (DLM3000/DLM5000 style) for:
  * automated waveform-parameter measurement (Max/Min)  [Dynamic Output test]
  * single-shot triggered capture with vertical/timebase/trigger setup,
    peak-detect acquisition, and peak read-back          [VDS Turn-off test]
  * screen image transfer

NOTE: exact command syntax varies between DLM2000/3000/5000 firmware. The first
run prints *IDN?; verify each command against your model's "Communication
Interface" manual and adjust CMDS if one errors. The single-shot / trigger
commands especially are model-dependent — they are grouped in CMDS below.
"""
import time

from .replies import parse_number

CMDS = {
    # ---- continuous measurement (Dynamic Output Response test) ---- #
    "meas_on": ":MEASure:MODE ON",
    "item_max_on": ":MEASure:CHANnel{ch}:MAXimum:STATe ON",
    "item_min_on": ":MEASure:CHANnel{ch}:MINimum:STATe ON",
    "query_max": ":MEASure:CHANnel{ch}:MAXimum:VALue?",
    "query_min": ":MEASure:CHANnel{ch}:MINimum:VALue?",
    # ---- vertical / horizontal / acquisition ---- #
    "display": ":CHANnel{ch}:DISPlay {s}",         # ON | OFF (enable a channel)
    "coupling": ":CHANnel{ch}:COUPling {c}",       # DC | AC | GND
    "probe": ":CHANnel{ch}:PROBe {a}",             # attenuation ratio, e.g. 100
    "bandwidth": ":CHANnel{ch}:BWIDth {b}",        # FULL | 20M | ...
    "vdiv": ":CHANnel{ch}:VDIV {v}",               # volts/div
    "offset": ":CHANnel{ch}:OFFSet {v}",           # vertical offset (volts)
    "vdiv_q": ":CHANnel{ch}:VDIV?",                # read back volts/div
    "offset_q": ":CHANnel{ch}:OFFSet?",            # read back offset
    "tdiv": ":TIMebase:TDIV {t}",                  # main (top) seconds/div
    "acq_mode": ":ACQuire:MODE {m}",               # NORMal | ENVelope (peak-detect)
    # ---- zoom (split display: main on top, zoom window on bottom) ---- #
    "zoom_mode": ":ZOOM:MODE {s}",                 # ON | OFF
    "zoom1_state": ":ZOOM:ZOOM1:STATe {s}",        # ON | OFF
    "zoom1_tdiv": ":ZOOM:ZOOM1:TDIV {t}",          # zoom window seconds/div
    "zoom1_pos": ":ZOOM:ZOOM1:POSition {t}",       # zoom centre, seconds from trigger
    # ---- trigger + single-shot ---- #
    "trig_source": ":TRIGger:SIMPle:SOURce {src}",
    "trig_level": ":TRIGger:SIMPle:LEVel {v}",
    "trig_slope": ":TRIGger:SIMPle:SLOPe {s}",     # RISE | FALL
    "trig_mode": ":TRIGger:MODE {m}",              # SINGle | NORMal | AUTO
    "acq_start": ":STARt",
    "acq_stop": ":STOP",
    "force_trig": ":TRIGger:FORCe",
    "cond": ":STATus:CONDition?",                  # poll; bit indicates running/stopped
    # ---- screenshot ---- #
    "img_format": ":IMAGe:FORMat PNG",
    "img_send": ":IMAGe:SEND?",
}

_SLOPE = {"rising": "RISE", "falling": "FALL"}
_RUNNING_BIT = 0x0001   # DLM condition bit meaning "acquisition running" (verify per model)


class YokogawaScope:
    role = "scope"
    VERT_DIVS = 8         # vertical graticule divisions (DLM: 8)
    HORIZ_DIVS = 10       # horizontal graticule divisions

    def __init__(self, resource):
        self.inst = resource
        self.inst.timeout = 15000  # image transfer can be slow
        self.idn = self.inst.query("*IDN?").strip()
        self._vdiv = {}
        self._offset = {}
        print(f"[Scope] {self.idn}")

    # ---- continuous measurement (Dynamic Output Response) --------------- #
    def setup_measurements(self, channel):
        self.inst.write(CMDS["meas_on"])
        self.inst.write(CMDS["item_max_on"].format(ch=channel))
        self.inst.write(CMDS["item_min_on"].format(ch=channel))

    def read_vmax_vmin(self, channel):
        vmax = parse_number(self.inst.query(CMDS["query_max"].format(ch=channel)),
                            unit="V", what=f"CH{channel} Vmax")
        vmin = parse_number(self.inst.query(CMDS["query_min"].format(ch=channel)),
                            unit="V", what=f"CH{channel} Vmin")
        print(f"[Scope] CH{channel}: Vmax={vmax} V, Vmin={vmin} V")
        return vmax, vmin

    # ---- vertical / horizontal / acquisition setup --------------------- #
    def enable_channel(self, ch, on=True):
        self.inst.write(CMDS["display"].format(ch=ch, s="ON" if on else "OFF"))

    def configure_channel(self, ch, coupling="DC", probe_atten=None, bandwidth=None):
        self.inst.write(CMDS["coupling"].format(ch=ch, c=coupling))
        if probe_atten is not None:
            self.inst.write(CMDS["probe"].format(ch=ch, a=probe_atten))
        if bandwidth is not None:
            self.inst.write(CMDS["bandwidth"].format(ch=ch, b=bandwidth))

    def set_vertical(self, ch, vdiv, offset=0.0):
        self.inst.write(CMDS["vdiv"].format(ch=ch, v=vdiv))
        self.inst.write(CMDS["offset"].format(ch=ch, v=offset))
        self._vdiv[ch] = vdiv
        self._offset[ch] = offset

    def screen_top(self, ch):
        """Top of the screen as the APP set it (may differ from the scope's)."""
        return self._offset.get(ch, 0.0) + self._vdiv.get(ch, 1.0) * self.VERT_DIVS / 2

    def read_screen_top(self, ch):
        """Top of the screen as the SCOPE reports it. A scope can silently clamp
        a volts/div it can't do (for example above its maximum range), so the
        clip check and the "≥ X V" value use this read-back, not our own number."""
        vdiv = parse_number(self.inst.query(CMDS["vdiv_q"].format(ch=ch)),
                            unit="V", what=f"CH{ch} V/div")
        offset = parse_number(self.inst.query(CMDS["offset_q"].format(ch=ch)),
                              unit="V", what=f"CH{ch} offset")
        return offset + vdiv * self.VERT_DIVS / 2

    def screen_bottom(self, ch):
        return self._offset.get(ch, 0.0) - self._vdiv.get(ch, 1.0) * self.VERT_DIVS / 2

    def set_timebase(self, total_seconds):
        """Set the MAIN (top) window total span across the screen."""
        self.inst.write(CMDS["tdiv"].format(t=total_seconds / self.HORIZ_DIVS))

    def set_peak_detect(self, on=True):
        self.inst.write(CMDS["acq_mode"].format(m="ENVelope" if on else "NORMal"))

    def enable_zoom(self, zoom_window_s, position_s=0.0):
        """Turn on the DLM split display: the main window stays on top and a
        magnified zoom window (span = zoom_window_s, centred position_s from the
        trigger) appears on the bottom. Best-effort — a measurement run still
        proceeds if the :ZOOM commands differ on your model."""
        try:
            self.inst.write(CMDS["zoom_mode"].format(s="ON"))
            self.inst.write(CMDS["zoom1_state"].format(s="ON"))
            self.inst.write(CMDS["zoom1_tdiv"].format(t=zoom_window_s / self.HORIZ_DIVS))
            self.inst.write(CMDS["zoom1_pos"].format(t=position_s))
        except Exception as e:
            print(f"[Scope] zoom setup skipped ({e}); verify :ZOOM commands for your model")

    def disable_zoom(self):
        try:
            self.inst.write(CMDS["zoom_mode"].format(s="OFF"))
        except Exception:
            pass

    # ---- trigger + single-shot ----------------------------------------- #
    def set_trigger(self, source_ch, level, slope="rising", mode="single"):
        self.inst.write(CMDS["trig_source"].format(src=source_ch))
        self.inst.write(CMDS["trig_level"].format(v=level))
        self.inst.write(CMDS["trig_slope"].format(s=_SLOPE.get(slope, "RISE")))
        self.inst.write(CMDS["trig_mode"].format(m="SINGle" if mode == "single" else mode.upper()))

    def arm_single(self):
        self.inst.write(CMDS["trig_mode"].format(m="SINGle"))
        self.inst.write(CMDS["acq_start"])

    def wait_trigger(self, timeout_s):
        """Poll until the single acquisition completes (acquisition stops).
        Returns True if it triggered, False on timeout. Status-bit semantics are
        model-specific — verify _RUNNING_BIT against your DLM manual."""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                cond = int(self.inst.query(CMDS["cond"]).strip())
                if not (cond & _RUNNING_BIT):   # acquisition stopped => triggered
                    return True
            except Exception:
                break
            time.sleep(0.05)
        return False

    def force_trigger(self):
        try:
            self.inst.write(CMDS["force_trig"])
        except Exception:
            self.inst.write(CMDS["acq_stop"])   # fall back: stop to freeze the record

    def measure_max(self, ch):
        self.inst.write(CMDS["meas_on"])
        self.inst.write(CMDS["item_max_on"].format(ch=ch))
        return parse_number(self.inst.query(CMDS["query_max"].format(ch=ch)),
                            unit="V", what=f"CH{ch} max")

    # ---- screenshot ----------------------------------------------------- #
    def save_screenshot(self, filepath):
        self.inst.write(CMDS["img_format"])
        raw = self.inst.query_binary_values(
            CMDS["img_send"], datatype="B", container=bytearray
        )
        with open(filepath, "wb") as f:
            f.write(bytes(raw))
        print(f"[Scope] screenshot -> {filepath}")

    def close(self):
        self.inst.close()
