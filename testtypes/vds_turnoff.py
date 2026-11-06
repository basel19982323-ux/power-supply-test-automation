"""VDS Max during AC input turn-off — flyback primary MOSFET stress test.

Physical setup: scope probe on the primary MOSFET drain -> primary ground
(V_DS). With the DUT running, the app cuts the AC input (AC source output OFF),
single-shot captures the turn-off transient, and reads the peak V_DS. Because
the scope zoom/trigger isn't preset, it auto-ranges: it measures the steady-state
switching V_DS to set the vertical scale with headroom, enables peak-detect over
a capture window, arms a single-shot trigger just above the steady peak, then
cuts AC. If the captured peak clips the top of the screen, it widens the range,
restarts the DUT, and re-cuts AC (up to a retry limit).

PASS/FAIL is V_DS,max vs. the FET's V_DS rating x a derating margin. A capture
that is still clipped after the last retry is FAIL ("≥ X V") only if the scope's
full-scale X is already above the limit; otherwise it is ERROR CLIPPED. The load
condition is whatever you set up physically (e-load, resistor, or none) — this
test does not control a load.
"""
import os

from core.test_base import Column, Field, Section, TableColumn, TestType
from core.verdict import PointError, judge_upper

from .common import (PROBE_CHECK_MAX_X, PROBE_CHECK_MAX_X_RATING,
                     PROBE_CHECK_MIN_X, check_steady_vds,
                     clip_check, quiet_off, vds_limit)


