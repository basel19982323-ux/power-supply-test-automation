"""VISA plumbing: backend selection, resource opening, discovery, identify.

The backend is selectable via the DLT_VISA_BACKEND environment variable
(default "@py" — the pure-Python pyvisa-py backend). Set it to "@sim" to use
pyvisa-sim, or "@ivi"/"" for NI-VISA. Raw-socket resources
(TCPIP::host::port::SOCKET) get "\n" termination so they work against a plain
SCPI socket server such as tools/fake_bench.py.

Kept import-light: pyvisa is only imported inside functions so the app (and the
whole simulation path) runs even when no VISA backend is installed.
"""
import os


def resource_manager():
    try:
        import pyvisa
    except ImportError as e:  # pragma: no cover - environment dependent
        raise ImportError(
            "pyvisa is not installed. Install with: pip install pyvisa pyvisa-py"
        ) from e
    backend = os.environ.get("DLT_VISA_BACKEND", "@py")
    return pyvisa.ResourceManager(backend)


def open_resource(rm, address, timeout_ms=5000):
    """Open a resource and apply raw-socket termination when needed."""
    inst = rm.open_resource(address)
    inst.timeout = timeout_ms
    if "SOCKET" in str(address).upper():
        inst.read_termination = "\n"
        inst.write_termination = "\n"
    return inst


def scan(timeout_ms=2000):
    """Return a list of {'address': str, 'idn': str} for connected VISA resources.

    Note: raw socket servers (e.g. tools/fake_bench.py) are not discoverable —
    enter their TCPIP::host::port::SOCKET address by hand and use 'Test'.
    """
    rm = resource_manager()
    found = []
    for addr in rm.list_resources():
        try:
            inst = open_resource(rm, addr, timeout_ms)
            idn = inst.query("*IDN?").strip()
            inst.close()
        except Exception as e:
            idn = f"(no IDN response: {e})"
        found.append({"address": addr, "idn": idn})
    return found


def identify(address, timeout_ms=3000):
    """Open one address, query *IDN?, close. Returns the IDN string (raises on
    failure). Used by the Instruments tab's per-instrument 'Test' button."""
    rm = resource_manager()
    inst = open_resource(rm, address, timeout_ms)
    try:
        return inst.query("*IDN?").strip()
    finally:
        inst.close()
