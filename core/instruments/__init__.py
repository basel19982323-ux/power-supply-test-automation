"""Instrument drivers (real, over PyVISA/SCPI) and simulated equivalents.

Every driver exposes the same small role interface so the runner and test types
are hardware-agnostic:

    ac_source : apply(voltage, frequency) -> measured ; off() ; close()
    e_load    : start_transient(i_low, i_high, freq_hz, duty_pct, slew) ; stop() ; close()
    scope     : setup_measurements(ch) ; read_vmax_vmin(ch) -> (vmax, vmin) ;
                save_screenshot(path) ; close()
    powerz    : request_profile(label, voltage) ; close()

The simulator module provides drop-in fakes with the identical interface so the
whole application runs end-to-end with no instruments connected.
"""
