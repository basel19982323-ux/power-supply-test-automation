"""Simulated instruments — drop-in fakes with the identical role interface.

Used when Simulation mode is on (no hardware connected). A shared SimBench holds
the "bench state" (PD voltage for the Dynamic test; AC on/off + a modelled VDS
turn-off spike for the VDS test) so the fake scope can fabricate believable
readings — keeping the test types and runner completely hardware-agnostic.
"""
import base64
import math
import os

# Minimal valid 1x1 PNG, used as a last-resort placeholder screenshot.
_PLACEHOLDER_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


class SimBench:
    """Shared state between the simulated instruments for one run."""

    def __init__(self, wobble_pct=2.0, fault_profiles=None,
                 vds_reflected=100.0, vds_spike_factor=1.2,
                 steady_out=20.0, ovp_vout=28.0, ovp_vds_factor=1.3, faults=None):
        # Fault switches for tests (the config's `simulation:` section), e.g.
        #   reading_scale: 10   -> scope readings x10 (probe attenuation set wrong)
        #   scope_nan: true     -> the scope answers "no value" (9.91E37 = NaN) for
        #                          captured / dynamic readings
        #   probe_disconnected: true   -> the VDS probe (CH1) reads only noise
        #   scope_never_triggers: true -> the single-shot never fires
        #   scope_not_rearmed: true    -> :STARt is ignored, the old waveform stays
        #   scope_max_top: 500  -> the scope can't show more than 500 V full-scale
        #                          (range limit) and silently clamps, so the top of
        #                          the screen is lower than the app asked for
        self.faults = dict(faults or {})
        # Dynamic Output Response test
        self.pd_voltage = 5.0
        self.wobble_pct = wobble_pct
        self.fault_profiles = set(fault_profiles or ())
        # VDS Turn-off test
        self.ac_voltage = 0.0
        self.ac_on = False
        self.vds_reflected = vds_reflected        # V added to bulk for steady VDS peak
        self.vds_spike_factor = vds_spike_factor  # turn-off spike = steady * this
        # VDS-at-OVP test
        self.load_a = 0.0                         # static CC load current
        self.steady_out = steady_out              # steady output before OVP (CH2)
        self.ovp_vout = ovp_vout                  # output peak when OVP trips (CH2)
        self.ovp_vds_factor = ovp_vds_factor      # VDS during OVP = steady VDS * this


class SimACSource:
    role = "ac_source"

    def __init__(self, bench):
        self.bench = bench
        self.idn = "SIM,ITECH-AC,0,1.0"
        print(f"[AC source] {self.idn}")

    def apply(self, voltage, frequency, settle_s=2.0):
        self.bench.ac_voltage = float(voltage)
        self.bench.ac_on = True
        print(f"[AC source] (sim) set {voltage} V / {frequency} Hz")
        return float(voltage)

    def off(self):
        self.bench.ac_on = False
        print("[AC source] (sim) output OFF")

    def close(self):
        pass


class SimLoad:
    role = "e_load"

    def __init__(self, bench):
        self.bench = bench
        self.idn = "SIM,ITECH-LOAD,0,1.0"
        print(f"[E-load] {self.idn}")

    def start_transient(self, i_low, i_high, freq_hz, duty_pct, slew_a_us):
        print(f"[E-load] (sim) transient {i_low}<->{i_high} A @ {freq_hz} Hz")

    def set_cc(self, current):
        self.bench.load_a = float(current)
        print(f"[E-load] (sim) static CC {current} A")

    def stop(self):
        pass

    def close(self):
        pass


