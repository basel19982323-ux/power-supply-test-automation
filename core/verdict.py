"""Results of a test point, the fixed error codes, and the overall result.

A broken measurement is not a broken product, so there are four results:

  PASS     every check passed and the reading is inside the limit
  FAIL     a trustworthy reading is outside the limit   -> the PRODUCT failed
  ERROR    the measurement can't be trusted           -> the BENCH or SETUP failed
  NOT RUN  the point was never measured (the run stopped earlier, or Stop was pressed)

ERROR is never counted as PASS. Every ERROR and NOT RUN row carries one of the
short fixed codes below plus a human-readable reason.
"""
import math
from dataclasses import dataclass

PASS = "PASS"
FAIL = "FAIL"
ERROR = "ERROR"
NOT_RUN = "NOT RUN"
RESULTS = (PASS, FAIL, ERROR, NOT_RUN)

# Fixed short codes for ERROR, with what each one means.
ERROR_CODES = {
    "TIMEOUT": "an instrument did not answer in time",
    "BAD_REPLY": "an instrument answered with something that is not a number",
    "WRONG_UNIT": "a reading came back in the wrong unit",
    "NO_READING": "the instrument returned no valid value (NaN / no data)",
    "NO_TRIGGER": "the scope never triggered, so there is no capture",
    "STALE_CAPTURE": "the scope did not re-arm, so the waveform on screen is old",
    "CLIPPED": "the capture was clipped below the limit, so the true peak is unknown",
    "PROBE_CHECK": "the steady-state reading is impossible (probe disconnected?)",
    "LOAD_NOT_REACHED": "the electronic load did not reach its set current",
    "SANITY_ABORT": "a reading was far out of range; the run was stopped for safety",
    "DISCONNECTED": "the connection to an instrument was lost or could not be opened",
    "BAD_CONFIG": "the test settings are invalid",
    "INSTRUMENT_ERROR": "an unexpected instrument or software error",
}

# Fixed short codes for NOT RUN.
NOT_RUN_CODES = {
    "STOPPED": "the operator pressed Stop",
    "RUN_ENDED_EARLY": "the run stopped earlier because of an ERROR",
    "STEP_NOT_LOADED": "the Sequence step's settings could not be loaded",
}

_COUNT_KEY = {PASS: "pass", FAIL: "fail", ERROR: "error", NOT_RUN: "not_run"}

# One colour per result, used by the GUI and the Excel reports (hex RGB):
# PASS green, FAIL red, ERROR amber, NOT RUN grey.
RESULT_COLORS = {PASS: "C6EFCE", FAIL: "FFC7CE", ERROR: "FFEB9C", NOT_RUN: "D9D9D9"}


def result_color(result):
    """Colour for a result; anything unknown is shown like ERROR."""
    return RESULT_COLORS.get(result, RESULT_COLORS[ERROR])


def counts_text(summary):
    """'14 PASS / 1 FAIL / 1 ERROR / 0 NOT RUN of 16' (all four, always)."""
    return (f"{summary.get('pass', 0)} PASS / {summary.get('fail', 0)} FAIL / "
            f"{summary.get('error', 0)} ERROR / {summary.get('not_run', 0)} NOT RUN "
            f"of {summary.get('total', 0)}")


# --------------------------------------------------------------------------- #
# Errors with a fixed code
# --------------------------------------------------------------------------- #
class CodedError(Exception):
    """An error that already knows its fixed code and its reason. `values` are
    measured numbers worth keeping in the ERROR row (for example the insane
    reading that caused a sanity abort)."""

    def __init__(self, code, reason, **values):
        super().__init__(f"{code}: {reason}")
        self.code = code
        self.reason = reason
        self.values = values


class PointError(CodedError):
    """This point's measurement can't be trusted, but the bench is in a known,
    safe state: record ERROR for this point and continue with the next one."""


class StopRunError(CodedError):
    """The bench itself can't be trusted (sanity abort, lost instrument, ...):
    record ERROR for this point, NOT RUN for the rest, and shut the bench down."""


# Text that pyvisa puts in its error messages for a lost or missing connection.
_CONNECTION_MARKERS = ("VI_ERROR_CONN_LOST", "VI_ERROR_RSRC_NFOUND", "VI_ERROR_IO",
                       "VI_ERROR_RSRC_BUSY", "VI_ERROR_INV_OBJECT", "VI_ERROR_CLOSING_FAILED")


def classify_exception(exc):
    """Map any exception to (code, reason). Used for errors that the test code
    did not expect, for example a pyvisa timeout or a dropped connection."""
    if isinstance(exc, CodedError):
        return exc.code, exc.reason
    text = str(exc) or type(exc).__name__
    short = text if len(text) <= 160 else text[:157] + "..."
    if (isinstance(exc, TimeoutError) or "VI_ERROR_TMO" in text
            or "timed out" in text.lower()):
        return "TIMEOUT", f"an instrument did not answer in time ({short})"
    if isinstance(exc, ConnectionError) or any(m in text for m in _CONNECTION_MARKERS):
        return "DISCONNECTED", f"the connection to an instrument was lost ({short})"
    return "INSTRUMENT_ERROR", f"{type(exc).__name__}: {short}"


