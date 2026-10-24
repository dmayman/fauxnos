#!/usr/bin/env python3
"""
Test the optional built-in sources (Noise, Library): a client lists them only
once they're in its explicit `sources` array, and adding one through the
per-source upsert seeds the full routable entry.

Run: python3 test_optional_sources.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from modules.api_server import FauxnosAPIServer


def _fresh(raw):
    # __new__ skips __init__ so no Flask app, config file or broker is needed.
    s = FauxnosAPIServer.__new__(FauxnosAPIServer)
    s._get_client_raw = lambda client_id: raw
    return s


def demo():
    # Not added: only the always-on built-ins.
    s = _fresh({"id": "fauxnos003", "sources": []})
    assert [x["id"] for x in s._effective_client_sources("fauxnos003")] == ["spotify", "airplay"]

    # Added (as the upsert stores it): listed in canonical order, before
    # analog, with structural fields backfilled from the default.
    seed = s._synthesized_default_source("noise")
    assert seed["sink"] == "noisesink" and seed["volume_controller"] == "self", seed
    s = _fresh({"id": "fauxnos003", "has_adc": True,
                "sources": [{**seed, "label": "Noise"}, {"id": "library", "label": "Library"}]})
    got = s._effective_client_sources("fauxnos003")
    assert [x["id"] for x in got] == ["spotify", "airplay", "noise", "library", "analog"], got
    assert got[3]["sink"] == "librarysink", got[3]
    print("ok: noise/library are listed only once added, and added entries are routable")


if __name__ == "__main__":
    demo()
