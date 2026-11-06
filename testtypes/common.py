"""Helpers shared by the V_DS tests (AC turn-off and OVP)."""


def vds_limit(config):
    """Return (FET rating, derating %, limit) from the 'limits' section.
    limit = rating x derating / 100."""
    lim = config["limits"]
    rating = float(lim.get("fet_vds_rating_v", 0) or 0)
    derating = float(lim.get("derating_pct", 100) or 100)
    return rating, derating, rating * derating / 100.0