def summarize(rows):
    """Count the results. Anything that is not a known result counts as ERROR,
    so it can never be counted as PASS by accident."""
    counts = {"total": len(rows), "pass": 0, "fail": 0, "error": 0, "not_run": 0}
    for row in rows:
        counts[_COUNT_KEY.get(row.get("result"), "error")] += 1
    return counts


def combine(results):
    """Overall result of several results (the points of a test, or the tests of
    a Sequence):

      any FAIL                      -> FAIL
      otherwise any ERROR           -> ERROR   (an unknown result counts as ERROR)
      otherwise any NOT RUN, or none -> NOT RUN
      PASS only if every result is PASS.
    """
    results = list(results)
    if FAIL in results:
        return FAIL
    if any(r not in (PASS, NOT_RUN) for r in results):
        return ERROR
    if not results or NOT_RUN in results:
        return NOT_RUN
    return PASS


# --------------------------------------------------------------------------- #
# Judging a reading (rules 1 and 2)
# --------------------------------------------------------------------------- #
def is_number(value):
    """True only for a real, finite number (not NaN, not infinity, not None)."""
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


@dataclass
class Judgement:
    result: str      # PASS / FAIL / ERROR
    code: str        # error code, "" for PASS / FAIL
    reason: str      # human-readable explanation
    shown: object    # what to show in the table, e.g. 568.0 or "≥ 946.8"


def judge_upper(value, limit, *, what="VDS max", unit="V", clipped=False,
                screen_top=None, digits=1):
    """Judge a reading against an upper limit.

    PASS only if the reading is a real number, not clipped, and <= limit.
    NaN / None / infinity -> ERROR NO_READING (never PASS: note that in Python
    `nan > limit` is False, so a naive "FAIL if value > limit else PASS" would
    give PASS for a broken reading).

    Clipped capture: X = top-of-screen voltage read back from the scope.
      X above the limit -> FAIL, shown as "≥ X" (the true peak is even higher)
      otherwise         -> ERROR CLIPPED (the true peak is unknown)
    """
    if not is_number(limit) or limit <= 0:
        return Judgement(ERROR, "BAD_CONFIG",
                         f"the limit ({limit!r}) is not a positive number", "")
    if clipped:
        x = screen_top
        if not is_number(x):
            return Judgement(ERROR, "CLIPPED", f"{what}: the capture was clipped and "
                             f"the scope's full-scale could not be read back", "")
        shown = f"≥ {x:.{digits}f}"
        if x > limit:
            return Judgement(FAIL, "", f"{what} {shown} {unit} (clipped at full-scale) is "
                             f"already above the {limit:.{digits}f} {unit} limit", shown)
        return Judgement(ERROR, "CLIPPED", f"{what} clipped at {x:.{digits}f} {unit}, below "
                         f"the {limit:.{digits}f} {unit} limit: the true peak is unknown",
                         shown)
    if not is_number(value):
        return Judgement(ERROR, "NO_READING",
                         f"{what}: the scope gave no valid value ({value!r})", "")
    shown = round(float(value), digits)
    if value <= limit:
        return Judgement(PASS, "", f"{what} {value:.{digits}f} {unit} <= limit "
                         f"{limit:.{digits}f} {unit}", shown)
    return Judgement(FAIL, "", f"{what} {value:.{digits}f} {unit} > limit "
                     f"{limit:.{digits}f} {unit}", shown)


def judge_window(vmin, vmax, low, high, *, unit="V", digits=3):
    """Judge Vmin/Vmax against a [low, high] window (Dynamic Output Response)."""
    for name, v in (("Vmin", vmin), ("Vmax", vmax)):
        if not is_number(v):
            return Judgement(ERROR, "NO_READING", f"{name}: the scope gave no valid "
                             f"value ({v!r}) - nothing captured?", "")
    if not (is_number(low) and is_number(high)) or low >= high:
        return Judgement(ERROR, "BAD_CONFIG", f"invalid limit window [{low!r}, {high!r}]", "")
    if vmin > vmax:
        return Judgement(ERROR, "NO_READING", f"Vmin {vmin:.{digits}f} {unit} is above "
                         f"Vmax {vmax:.{digits}f} {unit}: not a valid measurement", "")
    window = f"[{low:.{digits}f}, {high:.{digits}f}] {unit}"
    if low <= vmin and vmax <= high:
        return Judgement(PASS, "", f"Vmin {vmin:.{digits}f} and Vmax {vmax:.{digits}f} "
                         f"{unit} inside {window}", "")
    out = []
    if vmin < low:
        out.append(f"Vmin {vmin:.{digits}f} {unit} below {low:.{digits}f} {unit}")
    if vmax > high:
        out.append(f"Vmax {vmax:.{digits}f} {unit} above {high:.{digits}f} {unit}")
    return Judgement(FAIL, "", "; ".join(out), "")


def rounded(value, digits):
    """Round a reading for the table; a non-number is shown as an empty cell."""
    return round(float(value), digits) if is_number(value) else ""


def overall(rows, run_error=None):
    """Overall result of one run. A run-level error (for example the test plan
    could not be built) makes the run ERROR unless something already FAILed."""
    result = combine(row.get("result") for row in rows)
    if run_error and result != FAIL:
        return ERROR
    return result
