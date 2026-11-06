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

SENT is not CONFIRMED. "The OFF command was sent without an error" only means
the bytes left the PC. Only the instrument's own answer to a read-back query
("OUTPut?" / "INPut?" -> off) confirms it. Both are recorded separately for
each instrument, and only a confirmed OFF counts as safe.
"""

AC_WARNING = ("WARNING: the AC source output could NOT be confirmed OFF. The DUT "
              "may still be live - switch the AC source off by hand before touching it.")
LOAD_WARNING = ("WARNING: the e-load input could NOT be confirmed OFF - switch it off "
                "by hand.")


# Final state of each powered instrument, as recorded in `record`.
CONFIRMED_OFF = "OFF confirmed by the instrument"
SENT_STILL_ON = "OFF sent, but the instrument says it is still ON"
SENT_NOT_CONFIRMED = "OFF sent, but NOT confirmed (no valid answer to the read-back)"
NOT_SENT_NOT_CONFIRMED = "OFF could NOT be sent, and NOT confirmed"
CANNOT_ASK = "OFF sent, but NOT confirmed (this instrument can't be asked)"


def shutdown_bench(instruments, status=print, record=None):
    """Turn the e-load and the AC source off, confirm, and close everything.
    Returns a list of warning strings (empty when everything is confirmed off).
    If `record` (a dict) is given, it is filled per role with
    {"off_sent": bool, "confirmed_off": True / False / None, "state": text}:
    confirmed_off is True only if the instrument answered "off", False if it
    answered "on", None if it could not be asked or gave no valid answer.
    Never raises."""
    warnings = []
    record = {} if record is None else record

    def attempt(what, fn):
        try:
            fn()
            return True
        except Exception as e:  # noqa: BLE001 - keep going, report it
            status(f"    could not {what}: {type(e).__name__}: {e}")
            return False

    load = instruments.get("e_load")
    ac = instruments.get("ac_source")

    sent = {}
    if load is not None:
        sent["e_load"] = attempt("turn the e-load off", load.stop)
    if ac is not None:
        sent["ac_source"] = attempt("turn the AC source off", ac.off)

    # Confirm by asking the instrument (not by trusting that the command worked).
    for role, dev, method, warning in (("ac_source", ac, "output_is_on", AC_WARNING),
                                       ("e_load", load, "input_is_on", LOAD_WARNING)):
        if dev is None:
            continue
        confirmed = _confirmed_off(dev, method, attempt)
        record[role] = {"off_sent": sent[role], "confirmed_off": confirmed,
                        "state": _state_text(sent[role], confirmed, dev, method)}
        status(f"    {role}: {record[role]['state']}")
        if confirmed is not True:
            warnings.append(warning)

    for role, dev in instruments.items():
        attempt(f"close the {role} connection", dev.close)

    for w in warnings:
        status(w)
    return warnings


def _confirmed_off(dev, method, attempt):
    """True if the instrument answers that it is off, False if it answers that
    it is on, None if it can't be asked or gives no valid answer."""
    query = getattr(dev, method, None)
    if query is None:
        return None                    # can't be asked -> NOT confirmed
    answer = []
    if not attempt(f"read back the {dev.role} state", lambda: answer.append(query())):
        return None
    return {False: True, True: False}.get(answer[0])


def _state_text(sent, confirmed, dev, method):
    if confirmed is True:
        return CONFIRMED_OFF
    if confirmed is False:
        return SENT_STILL_ON if sent else NOT_SENT_NOT_CONFIRMED
    if not sent:
        return NOT_SENT_NOT_CONFIRMED
    return CANNOT_ASK if getattr(dev, method, None) is None else SENT_NOT_CONFIRMED
