"""Build the set of instruments a test type needs — real or simulated.

`build_instruments(roles, config, simulate, prompt_fn)` returns a dict keyed by
role (e.g. "ac_source", "scope") so a test type can look them up by name. Real
mode opens VISA resources from `config["instruments"]`; simulation mode returns
fakes sharing one SimBench. Either way the returned objects share one interface.
"""


def build_instruments(roles, config, simulate, prompt_fn=None):
    if simulate:
        return _build_sim(roles, config)
    return _build_real(roles, config, prompt_fn)


def _build_sim(roles, config):
    from .simulator import SimBench, SimACSource, SimLoad, SimScope, SimPowerZ

    sim = config.get("simulation") or {}
    bench = SimBench(
        fault_profiles=sim.get("fault_profiles"),
        vds_reflected=sim.get("vds_reflected", 100.0),
        vds_spike_factor=sim.get("vds_spike_factor", 1.2),
        steady_out=sim.get("steady_out", 20.0),
        ovp_vout=sim.get("ovp_vout", 28.0),
        ovp_vds_factor=sim.get("ovp_vds_factor", 1.3),
    )
    factories = {
        "ac_source": lambda: SimACSource(bench),
        "e_load": lambda: SimLoad(bench),
        "scope": lambda: SimScope(bench),
        "powerz": lambda: SimPowerZ(bench),
    }
    return {role: factories[role]() for role in roles}


def _build_real(roles, config, prompt_fn):
    from ..visa import open_resource, resource_manager
    from .itech_ac import ITechACSource
    from .itech_load import ITechLoad
    from .yokogawa_scope import YokogawaScope
    from .powerz import PowerZ

    addrs = config.get("instruments", {})
    rm = resource_manager()
    built = {}
    try:
        if "ac_source" in roles:
            built["ac_source"] = ITechACSource(open_resource(rm, addrs["ac_source"]))
        if "e_load" in roles:
            built["e_load"] = ITechLoad(open_resource(rm, addrs["e_load"]))
        if "scope" in roles:
            built["scope"] = YokogawaScope(open_resource(rm, addrs["scope"], timeout_ms=15000))
        if "powerz" in roles:
            mode = (config.get("powerz") or {}).get("mode", "manual")
            built["powerz"] = PowerZ(mode, prompt_fn=prompt_fn)
    except Exception:
        # Roll back any partial opens so we never leave instruments dangling.
        for dev in built.values():
            try:
                dev.close()
            except Exception:
                pass
        raise
    return built
