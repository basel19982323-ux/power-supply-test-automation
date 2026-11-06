"""Leave the bench in a safe state at the end of every run (rule 8).

Order matters for a power supply under test:
  1. e-load OFF first  - stop pulling current from the DUT output;
  2. AC source OFF     - remove the mains input (the dangerous part);
  3. confirm           - ask each instrument whether it is really off;
  4. close             - release the VISA connections.

Every step is tried even if an earlier one fails (one broken instrument must
never stop us from switching off the other). Anything that could not be done
or confirmed becomes a WARNING that the GUI and the CLI show clearly, because
a "run finished" message while the AC is still on is a safety problem.
"""

AC_WARNING = ("WARNING: the AC source output could NOT be confirmed OFF. The DUT "
              "may still be live - switch the AC source off by hand before touching it.")
LOAD_WARNING = ("WARNING: the e-load input could NOT be confirmed OFF - switch it off "
                "by hand.")


def shutdown_bench(instruments, status=print):
    """Turn the e-load and the AC source off, confirm, and close everything.
    Returns a list of warning strings (empty when everything is confirmed off).
    Never raises."""
    warnings = []

    def attempt(what, fn):
        try:
            fn()
            return True
        except Exception as e:  # noqa: BLE001 - keep going, report it
            status(f"    could not {what}: {type(e).__name__}: {e}")
            return False

    load = instruments.get("e_load")
    ac = instruments.get("ac_source")

    if load is not None:
        attempt("turn the e-load off", load.stop)
    if ac is not None:
        attempt("turn the AC source off", ac.off)

    # Confirm by asking the instrument (not by trusting that the command worked).
    if ac is not None and not _confirmed_off(ac, "output_is_on", attempt):
        warnings.append(AC_WARNING)
    if load is not None and not _confirmed_off(load, "input_is_on", attempt):
        warnings.append(LOAD_WARNING)

    for role, dev in instruments.items():
        attempt(f"close the {role} connection", dev.close)

    for w in warnings:
        status(w)
    return warnings


def _confirmed_off(dev, method, attempt):
    """True only if the instrument answers that it is off."""
    query = getattr(dev, method, None)
    if query is None:
        return True                    # this instrument can't be asked
    answer = []
    if not attempt(f"read back the {dev.role} state", lambda: answer.append(query())):
        return False
    return answer[0] is False
