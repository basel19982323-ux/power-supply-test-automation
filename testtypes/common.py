"""Helpers shared by the V_DS tests (AC turn-off and OVP)."""
from core.verdict import is_number


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