class SimScope:
    role = "scope"
    VERT_DIVS = 8

    def __init__(self, bench):
        self.bench = bench
        self.idn = "SIM,YOKOGAWA-DLM,0,1.0"
        self._last = (5.1, 4.9, 1)          # dynamic test
        self._mode = "dynamic"
        # VDS single-shot state
        self._v_top = {}           # per-channel top-of-screen voltage
        self._v_bottom = {}
        self._armed = False
        self._forced = False
        self._last_clipped = False
        self._vds_last = (0.0, 0.0, 0.0, False)
        self._main_window = 0.05
        self._zoom = None          # (zoom_window_s, position_s) when split display on
        self._trig_source = None   # trigger source channel (2 => OVP-style test)
        self._ovp = {"vds": 0.0, "vds_top": 0.0, "vds_clip": False,
                     "vout": 0.0, "vout_top": 0.0}
        print(f"[Scope] {self.idn}")

    # ---- Dynamic Output Response ---- #
    def setup_measurements(self, channel):
        pass

    def read_vmax_vmin(self, channel):
        self._mode = "dynamic"
        v = self.bench.pd_voltage
        swing = self.bench.wobble_pct / 100.0
        for label in self.bench.fault_profiles:
            if abs(self._label_to_v(label) - v) < 1e-6:
                swing = 0.10
        scale = float(self.bench.faults.get("reading_scale", 1.0))
        vmax = v * (1 + swing) * scale
        vmin = v * (1 - swing) * scale
        if self.bench.faults.get("scope_nan"):
            vmax = vmin = float("nan")
        self._last = (vmax, vmin, channel)
        print(f"[Scope] (sim) CH{channel}: Vmax={vmax:.4f} V, Vmin={vmin:.4f} V")
        return vmax, vmin

    @staticmethod
    def _label_to_v(label):
        try:
            return float(str(label).lower().replace("v", "").strip())
        except ValueError:
            return -1.0

    # ---- VDS single-shot: channels / vertical / trigger ---- #
    def enable_channel(self, ch, on=True):
        pass

    def configure_channel(self, ch, coupling="DC", probe_atten=None, bandwidth=None):
        print(f"[Scope] (sim) CH{ch} coupling={coupling} probe={probe_atten}")

    def set_vertical(self, ch, vdiv, offset=0.0):
        self._v_top[ch] = offset + vdiv * self.VERT_DIVS / 2
        max_top = self.bench.faults.get("scope_max_top")
        if max_top:                               # like a real scope: clamp silently
            self._v_top[ch] = min(self._v_top[ch], float(max_top))
        self._v_bottom[ch] = offset - vdiv * self.VERT_DIVS / 2

    def screen_top(self, ch):
        return self._v_top.get(ch, 1e12)

    def read_screen_top(self, ch):
        return self._v_top.get(ch, 1e12)

    def screen_bottom(self, ch):
        return self._v_bottom.get(ch, -1e12)

    def set_timebase(self, total_seconds):
        self._main_window = total_seconds

    def set_peak_detect(self, on=True):
        pass

    def enable_zoom(self, zoom_window_s, position_s=0.0):
        self._zoom = (zoom_window_s, position_s)

    def disable_zoom(self):
        self._zoom = None

    def set_trigger(self, source_ch, level, slope="rising", mode="single"):
        self._trig_source = source_ch
        self._mode = "ovp" if source_ch == 2 else "vds"

    def arm_single(self):
        if self.bench.faults.get("scope_not_rearmed"):
            return False                      # the old capture stays on screen
        self._armed = True
        self._forced = False
        return True

    def wait_trigger(self, timeout_s, cancel=None):
        # Turn-off: fires when AC goes off. OVP: fires on the (simulated) operator
        # opening the optocoupler after arming.
        if cancel is not None:
            cancel()
        if self.bench.faults.get("scope_never_triggers"):
            return False
        if self._trig_source == 2:
            return bool(self._armed)
        return bool(self._armed and not self.bench.ac_on)

    def stop_acquisition(self):
        self._armed = False

    def _steady_vds(self):
        return self.bench.ac_voltage * 1.41421 + self.bench.vds_reflected

    def measure_max(self, ch):
        ovp = (self._trig_source == 2)
        captured = self._armed and (ovp or (not self.bench.ac_on) or self._forced)
        if captured and ovp:
            true_val = (self.bench.ovp_vout if ch == 2
                        else self._steady_vds() * self.bench.ovp_vds_factor)
        elif captured:                                  # turn-off spike
            true_val = self._steady_vds() * self.bench.vds_spike_factor
        else:                                           # pre-arm steady
            true_val = self.bench.steady_out if ch == 2 else self._steady_vds()

        if self.bench.faults.get("probe_disconnected") and ch == 1:
            true_val = 0.3                                # noise on an open probe
        top = self._v_top.get(ch, 1e12)
        clipped = true_val > top
        val = min(true_val, top)
        if captured and ovp:
            self._mode = "ovp"
            if ch == 2:
                self._ovp["vout"], self._ovp["vout_top"] = val, top
            else:
                self._ovp.update(
                    vds=val, vds_top=top, vds_clip=clipped,
                    vds_steady=self._steady_vds(),
                    bulk=self.bench.ac_voltage * 1.41421,
                    main_ms=self._main_window * 1000.0,
                    zoom_ms=(self._zoom[0] * 1000.0 if self._zoom else 50.0))
        elif captured:
            self._mode = "vds"
            self._vds_last = (self._steady_vds(),
                              self._steady_vds() * self.bench.vds_spike_factor,
                              top, clipped)
        if captured and self.bench.faults.get("scope_nan"):
            return float("nan")
        return val

    # ---- screenshot ---- #
    def save_screenshot(self, filepath):
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        ok = False
        if self._mode == "ovp":
            ok = _draw_ovp(filepath, self._ovp, self.bench.steady_out)
        elif self._mode == "vds":
            steady, spike, top, clipped = self._vds_last
            if self._zoom:
                ok = _draw_vds_split(filepath, steady, spike, top, clipped,
                                     self._main_window, self._zoom[0])
            else:
                ok = _draw_vds_turnoff(filepath, steady, spike, top, clipped)
        else:
            ok = _draw_dynamic_waveform(filepath, *self._last)
        if not ok:
            with open(filepath, "wb") as f:
                f.write(_PLACEHOLDER_PNG)
        print(f"[Scope] (sim) screenshot -> {filepath}")

    def close(self):
        pass


