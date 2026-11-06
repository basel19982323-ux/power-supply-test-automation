"""Turning an instrument's text reply into a number — safely.

A bare float(reply) is dangerous:
  * 'garbage'      -> crashes with ValueError and no clear message
  * '1.5A'         -> crashes, but '1.5' from the wrong channel would be accepted
  * '9.91E+37'     -> SCPI's code for "no value" becomes a huge, real-looking number

parse_number() accepts the normal forms ('5.02', '5.02E+00', '5.02 V', and the
header form ':MEAS:CHAN1:MAX:VAL 5.02E+00') and turns everything else into an
error with a fixed code, so a broken reply can never become a PASS.
"""
import math
import re

from ..verdict import StopRunError

_REPLY = re.compile(
    r"^\s*(?:(?P<header>\S*:\S*)\s+)?"                       # optional SCPI header
    r"(?P<num>[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"     # 5, 5.02, .5, 5.02E+00
    r"|[-+]?(?:NAN|INF|INFINITY))"                          # or NaN / infinity
    r"\s*(?P<unit>[A-Za-z%]*)\s*$",                          # optional unit, e.g. V
    re.IGNORECASE,
)
_SCPI_NO_VALUE = 9.9e37   # SCPI uses 9.91E37 for NaN and 9.9E37 for infinity


def parse_on_off(reply, what="state"):
    """'1' / 'ON' -> True, '0' / 'OFF' -> False; anything else is BAD_REPLY."""
    text = "" if reply is None else str(reply).strip().upper()
    if text in ("1", "ON"):
        return True
    if text in ("0", "OFF"):
        return False
    raise StopRunError("BAD_REPLY", f"{what}: the instrument answered {text!r}, "
                                    f"expected ON/OFF")


def parse_number(reply, unit=None, what="reading"):
    """Return the reply as a float. NaN means "the instrument has no value".

    Raises StopRunError("BAD_REPLY") if the reply is not a number, and
    StopRunError("WRONG_UNIT") if it carries a unit other than `unit`. These
    stop the run: if the conversation with an instrument is broken, nothing it
    says afterwards can be trusted either.
    """
    text = "" if reply is None else str(reply).strip()
    m = _REPLY.match(text)
    if not m:
        raise StopRunError("BAD_REPLY", f"{what}: the instrument answered {text!r}, "
                                        f"which is not a number")
    got_unit = m.group("unit")
    if got_unit and unit is not None and got_unit.upper() != unit.upper():
        raise StopRunError("WRONG_UNIT", f"{what}: expected a value in {unit}, the "
                                         f"instrument answered {text!r}")
    value = float(m.group("num"))
    if math.isfinite(value) and abs(value) >= _SCPI_NO_VALUE:
        return float("nan")
    return value
