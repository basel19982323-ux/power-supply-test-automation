"""Dynamic Output Response test — the first built-in TestType.

Automates: ITECH AC source + ITECH electronic load (transient mode) + Yokogawa
DLM scope + POWER-Z PD trigger. Walks the matrix (PD profiles x AC conditions),
reads Vmax/Vmin, captures a scope screenshot, and PASS/FAILs each point against
per-profile voltage limits (default +/-5%).

This is a direct port of the original runner.py matrix logic into the generic
TestType interface: plan() builds the point list, execute_point() runs one point.
"""
import os

from core.test_base import Column, Field, Section, TableColumn, TestType
from core.verdict import StopRunError, is_number, judge_window, rounded

from .common import LOAD_CHECK_PCT, check_load_current, quiet_off


class DynamicOutputResponseTest(TestType):
    id = "dynamic_output_response"
    name = "Dynamic Output Response"
    description = ("USB-C PD charger: output voltage regulation under dynamic load "
                   "steps, swept across AC input conditions and PD profiles.")
    required_instruments = ["powerz", "ac_source", "e_load", "scope"]

    result_columns = [
        Column("pd_profile", "PD profile", "text"),
        Column("ac_condition", "AC condition", "text"),
        Column("i_low_a", "I low (A)", "number", 2),
        Column("i_high_a", "I high (A)", "number", 2),
        Column("load_avg_a", "Load avg (A)", "number", 2),
        Column("vmax_v", "Vmax (V)", "number", 4),
        Column("vmin_v", "Vmin (V)", "number", 4),
        Column("vmin_limit_v", "Vmin limit", "number", 3),
        Column("vmax_limit_v", "Vmax limit", "number", 3),
        Column("result", "Result", "result"),
        Column("error_code", "Code", "text"),
        Column("reason", "Reason", "text"),
    ]
    csv_fields = ["timestamp", "dut", "pd_profile", "ac_condition", "vin_set_v",
                  "freq_hz", "i_low_a", "i_high_a", "vmax_v", "vmin_v",
                  "vmin_limit_v", "vmax_limit_v", "result", "screenshot",
                  "load_avg_a", "error_code", "reason"]

    # ---- configuration -------------------------------------------------- #
    def default_config(self) -> dict:
        return {
            "dut_name": "DUT-01",
            "powerz": {"mode": "manual"},
            "instruments": {"ac_source": "", "e_load": "", "scope": ""},
            "ac_conditions": [
                {"label": "90Vac/60Hz", "voltage": 90, "frequency": 60},
                {"label": "115Vac/60Hz", "voltage": 115, "frequency": 60},
                {"label": "230Vac/50Hz", "voltage": 230, "frequency": 50},
                {"label": "264Vac/50Hz", "voltage": 264, "frequency": 50},
            ],
            "pd_profiles": [
                {"label": "5V", "voltage": 5.0, "i_low_a": 0.0, "i_high_a": 3.0},
                {"label": "9V", "voltage": 9.0, "i_low_a": 0.0, "i_high_a": 3.0},
                {"label": "12V", "voltage": 12.0, "i_low_a": 0.0, "i_high_a": 3.0},
                {"label": "20V", "voltage": 20.0, "i_low_a": 0.0, "i_high_a": 5.0},
            ],
            "e_load_settings": {
                "transient_frequency_hz": 100,
                "duty_cycle_pct": 50,
                "slew_rate_a_per_us": 1.0,
                "load_check_pct": LOAD_CHECK_PCT,   # measured avg must be >= this %
            },
            "scope_settings": {
                "vout_channel": 1,
                "measure_cycles_wait_s": 3,
            },
            "limits": {
                "tolerance_pct": 5.0,
                "overrides": {},   # e.g. {"5V": {"vmin_abs": 4.75, "vmax_abs": 5.25}}
            },
        }

    def config_schema(self) -> list:
        return [
            Section(
                key="ac_conditions", title="AC input conditions", kind="table",
                help="Mains conditions swept on the ITECH AC source (inner loop).",
                columns=[
                    TableColumn("label", "Label", "text"),
                    TableColumn("voltage", "Voltage (Vac)", "number"),
                    TableColumn("frequency", "Frequency (Hz)", "number"),
                ],
            ),
            Section(
                key="pd_profiles", title="PD output profiles", kind="table",
                help="PD voltages requested via POWER-Z (outer loop) and their load steps.",
                columns=[
                    TableColumn("label", "Label", "text"),
                    TableColumn("voltage", "Voltage (V)", "number"),
                    TableColumn("i_low_a", "I low (A)", "number"),
                    TableColumn("i_high_a", "I high (A)", "number"),
                ],
            ),
            Section(
                key="e_load_settings", title="Transient load settings", kind="group",
                fields=[
                    Field("transient_frequency_hz", "Step frequency", "number",
                          100, "Hz"),
                    Field("duty_cycle_pct", "Duty cycle", "number", 50, "%"),
                    Field("slew_rate_a_per_us", "Slew rate", "number", 1.0, "A/us"),
                    Field("load_check_pct", "Load check (min of expected avg)",
                          "number", LOAD_CHECK_PCT, "%"),
                ],
            ),
            Section(
                key="scope_settings", title="Scope settings", kind="group",
                fields=[
                    Field("vout_channel", "Vout channel", "int", 1, ""),
                    Field("measure_cycles_wait_s", "Settle before read", "number",
                          3, "s"),
                ],
            ),
            Section(
                key="limits", title="Pass/fail limits", kind="group",
                help="Default is +/- tolerance of nominal. Per-profile absolute "
                     "overrides can be added in the config file.",
                fields=[
                    Field("tolerance_pct", "Tolerance", "number", 5.0, "%"),
                ],
            ),
        ]

    # ---- execution ------------------------------------------------------ #
    def plan(self, config: dict) -> list:
        """PD profile (outer) x AC condition (inner). `new_profile` marks the
        first AC condition of each profile, so the POWER-Z step (a manual pause
        in manual mode) happens at most once per output voltage."""
        points = []
        for profile in config["pd_profiles"]:
            for j, ac in enumerate(config["ac_conditions"]):
                points.append({
                    "label": f"{profile['label']} output | {ac['label']}",
                    "pd_profile": profile["label"],
                    "pd_voltage": float(profile["voltage"]),
                    "i_low_a": float(profile["i_low_a"]),
                    "i_high_a": float(profile["i_high_a"]),
                    "ac_condition": ac["label"],
                    "ac_voltage": float(ac["voltage"]),
                    "ac_frequency": float(ac["frequency"]),
                    "new_profile": (j == 0),
                })
        return points

    def prepare(self, instruments, config, ctx):
        instruments["scope"].setup_measurements(config["scope_settings"]["vout_channel"])

    def execute_point(self, point, instruments, config, ctx) -> dict:
        try:
            return self._measure(point, instruments, config, ctx)
        except BaseException:
            quiet_off(ctx, ("turn the e-load off", instruments["e_load"].stop))
            raise

    def _measure(self, point, instruments, config, ctx) -> dict:
        els = config["e_load_settings"]
        ch = config["scope_settings"]["vout_channel"]
        wait_s = config["scope_settings"]["measure_cycles_wait_s"]
        dut = config.get("dut_name", "DUT")

        # Request the PD voltage once per profile (outer loop).
        if point["new_profile"]:
            instruments["powerz"].request_profile(point["pd_profile"], point["pd_voltage"])

        instruments["ac_source"].apply(point["ac_voltage"], point["ac_frequency"])
        instruments["e_load"].start_transient(
            point["i_low_a"], point["i_high_a"],
            els["transient_frequency_hz"], els["duty_cycle_pct"],
            els["slew_rate_a_per_us"],
        )
        if not ctx.simulate:
            ctx.sleep(wait_s)  # let the transient response stabilize on screen

        # Load check (rule 6): did the load really step up to i_high? The load
        # reports its AVERAGE current, so compare with the expected average.
        duty = float(els["duty_cycle_pct"]) / 100.0
        expected = point["i_low_a"] * (1 - duty) + point["i_high_a"] * duty
        load_avg = check_load_current(
            instruments["e_load"].measure_current(), expected,
            float(els.get("load_check_pct", LOAD_CHECK_PCT)),
            f"{point['i_low_a']:g}<->{point['i_high_a']:g} A transient")

        vmax, vmin = instruments["scope"].read_vmax_vmin(ch)

        tag = f"{dut}_{point['pd_profile']}_{point['ac_condition'].replace('/', '_')}"
        shot_rel = os.path.join("screenshots", f"{tag}.png")
        instruments["scope"].save_screenshot(os.path.join(ctx.run_dir, shot_rel))
        instruments["e_load"].stop()

        vmin_l, vmax_l = self._limits(config, point)
        # Sanity abort: a wildly out-of-range reading means a probe/setup problem,
        # so the whole run stops and the bench is shut down (rule 7).
        # (A NaN reading is not "insane" here - judge_window makes it ERROR NO_READING.)
        if (is_number(vmax) and vmax > point["pd_voltage"] * 2) or                 (is_number(vmin) and vmin < -1):
            raise StopRunError(
                "SANITY_ABORT",
                f"reading out of sane range (Vmax {vmax:.3f} V, Vmin {vmin:.3f} V for a "
                f"{point['pd_voltage']:g} V output) - check probe/channel; run stopped "
                f"for safety",
                vmax_v=rounded(vmax, 4), vmin_v=rounded(vmin, 4), screenshot=shot_rel)
        j = judge_window(vmin, vmax, vmin_l, vmax_l)
        ctx.status(f"    {j.reason} -> {j.result}")

        return self.make_row(point, config, j.result, j.code, j.reason,
                             vmax_v=rounded(vmax, 4), vmin_v=rounded(vmin, 4),
                             load_avg_a=rounded(load_avg, 3), screenshot=shot_rel)

    # ---- helpers -------------------------------------------------------- #
    def identity(self, point, config):
        vmin_l, vmax_l = self._limits(config, point)
        return {
            "pd_profile": point["pd_profile"],
            "ac_condition": point["ac_condition"],
            "vin_set_v": point["ac_voltage"],
            "freq_hz": point["ac_frequency"],
            "i_low_a": point["i_low_a"],
            "i_high_a": point["i_high_a"],
            "vmin_limit_v": round(vmin_l, 4),
            "vmax_limit_v": round(vmax_l, 4),
        }

    @staticmethod
    def _limits(config, point):
        lim = config["limits"]
        override = (lim.get("overrides") or {}).get(point["pd_profile"]) or {}
        nominal = point["pd_voltage"]
        tol = lim["tolerance_pct"] / 100.0
        vmin_l = override.get("vmin_abs", nominal * (1 - tol))
        vmax_l = override.get("vmax_abs", nominal * (1 + tol))
        return vmin_l, vmax_l
