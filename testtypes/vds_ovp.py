"""VDS at OVP condition — flyback primary MOSFET stress when the feedback loop
is broken (over-voltage protection event).

Physical setup: scope CH1 on the primary MOSFET drain -> primary ground (V_DS),
scope CH2 on the DC output (V_out), the ITECH e-load holding a static load on the
output, AC source powering the DUT. With the DUT running normally (output steady
at ~20 V), the operator opens the optocoupler with a physical switch, breaking
the feedback loop; the controller loses regulation and the output jerks up until
OVP trips. The app arms a single-shot triggered on CH2 (output) rising above a
threshold, prompts the operator to open the switch, then captures the peak V_DS.

Like the VDS Turn-off test: CH1 auto-ranges, peak-detect + zoom split display,
retry if the capture clips, PASS/FAIL vs the FET V_DS rating x derating. Adds the
e-load (static CC) and a CH2-based trigger. The difference from Turn-off is only
the trigger condition and that the event is operator-initiated.
"""
import os
from datetime import datetime

from core.test_base import Column, Field, Section, TableColumn, TestType


class VDSOVPTest(TestType):
    id = "vds_ovp"
    name = "VDS at OVP (feedback break)"
    description = ("Flyback primary MOSFET: peak V_DS when the feedback loop is opened "
                  "and the output jerks up to OVP. Single-shot triggered on the output "
                  "(CH2), captured on CH1.")
    required_instruments = ["ac_source", "e_load", "scope"]

    wants_datasheet = True
    datasheet_field = ("limits", "fet_vds_rating_v")

    result_columns = [
        Column("ac_condition", "AC condition", "text"),
        Column("load_a", "Load (A)", "number", 2),
        Column("vout_ovp_v", "Vout OVP (V)", "number", 2),
        Column("vds_max_v", "VDS max (V)", "number", 1),
        Column("limit_v", "Limit (V)", "number", 1),
        Column("retries", "Retries", "number", 0),
        Column("result", "Result", "result"),
    ]
    csv_fields = ["timestamp", "dut", "ac_condition", "vin_set_v", "freq_hz", "load_a",
                  "vout_steady_v", "vout_ovp_v", "fet_rating_v", "derating_pct",
                  "limit_v", "vds_max_v", "clipped", "retries", "result", "screenshot"]

    # ---- configuration -------------------------------------------------- #
    def default_config(self) -> dict:
        return {
            "dut_name": "DUT-01",
            "instruments": {"ac_source": "", "e_load": "", "scope": ""},
            "ac_conditions": [
                {"label": "230Vac/50Hz", "voltage": 230, "frequency": 50},
            ],
            "load": {"current_a": 1.0},
            "scope": {
                "vds_channel": 1,
                "vout_channel": 2,
                "probe_atten": 100,          # CH1 high-voltage probe
                "vout_probe_atten": 10,      # CH2 probe
                "coupling": "DC",
                "vout_steady_v": 20.0,       # expected steady output before OVP
                "vout_trigger_level_v": 22.0,  # trigger when output rises above this
                "vout_fullscale_v": 40.0,    # CH2 vertical full-scale
                "main_window_s": 0.5,        # MAIN (top) wide window
                "zoom_window_s": 0.05,       # ZOOM (bottom) detail
                "zoom_position_s": 0.0,
                "vertical_headroom_x": 2.0,
                "trigger_timeout_s": 10.0,
                "max_retries": 2,
                "settle_s": 2.0,
            },
            "limits": {
                "fet_vds_rating_v": 650.0,
                "derating_pct": 90.0,
            },
        }

    def config_schema(self) -> list:
        return [
            Section(
                key="ac_conditions", title="AC input conditions", kind="table",
                help="Input condition(s) the DUT runs at during the test.",
                columns=[
                    TableColumn("label", "Label", "text"),
                    TableColumn("voltage", "Voltage (Vac)", "number"),
                    TableColumn("frequency", "Frequency (Hz)", "number"),
                ],
            ),
            Section(
                key="load", title="Static load (ITECH e-load)", kind="group",
                help="Constant-current load held on the DUT output during the test.",
                fields=[Field("current_a", "Load current", "number", 1.0, "A")],
            ),
            Section(
                key="scope", title="Scope, channels & trigger", kind="group",
                help="CH1 = VDS (auto-ranged), CH2 = output. The single-shot triggers "
                     "on CH2 rising above the trigger level (output jerking up). Split "
                     "display: wide MAIN on top, ZOOM detail on the bottom.",
                fields=[
                    Field("vds_channel", "VDS channel", "int", 1, ""),
                    Field("vout_channel", "Output channel", "int", 2, ""),
                    Field("probe_atten", "VDS probe atten.", "number", 100, "x"),
                    Field("vout_probe_atten", "Output probe atten.", "number", 10, "x"),
                    Field("vout_steady_v", "Steady output", "number", 20.0, "V"),
                    Field("vout_trigger_level_v", "Trigger above", "number", 22.0, "V"),
                    Field("vout_fullscale_v", "Output full-scale", "number", 40.0, "V"),
                    Field("main_window_s", "Main window (top)", "number", 0.5, "s"),
                    Field("zoom_window_s", "Zoom window (bottom)", "number", 0.05, "s"),
                    Field("zoom_position_s", "Zoom position", "number", 0.0, "s"),
                    Field("vertical_headroom_x", "Initial headroom", "number", 2.0, "x"),
                    Field("trigger_timeout_s", "Trigger timeout", "number", 10.0, "s"),
                    Field("max_retries", "Max auto-range retries", "int", 2, ""),
                    Field("settle_s", "DUT settle after AC on", "number", 2.0, "s"),
                ],
            ),
            Section(
                key="limits", title="Pass/fail (FET VDS rating)", kind="group",
                help="Limit = rating x derating%. Use the datasheet button to fill the "
                     "rating from a MOSFET PDF.",
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
                "label": f"VDS at OVP @ {ac['label']}",
                "ac_condition": ac["label"],
                "ac_voltage": float(ac["voltage"]),
                "ac_frequency": float(ac["frequency"]),
            })
        return points

    def prepare(self, instruments, config, ctx):
        sc = config["scope"]
        scope = instruments["scope"]
        vds_ch, vout_ch = int(sc["vds_channel"]), int(sc["vout_channel"])
        scope.enable_channel(vds_ch, True)
        scope.enable_channel(vout_ch, True)
        scope.configure_channel(vds_ch, coupling=sc.get("coupling", "DC"),
                                probe_atten=sc.get("probe_atten"))
        scope.configure_channel(vout_ch, coupling=sc.get("coupling", "DC"),
                                probe_atten=sc.get("vout_probe_atten"))
        scope.set_peak_detect(True)
        scope.set_timebase(float(sc.get("main_window_s", 0.5)))
        if hasattr(scope, "enable_zoom"):
            scope.enable_zoom(float(sc.get("zoom_window_s", 0.05)),
                              float(sc.get("zoom_position_s", 0.0)))
        # Fixed vertical for the output channel (0..full-scale).
        full = float(sc.get("vout_fullscale_v", 40.0))
        divs = getattr(scope, "VERT_DIVS", 8)
        scope.set_vertical(vout_ch, full / divs, offset=full / 2.0)

    def execute_point(self, point, instruments, config, ctx) -> dict:
        import time

        ac = instruments["ac_source"]
        eload = instruments["e_load"]
        scope = instruments["scope"]
        sc = config["scope"]
        lim = config["limits"]
        vds_ch, vout_ch = int(sc["vds_channel"]), int(sc["vout_channel"])
        divs = getattr(scope, "VERT_DIVS", 8)

        rating = float(lim.get("fet_vds_rating_v", 0) or 0)
        derating = float(lim.get("derating_pct", 100) or 100)
        limit_v = rating * derating / 100.0

        steady_out = float(sc.get("vout_steady_v", 20.0))
        trig_level = float(sc.get("vout_trigger_level_v", 22.0))
        headroom = float(sc.get("vertical_headroom_x", 2.0))
        timeout = float(sc.get("trigger_timeout_s", 10.0))
        max_retries = int(sc.get("max_retries", 2))
        settle = float(sc.get("settle_s", 2.0))
        load_a = float(config["load"]["current_a"])
        dut = config.get("dut_name", "DUT")

        ac.apply(point["ac_voltage"], point["ac_frequency"])
        eload.set_cc(load_a)
        if not ctx.simulate:
            time.sleep(settle)

        steady = scope.measure_max(vds_ch)                 # steady VDS (auto-range)
        target_top = max(steady * headroom, limit_v * 1.1, steady * 1.2)

        vds_max, vout_ovp, clipped, retries = steady, steady_out, True, 0
        while True:
            scope.set_vertical(vds_ch, target_top / divs, offset=target_top / 2.0)
            scope.set_trigger(vout_ch, level=trig_level, slope="rising", mode="single")
            scope.arm_single()
            ctx.status(f"    armed single-shot on CH{vout_ch} (output) rising > "
                       f"{trig_level:.1f} V; full-scale {target_top:.0f} V")
            if not ctx.simulate:
                ctx.prompt(
                    f"Open the optocoupler switch now (break the feedback loop). The "
                    f"output will jump up from {steady_out:.0f} V and trigger the "
                    f"capture. Click Continue once the output has jumped.")
            if not scope.wait_trigger(timeout):
                ctx.status("    no OVP trigger within timeout; forcing capture")
                scope.force_trigger()
            vds_max = scope.measure_max(vds_ch)
            vout_ovp = scope.measure_max(vout_ch)
            top = scope.screen_top(vds_ch)
            clipped = vds_max >= top - max(0.02 * top, 1.0)
            if not clipped or retries >= max_retries:
                break
            retries += 1
            target_top *= 1.6
            ctx.status(f"    VDS clipped at {top:.0f} V; retry {retries} -> "
                       f"full-scale {target_top:.0f} V")
            if not ctx.simulate:
                ctx.prompt("Capture clipped. Close the switch, let the output recover "
                           f"to {steady_out:.0f} V, then Continue to retry.")

        tag = f"{dut}_VDSOVP_{point['ac_condition'].replace('/', '_')}"
        shot_rel = os.path.join("screenshots", f"{tag}.png")
        scope.save_screenshot(os.path.join(ctx.run_dir, shot_rel))
        eload.stop()
        ac.off()

        result = "PASS" if (limit_v > 0 and vds_max <= limit_v) else "FAIL"
        note = " (CLIPPED)" if clipped else ""
        ctx.status(f"    VDS max {vds_max:.1f} V (Vout OVP {vout_ovp:.1f} V) "
                   f"limit {limit_v:.1f} V -> {result}{note}")

        return {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "dut": dut,
            "ac_condition": point["ac_condition"],
            "vin_set_v": point["ac_voltage"],
            "freq_hz": point["ac_frequency"],
            "load_a": load_a,
            "vout_steady_v": steady_out,
            "vout_ovp_v": round(vout_ovp, 2),
            "fet_rating_v": rating,
            "derating_pct": derating,
            "limit_v": round(limit_v, 1),
            "vds_max_v": round(vds_max, 1),
            "clipped": clipped,
            "retries": retries,
            "result": result,
            "screenshot": shot_rel,
        }