class VDSTurnoffTest(TestType):
    id = "vds_turnoff"
    name = "VDS Max — AC Turn-off"
    description = ("Flyback primary MOSFET: peak drain-source voltage during AC input "
                  "turn-off, single-shot captured with scope auto-ranging.")
    required_instruments = ["ac_source", "scope"]

    # A datasheet-assist affordance the Setup tab renders (fills the rating field).
    wants_datasheet = True
    datasheet_field = ("limits", "fet_vds_rating_v")

    result_columns = [
        Column("ac_condition", "AC condition", "text"),
        Column("vds_max_v", "VDS max (V)", "number", 1),
        Column("limit_v", "Limit (V)", "number", 1),
        Column("fet_rating_v", "FET rating (V)", "number", 0),
        Column("retries", "Retries", "number", 0),
        Column("result", "Result", "result"),
        Column("error_code", "Code", "text"),
        Column("reason", "Reason", "text"),
    ]
    csv_fields = ["timestamp", "dut", "ac_condition", "vin_set_v", "freq_hz",
                  "fet_rating_v", "derating_pct", "limit_v", "vds_max_v",
                  "clipped", "retries", "result", "screenshot",
                  "error_code", "reason"]

    # ---- configuration -------------------------------------------------- #
    def default_config(self) -> dict:
        return {
            "dut_name": "DUT-01",
            "instruments": {"ac_source": "", "scope": ""},
            "ac_conditions": [
                {"label": "264Vac/50Hz", "voltage": 264, "frequency": 50},
                {"label": "90Vac/60Hz", "voltage": 90, "frequency": 60},
            ],
            "scope": {
                "channel": 1,
                "probe_atten": 100,          # high-voltage probe ratio
                "coupling": "DC",
                # DLM split display: MAIN (top) wide + ZOOM (bottom) detail.
                "main_window_s": 0.5,        # top: wide, shows bulk-cap charge/discharge
                "zoom_window_s": 0.05,       # bottom: turn-off detail where VDS peaks
                "zoom_position_s": 0.0,      # zoom centre, seconds from the trigger
                "vertical_headroom_x": 2.0,  # initial full-scale = steady peak x this
                "trigger_level_factor": 1.1, # trigger above steady peak x this
                "trigger_timeout_s": 5.0,
                "max_retries": 3,
                "settle_s": 2.0,             # DUT stabilize time after AC on
                "probe_check_min_x": PROBE_CHECK_MIN_X,  # steady VDS vs AC peak
                "probe_check_max_x": PROBE_CHECK_MAX_X,
                "probe_check_max_x_rating": PROBE_CHECK_MAX_X_RATING,
            },
            "limits": {
                "fet_vds_rating_v": 650.0,
                "derating_pct": 90.0,        # PASS if VDS max <= rating * derating/100
            },
        }

    def config_schema(self) -> list:
        return [
            Section(
                key="ac_conditions", title="AC input conditions", kind="table",
                help="Input conditions to test the turn-off at (high line is worst case).",
                columns=[
                    TableColumn("label", "Label", "text"),
                    TableColumn("voltage", "Voltage (Vac)", "number"),
                    TableColumn("frequency", "Frequency (Hz)", "number"),
                ],
            ),
            Section(
                key="scope", title="Scope & capture", kind="group",
                help="Split display: the MAIN (top) window is wide so the bulk-cap "
                     "charge/discharge envelope is visible; the ZOOM (bottom) window "
                     "shows the turn-off detail. Vertical scale auto-ranges from the "
                     "measured steady-state VDS.",
                fields=[
                    Field("channel", "VDS channel", "int", 1, ""),
                    Field("probe_atten", "Probe attenuation", "number", 100, "x"),
                    Field("main_window_s", "Main window (top)", "number", 0.5, "s"),
                    Field("zoom_window_s", "Zoom window (bottom)", "number", 0.05, "s"),
                    Field("zoom_position_s", "Zoom position", "number", 0.0, "s"),
                    Field("vertical_headroom_x", "Initial headroom", "number", 2.0, "x"),
                    Field("trigger_level_factor", "Trigger above steady", "number", 1.1, "x"),
                    Field("trigger_timeout_s", "Trigger timeout", "number", 5.0, "s"),
                    Field("max_retries", "Max auto-range retries", "int", 3, ""),
                    Field("settle_s", "DUT settle after AC on", "number", 2.0, "s"),
                    Field("probe_check_min_x", "Probe check: min VDS", "number",
                          PROBE_CHECK_MIN_X, "x AC peak"),
                    Field("probe_check_max_x", "Probe check: max VDS", "number",
                          PROBE_CHECK_MAX_X, "x AC peak"),
                    Field("probe_check_max_x_rating", "Probe check: max VDS at least",
                          "number", PROBE_CHECK_MAX_X_RATING, "x FET rating"),
                ],
            ),
            Section(
                key="limits", title="Pass/fail (FET VDS rating)", kind="group",
                help="Limit = rating x derating%. Use the datasheet button below to "
                     "fill the rating from a MOSFET PDF.",
                fields=[
                    Field("fet_vds_rating_v", "FET VDS rating", "number", 650.0, "V"),
                    Field("derating_pct", "Derating", "number", 90.0, "%"),
                ],
            ),
        ]

    # ---- execution ------------------------------------------------------ #
    def plan(self, config: dict) -> list:
        points = []
        for ac in config["ac_conditions"]:
            points.append({
                "label": f"VDS turn-off @ {ac['label']}",
                "ac_condition": ac["label"],
                "ac_voltage": float(ac["voltage"]),
                "ac_frequency": float(ac["frequency"]),
            })
        return points

    def prepare(self, instruments, config, ctx):
        sc = config["scope"]
        scope = instruments["scope"]
        scope.configure_channel(sc["channel"], coupling=sc.get("coupling", "DC"),
                                probe_atten=sc.get("probe_atten"))
        scope.set_peak_detect(True)
        # MAIN (top) = wide window to see the bulk-cap charge/discharge envelope;
        # ZOOM (bottom) = the turn-off detail where the VDS peak is resolved.
        scope.set_timebase(float(sc.get("main_window_s", 0.5)))
        if hasattr(scope, "enable_zoom"):
            scope.enable_zoom(float(sc.get("zoom_window_s", 0.05)),
                              float(sc.get("zoom_position_s", 0.0)))

    def execute_point(self, point, instruments, config, ctx) -> dict:
        try:
            return self._measure(point, instruments, config, ctx)
        except BaseException:
            # Whatever went wrong, leave the DUT de-energized before reporting it.
            quiet_off(ctx, ("turn the AC source off", instruments["ac_source"].off))
            raise

    def _measure(self, point, instruments, config, ctx) -> dict:
        ac = instruments["ac_source"]
        scope = instruments["scope"]
        sc = config["scope"]
        ch = int(sc["channel"])
        divs = getattr(scope, "VERT_DIVS", 8)

        rating, _, limit_v = vds_limit(config)

        headroom = float(sc.get("vertical_headroom_x", 2.0))
        trig_factor = float(sc.get("trigger_level_factor", 1.1))
        timeout = float(sc.get("trigger_timeout_s", 5.0))
        max_retries = int(sc.get("max_retries", 3))
        settle = float(sc.get("settle_s", 2.0))
        dut = config.get("dut_name", "DUT")

        def establish_ac():
            ac.apply(point["ac_voltage"], point["ac_frequency"])
            if not ctx.simulate:
                ctx.sleep(settle)

        def measure_steady():
            return check_steady_vds(scope.measure_max(ch), point["ac_voltage"], sc,
                                    rating)

        establish_ac()
        steady = measure_steady()
        target_top = max(steady * headroom, limit_v * 1.1, steady * 1.2)

        vds_max, clipped, retries = steady, True, 0
        while True:
            vdiv = target_top / divs
            scope.set_vertical(ch, vdiv, offset=target_top / 2.0)   # 0..target_top visible
            level = steady * trig_factor
            scope.set_trigger(ch, level=level, slope="rising", mode="single")
            if not scope.arm_single():
                raise PointError("STALE_CAPTURE", "the scope did not confirm a new "
                                 "single-shot, so the waveform on screen is old; AC was "
                                 "turned off without using it", retries=retries)
            ctx.status(f"    armed single-shot; cutting AC (full-scale {target_top:.0f} V)")
            ac.off()
            if not scope.wait_trigger(timeout, cancel=ctx.check_stop):
                # No forced capture: a forced capture shows whatever is on the
                # screen, not the turn-off peak, so it could falsely PASS.
                scope.stop_acquisition()
                raise PointError("NO_TRIGGER", f"no capture above {level:.0f} V within "
                                 f"{timeout:g} s after AC off", retries=retries)
            vds_max = scope.measure_max(ch)
            top = scope.read_screen_top(ch)          # what the SCOPE really shows
            clipped = clip_check(vds_max, top)
            if not clipped or retries >= max_retries:
                break
            retries += 1
            target_top *= 1.6
            ctx.status(f"    capture clipped at {top:.0f} V; retry {retries} -> "
                       f"full-scale {target_top:.0f} V")
            establish_ac()
            steady = measure_steady()

        tag = f"{dut}_VDS_{point['ac_condition'].replace('/', '_')}"
        shot_rel = os.path.join("screenshots", f"{tag}.png")
        scope.save_screenshot(os.path.join(ctx.run_dir, shot_rel))
        ac.off()  # leave DUT de-energized between points

        j = judge_upper(vds_max, limit_v, what="VDS max", clipped=clipped, screen_top=top)
        ctx.status(f"    {j.reason} -> {j.result}")

        return self.make_row(point, config, j.result, j.code, j.reason,
                             vds_max_v=j.shown, clipped=clipped,
                             retries=retries, screenshot=shot_rel)

    def identity(self, point, config):
        rating, derating, limit_v = vds_limit(config)
        return {
            "ac_condition": point["ac_condition"],
            "vin_set_v": point["ac_voltage"],
            "freq_hz": point["ac_frequency"],
            "fet_rating_v": rating,
            "derating_pct": derating,
            "limit_v": round(limit_v, 1),
        }
