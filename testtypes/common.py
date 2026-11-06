"""Helpers shared by the V_DS tests (AC turn-off and OVP)."""
import math

from core.verdict import PointError, is_number

PROBE_CHECK_MIN_X = 0.5     # steady VDS must be at least 0.5 x the AC peak ...
PROBE_CHECK_MAX_X = 3.0     # ... and at most 3 x the AC peak


def vds_limit(config):
    """Return (FET rating, derating %, limit) from the 'limits' section.
    limit = rating x derating / 100."""
    lim = config["limits"]
    rating = float(lim.get("fet_vds_rating_v", 0) or 0)
    derating = float(lim.get("derating_pct", 100) or 100)
    return rating, derating, rating * derating / 100.0


def clip_check(reading, screen_top):
    """True if the capture touches the top of the screen (the real peak may be
    higher than what the scope could show). `screen_top` must be the value READ
    BACK from the scope. If the top can't be read, we can't prove the capture
    is not clipped, so we say it is clipped (the safe side)."""
    if not is_number(screen_top):
        return True
    if not is_number(reading):
        return False            # no reading at all: judged as NO_READING instead
    return reading >= screen_top - max(0.02 * screen_top, 1.0)


def quiet_off(ctx, *actions):
    """Run each (name, function) "turn off" action on the error path. Every
    action is tried even if an earlier one fails, and a failure never hides
    the original error - it is only reported in the status log."""
    for name, fn in actions:
        try:
            fn()
        except Exception as e:
            ctx.status(f"    WARNING: could not {name}: {e}")


def check_steady_vds(value, ac_voltage, scope_cfg):
    """Probe check (rule 4), done BEFORE the AC is cut or the event starts.

    While the flyback runs, the MOSFET drain sees at least the bulk capacitor
    voltage (about sqrt(2) x Vac) plus the reflected voltage. So the steady VDS
    peak must be clearly above 0 and not wildly above the AC peak. About 0 V
    means the probe is not connected (or the wrong channel); a huge value means
    the probe attenuation is set wrong. Either way the capture can't be trusted.
    """
    if not is_number(value):
        raise PointError("NO_READING", f"steady-state VDS: the scope gave no valid "
                         f"value ({value!r}); the bench was turned off")
    ac_peak = math.sqrt(2) * float(ac_voltage)
    lo = float(scope_cfg.get("probe_check_min_x", PROBE_CHECK_MIN_X)) * ac_peak
    hi = float(scope_cfg.get("probe_check_max_x", PROBE_CHECK_MAX_X)) * ac_peak
    if not lo <= value <= hi:
        hint = ("probe disconnected or wrong channel?" if value < lo
                else "probe attenuation set wrong?")
        raise PointError("PROBE_CHECK", f"steady-state VDS {value:.1f} V is outside the "
                         f"possible range {lo:.0f}..{hi:.0f} V for {ac_voltage:g} Vac "
                         f"({hint}); AC was not cut")
    return value


def check_steady_output(value, expected_v, trigger_v):
    """OVP test: before the feedback loop is broken, the output (CH2) must be
    near its normal value and BELOW the trigger level - otherwise the trigger
    would fire at once (or never) and the capture would not be the OVP event."""
    if not is_number(value):
        raise PointError("NO_READING", f"steady output: the scope gave no valid value "
                         f"({value!r})")
    if not 0.5 * expected_v <= value < trigger_v:
        raise PointError("PROBE_CHECK", f"steady output {value:.2f} V is not between "
                         f"{0.5 * expected_v:.1f} V and the {trigger_v:.1f} V trigger "
                         f"level (output probe / channel / settings?)")
    return value
