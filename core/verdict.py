"""Results of a test point, the fixed error codes, and the overall result.

A broken measurement is not a broken product, so there are four results:

  PASS     every check passed and the reading is inside the limit
  FAIL     a trustworthy reading is outside the limit   -> the PRODUCT failed
  ERROR    the measurement can't be trusted           -> the BENCH or SETUP failed
  NOT RUN  the point was never measured (the run stopped earlier, or Stop was pressed)

ERROR is never counted as PASS. Every ERROR and NOT RUN row carries one of the
short fixed codes below plus a human-readable reason.
"""

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


def overall(rows, run_error=None):
    """Overall result of one run. A run-level error (for example the test plan
    could not be built) makes the run ERROR unless something already FAILed."""
    result = combine(row.get("result") for row in rows)
    if run_error and result != FAIL:
        return ERROR
    return result
