"""Datasheet VDS-rating extraction (text ranking, no PDF needed)."""
from core.datasheet import rank_candidates


def test_rank_finds_vdss():
    text = "Absolute Maximum Ratings  Drain-Source Voltage VDSS 650 V"
    c = rank_candidates(text)
    assert c and c[0]["value"] == 650.0


def test_rank_brdss_breakdown():
    text = "V(BR)DSS Drain-to-Source Breakdown Voltage 600 V"
    c = rank_candidates(text)
    assert c[0]["value"] == 600.0


def test_rank_low_voltage_part():
    text = "VDS 30 V continuous drain current ID 100 A"
    c = rank_candidates(text)
    assert c[0]["value"] == 30.0


def test_rank_none():
    assert rank_candidates("nothing relevant in this text") == []
