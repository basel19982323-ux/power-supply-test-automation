"""The fake SCPI bench itself: the REAL drivers pass all three tests on a
healthy fake bench, every command and reply is logged, unknown fault names
are rejected, and the servers stop cleanly."""
import socket

import pytest

from core.verdict import PASS
from tools import fake_bench as fb


@pytest.mark.parametrize("test_id", ["dynamic_output_response", "vds_turnoff", "vds_ovp"])
def test_real_drivers_pass_on_a_healthy_fake_bench(run_on_fake_bench, test_id):
    res, bench, _ = run_on_fake_bench(test_id)
    assert res.rows and all(r["result"] == PASS for r in res.rows), res.rows
    assert res.error is None and res.warnings == []


def test_the_log_has_every_command_and_reply(run_on_fake_bench):
    res, bench, _ = run_on_fake_bench("vds_turnoff")
    ac = [(cmd.upper(), reply) for role, cmd, reply in bench.log if role == "ac_source"]
    assert ("*IDN?", "SIM,ITECH-IT7300,FAKE-BENCH,1.0") in ac
    assert ("OUTPUT OFF", None) in ac                  # a write: no reply
    assert ("OUTPUT?", "0") in ac                      # a query: its reply is logged
    assert bench.sent("ac_source") == [c for c, _ in ac]


def test_unknown_fault_name_is_an_error():
    with pytest.raises(ValueError, match="unknown fake-bench fault"):
        fb.Bench(faults={"no_such_fault": True})


def test_stopped_servers_free_their_ports():
    servers = fb.start_servers(fb.Bench())
    port = servers["scope"].port
    socket.create_connection(("127.0.0.1", port), timeout=2).close()   # it listens
    for s in servers.values():
        s.stop()
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=0.5)
