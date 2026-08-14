#!/usr/bin/env python3
"""Self-check for SnapcastGroupManager.leave_group_on_source_change.

    python3 test_group_leave.py

Stubs snapcast RPC — only the leave/disband decision is under test.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from modules.group_manager import SnapcastGroupManager  # noqa: E402


class FakeGM(SnapcastGroupManager):
    """Group of fauxnos000 (host, playing its spotify) + 001 + 002."""

    def __init__(self, stream="source_fauxnos000_spotify"):
        super().__init__()
        self.group = {
            "id": "g1",
            "stream_id": stream,
            "clients": [{"id": f"fauxnos00{i}", "connected": True} for i in range(3)],
        }
        self.sent_home = []

    def find_client_group(self, client_id):
        ids = [c["id"] for c in self.group["clients"] if c["connected"]]
        return self.group if client_id in ids else None

    def return_client_to_home(self, client_id):
        self.sent_home.append(client_id)
        self.group["clients"] = [c for c in self.group["clients"] if c["id"] != client_id]
        return True


def main():
    # Member switches away → only it leaves.
    gm = FakeGM()
    assert gm.leave_group_on_source_change("fauxnos001", "analog") == []
    assert gm.sent_home == ["fauxnos001"]

    # Host switches away → everyone else goes home, host stays put.
    gm = FakeGM()
    assert sorted(gm.leave_group_on_source_change("fauxnos000", "airplay")) == \
        ["fauxnos001", "fauxnos002"]
    assert "fauxnos000" not in gm.sent_home

    # Still on the group's source → no-op (join publishes mode=spotify, and
    # the client echoes it straight back; must not self-disband).
    gm = FakeGM()
    assert gm.leave_group_on_source_change("fauxnos001", "spotify") == []
    assert gm.sent_home == []

    # Alone in a group → nothing to leave.
    gm = FakeGM()
    gm.group["clients"] = [{"id": "fauxnos000", "connected": True}]
    assert gm.leave_group_on_source_change("fauxnos000", "analog") == []
    assert gm.sent_home == []

    # Unparseable stream id → bail rather than guess a host.
    gm = FakeGM(stream="default")
    assert gm.leave_group_on_source_change("fauxnos001", "analog") == []
    assert gm.sent_home == []

    print("✅ leave_group_on_source_change: all cases pass")


if __name__ == "__main__":
    main()