class SimPowerZ:
    role = "powerz"

    def __init__(self, bench):
        self.bench = bench

    def request_profile(self, label, voltage):
        self.bench.pd_voltage = float(voltage)
        print(f"[Power-Z] (sim) profile {label} ({voltage} V)")

    def close(self):
        pass


# --------------------------------------------------------------------------- #
# Fake screenshot rendering (Pillow). Returns False if Pillow is unavailable.
# --------------------------------------------------------------------------- #
def _new_scope_image():
    from PIL import Image, ImageDraw
    w, h = 640, 400
    img = Image.new("RGB", (w, h), (12, 16, 28))
    d = ImageDraw.Draw(img)
    for gx in range(0, w, w // 10):
        d.line([(gx, 0), (gx, h)], fill=(30, 40, 55))
    for gy in range(0, h, h // 8):
        d.line([(0, gy), (w, gy)], fill=(30, 40, 55))
    return img, d, w, h


def _draw_dynamic_waveform(filepath, vmax, vmin, channel):
    if not (math.isfinite(vmax) and math.isfinite(vmin)):
        return False                     # nothing to draw -> placeholder image
    try:
        img, d, w, h = _new_scope_image()
    except ImportError:
        return False
    span = max(vmax - vmin, 0.05)
    top, bottom = 60, h - 60

    def y_of(v):
        frac = (v - (vmin - span)) / (span * 3)
        return int(bottom - frac * (bottom - top))

    yhi, ylo = y_of(vmax), y_of(vmin)
    pts, x, level = [], 20, ylo
    seg = (w - 40) // 8
    for _ in range(9):
        pts.append((x, level))
        level = yhi if level == ylo else ylo
        pts.append((x, level))
        x += seg
    d.line(pts, fill=(70, 230, 140), width=2)
    d.text((16, 12), f"CH{channel}  DYNAMIC OUTPUT RESPONSE (SIM)", fill=(200, 210, 220))
    d.text((16, h - 26), f"Vmax {vmax:.3f} V", fill=(120, 235, 170))
    d.text((160, h - 26), f"Vmin {vmin:.3f} V", fill=(120, 235, 170))
    d.text((300, h - 26), f"Vpp {vmax - vmin:.3f} V", fill=(120, 235, 170))
    img.save(filepath, "PNG")
    return True


def _draw_vds_turnoff(filepath, steady, spike, top, clipped):
    """Switching pulses at the steady VDS level, then the turn-off overshoot."""
    try:
        img, d, w, h = _new_scope_image()
    except ImportError:
        return False
    baseline = h - 40
    ceiling = 30
    full = max(top, spike, steady * 1.2, 1.0)

    def y_of(v):
        y = baseline - (v / full) * (baseline - ceiling)
        return int(max(ceiling, min(baseline, y)))

    y0 = baseline
    ys = y_of(steady)
    # steady-state switching pulses (left third)
    x, seg = 20, 24
    for _ in range(5):
        d.line([(x, y0), (x, ys)], fill=(70, 230, 140), width=2)
        d.line([(x, ys), (x + seg // 2, ys)], fill=(70, 230, 140), width=2)
        d.line([(x + seg // 2, ys), (x + seg // 2, y0)], fill=(70, 230, 140), width=2)
        d.line([(x + seg // 2, y0), (x + seg, y0)], fill=(70, 230, 140), width=2)
        x += seg
    # turn-off marker + overshoot spike + decay
    d.line([(x, 0), (x, h)], fill=(90, 90, 140), width=1)
    yspk = y_of(min(spike, top) if clipped else spike)
    d.line([(x, y0), (x + 8, yspk)], fill=(255, 120, 120), width=2)
    if clipped:
        d.line([(x + 8, yspk), (x + 60, yspk)], fill=(255, 120, 120), width=3)  # flat-topped = clipped
    else:
        d.line([(x + 8, yspk), (x + 24, y_of(spike * 0.7))], fill=(255, 120, 120), width=2)
    # decaying envelope after the event
    px, py = x + 60, yspk if clipped else y_of(spike * 0.7)
    for i in range(1, 12):
        nx = px + 30
        ny = y_of(max(steady * (0.9 ** i), 0))
        d.line([(px, py), (nx, ny)], fill=(70, 230, 140), width=2)
        px, py = nx, ny
        if px > w - 10:
            break
    d.text((16, 12), "CH1  VDS TURN-OFF (SIM)", fill=(200, 210, 220))
    tag = "  [CLIPPED]" if clipped else ""
    d.text((16, h - 26), f"VDS max {min(spike, top) if clipped else spike:.1f} V{tag}",
           fill=(255, 170, 120) if clipped else (120, 235, 170))
    img.save(filepath, "PNG")
    return True


def _draw_vds_split(filepath, steady, spike, top, clipped, main_window_s, zoom_window_s):
    """DLM-style split display: MAIN (wide, bulk-cap discharge envelope) on top,
    ZOOM (turn-off detail) on the bottom."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False
    w, h = 640, 400
    img = Image.new("RGB", (w, h), (12, 16, 28))
    d = ImageDraw.Draw(img)
    full = max(top, spike, steady * 1.2, 1.0)
    peak = min(spike, top) if clipped else spike

    def grid(x0, y0, x1, y1):
        for gx in range(x0, x1 + 1, (x1 - x0) // 10):
            d.line([(gx, y0), (gx, y1)], fill=(30, 40, 55))
        for gy in range(y0, y1 + 1, (y1 - y0) // 4):
            d.line([(x0, gy), (x1, gy)], fill=(30, 40, 55))

    # ---- MAIN (top): wide window, bulk-cap discharge envelope ---- #
    tx0, ty0, tx1, ty1 = 16, 24, w - 16, 188
    grid(tx0, ty0, tx1, ty1)

    def ty(v):
        return int(max(ty0, min(ty1, ty1 - (v / full) * (ty1 - ty0))))

    turn = tx0 + int((tx1 - tx0) * 0.32)           # turn-off happens ~1/3 in
    d.line([(tx0, ty(steady)), (turn, ty(steady))], fill=(70, 230, 140), width=2)  # steady
    d.line([(tx0, ty(0)), (tx1, ty(0))], fill=(70, 230, 140), width=1)             # baseline
    d.line([(turn, ty0), (turn, ty1)], fill=(120, 120, 170), width=1)             # turn-off
    d.line([(turn, ty(steady)), (turn + 4, ty(peak))], fill=(255, 120, 120), width=2)
    # decaying discharge envelope after turn-off
    px, py = turn + 4, ty(peak)
    for i in range(1, 40):
        nx = turn + 4 + i * (tx1 - turn - 4) // 40
        nv = max(steady * (0.90 ** i), 0)
        ny = ty(nv)
        d.line([(px, py), (nx, ny)], fill=(70, 230, 140), width=2)
        px, py = nx, ny
    # highlight the region shown in the zoom pane
    d.rectangle([turn - 10, ty0 + 2, turn + 26, ty1 - 2], outline=(230, 200, 90))
    d.text((tx0 + 2, ty0 + 2), f"MAIN  {main_window_s * 1000:.0f} ms  (bulk-cap discharge)",
           fill=(200, 210, 220))

    d.line([(0, 200), (w, 200)], fill=(60, 70, 90), width=1)  # pane divider

    # ---- ZOOM (bottom): turn-off detail ---- #
    zx0, zy0, zx1, zy1 = 16, 214, w - 16, 384
    grid(zx0, zy0, zx1, zy1)

    def zy(v):
        return int(max(zy0, min(zy1, zy1 - (v / full) * (zy1 - zy0))))

    x, seg, y0, ys = zx0 + 8, 26, zy(0), zy(steady)
    for _ in range(5):
        d.line([(x, y0), (x, ys)], fill=(70, 230, 140), width=2)
        d.line([(x, ys), (x + seg // 2, ys)], fill=(70, 230, 140), width=2)
        d.line([(x + seg // 2, ys), (x + seg // 2, y0)], fill=(70, 230, 140), width=2)
        d.line([(x + seg // 2, y0), (x + seg, y0)], fill=(70, 230, 140), width=2)
        x += seg
    d.line([(x, zy0), (x, zy1)], fill=(120, 120, 170), width=1)
    yspk = zy(peak)
    d.line([(x, y0), (x + 8, yspk)], fill=(255, 120, 120), width=2)
    if clipped:
        d.line([(x + 8, yspk), (x + 70, yspk)], fill=(255, 120, 120), width=3)
    else:
        d.line([(x + 8, yspk), (x + 30, zy(spike * 0.7))], fill=(255, 120, 120), width=2)
    d.text((zx0 + 2, zy0 + 2), f"ZOOM  {zoom_window_s * 1000:.0f} ms  (turn-off detail)",
           fill=(200, 210, 220))
    tag = "  [CLIPPED]" if clipped else ""
    d.text((zx0 + 2, zy1 - 16), f"VDS max {peak:.1f} V{tag}",
           fill=(255, 170, 120) if clipped else (120, 235, 170))
    img.save(filepath, "PNG")
    return True


def _draw_ovp(filepath, ovp, steady_out):
    """Yokogawa-style split display of BOTH channels: MAIN (top, unzoomed) and
    ZOOM (bottom, magnified) each show CH1 (VDS, green/red) and CH2 (Vout, yellow)
    on one graticule. On the OVP event the feedback loop is broken, the output
    jerks up past the trigger and trips OVP -> the controller latches off:
    VDS switching stops (drops to the bulk DC level) and the output collapses."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False
    w, h = 640, 400
    img = Image.new("RGB", (w, h), (12, 16, 28))
    d = ImageDraw.Draw(img)

    vds_spike = ovp.get("vds", 0.0)
    vds_steady = ovp.get("vds_steady") or (vds_spike / 1.3 if vds_spike else 0.0)
    bulk = ovp.get("bulk") or max(vds_steady * 0.72, vds_steady - 120.0, 0.0)
    vout_ovp = ovp.get("vout", steady_out)
    vds_full = max(ovp.get("vds_top", 0.0), vds_spike, vds_steady, 1.0)
    vout_full = max(ovp.get("vout_top", 0.0), vout_ovp, steady_out * 1.6, 1.0)
    clipped = ovp.get("vds_clip", False)
    main_ms, zoom_ms = ovp.get("main_ms", 500.0), ovp.get("zoom_ms", 50.0)
    GREEN, RED, YELLOW, MARK = (70, 230, 140), (255, 120, 120), (235, 220, 90), (120, 120, 170)

    def grid(x0, y0, x1, y1):
        for gx in range(x0, x1 + 1, max(1, (x1 - x0) // 10)):
            d.line([(gx, y0), (gx, y1)], fill=(30, 40, 55))
        for gy in range(y0, y1 + 1, max(1, (y1 - y0) // 4)):
            d.line([(x0, gy), (x1, gy)], fill=(30, 40, 55))

    def pane(x0, y0, x1, y1, kind):
        grid(x0, y0, x1, y1)
        span = y1 - y0
        c1b, c1t = y0 + int(span * 0.52), y0 + 6      # CH1 VDS band (upper)
        c2b, c2t = y1 - 6, y0 + int(span * 0.58)      # CH2 Vout band (lower)

        def yv(v):
            return int(max(c1t, min(c1b, c1b - (v / vds_full) * (c1b - c1t))))

        def yo(v):
            return int(max(c2t, min(c2b, c2b - (v / vout_full) * (c2b - c2t))))

        ev = x0 + int((x1 - x0) * (0.34 if kind == "main" else 0.42))
        # CH1 VDS: steady switching -> spike -> shutdown (switching stops, flat at bulk)
        base, ys = yv(0), yv(vds_steady)
        seg = 18 if kind == "main" else 30
        x = x0 + 4
        while x + seg < ev:
            d.line([(x, base), (x, ys)], fill=GREEN, width=2)
            d.line([(x, ys), (x + seg // 2, ys)], fill=GREEN, width=2)
            d.line([(x + seg // 2, ys), (x + seg // 2, base)], fill=GREEN, width=2)
            d.line([(x + seg // 2, base), (x + seg, base)], fill=GREEN, width=2)
            x += seg
        yspk, ybulk = yv(vds_spike), yv(bulk)
        d.line([(ev, base), (ev + 5, yspk)], fill=RED, width=2)
        if clipped:
            d.line([(ev + 5, yspk), (ev + 34, yspk)], fill=RED, width=3)
            after = ev + 34
        else:
            after = ev + 5
        d.line([(after, yspk), (after + 14, ybulk)], fill=GREEN, width=2)
        d.line([(after + 14, ybulk), (x1 - 4, ybulk)], fill=GREEN, width=2)
        # CH2 Vout: steady -> jerk up to OVP -> collapse to 0 (device shuts down)
        trig = (steady_out + vout_ovp) / 2
        d.line([(x0, yo(trig)), (x1, yo(trig))], fill=MARK, width=1)
        d.line([(x0 + 4, yo(steady_out)), (ev, yo(steady_out))], fill=YELLOW, width=2)
        d.line([(ev, yo(steady_out)), (ev + 8, yo(vout_ovp))], fill=YELLOW, width=2)
        cx = ev + 8
        pts = [(cx, yo(vout_ovp))]
        for i in range(1, 11):
            pts.append((cx + (x1 - 4 - cx) * i // 11, yo(max(vout_ovp * (0.72 ** i), 0))))
        d.line(pts, fill=YELLOW, width=2)
        d.line([(ev, y0), (ev, y1)], fill=MARK, width=1)   # event marker across channels

    pane(16, 26, w - 16, 188, "main")
    d.text((18, 27), f"MAIN  {main_ms:.0f} ms   CH1 VDS + CH2 Vout", fill=(200, 210, 220))
    d.line([(0, 200), (w, 200)], fill=(60, 70, 90), width=1)
    pane(16, 214, w - 16, 384, "zoom")
    tag = "  [CLIP]" if clipped else ""
    d.text((18, 215), f"ZOOM  {zoom_ms:.0f} ms   VDS max {vds_spike:.0f} V   OVP "
           f"{vout_ovp:.0f} V{tag}", fill=(200, 210, 220))
    img.save(filepath, "PNG")
    return True
