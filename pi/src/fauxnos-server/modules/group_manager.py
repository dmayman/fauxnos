#!/usr/bin/env python3
"""
Snapcast Group Management
=========================
Thin wrapper around snapserver's JSON-RPC API.

Design (2026-05-24):
  • The only persistent per-client state is `home_source` (the snapcast
    stream id, e.g. `source_fauxnos001_spotify`). No `home_group` UUID is
    stored anywhere — snapcast auto-prunes empty groups, so any saved UUID
    would go stale the moment a client joined another group.
  • A snapcast group's "home client" is derived: it is the client whose
    `home_source` matches that group's current stream_id. Other connected
    clients in the same group are joined; they hear the host's stream.
  • Join / Return Home are user-driven, event-handled, and idempotent.
    No background reconciler moves clients between groups.
"""

import json
import socket
import time
from typing import Dict, List, Any, Optional


class SnapcastGroupManager:
    """JSON-RPC client for snapserver group operations."""

    def __init__(self, snapcast_host: str = "localhost", snapcast_port: int = 1705,
                 config_manager=None):
        self.snapcast_host = snapcast_host
        self.snapcast_port = snapcast_port
        self.config_manager = config_manager

    # ── Transport ─────────────────────────────────────────────────────────

    def send_snapcast_command(self, method: str, params: Optional[Dict[str, Any]] = None
                              ) -> Optional[Dict[str, Any]]:
        """Send a JSON-RPC request over snapserver's TCP control port.

        snapserver frames each message with a trailing "\n". A single
        recv(4096) used to truncate Server.GetStatus once a couple of
        clients were registered, so we read until we see a newline.
        """
        request = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((self.snapcast_host, self.snapcast_port))
            sock.send((json.dumps(request) + "\n").encode())

            chunks: list[bytes] = []
            while True:
                chunk = sock.recv(8192)
                if not chunk:
                    break
                chunks.append(chunk)
                if b"\n" in chunk:
                    break
            sock.close()

            response_data = b"".join(chunks).decode()
            if not response_data:
                return None
            return json.loads(response_data.split("\n", 1)[0])
        except Exception as e:
            print(f"❌ Failed to send snapcast command {method}: {e}")
            return None

    # ── Read helpers ──────────────────────────────────────────────────────

    def get_server_status(self) -> Optional[Dict[str, Any]]:
        return self.send_snapcast_command("Server.GetStatus")

    def get_groups(self) -> List[Dict[str, Any]]:
        status = self.get_server_status()
        if status and "result" in status and "server" in status["result"]:
            return status["result"]["server"].get("groups", [])
        return []

    def find_client_group(self, client_id: str) -> Optional[Dict[str, Any]]:
        """Find which snapcast group contains a CONNECTED client (strict id match).

        We deliberately don't fall back to host.name: a stale snapclient
        registration under the device's wlan0 MAC (legacy install path)
        keeps its `host.name="fauxnosNNN"` while its `id` stays the MAC
        string. The hostname-fallback would match that disconnected stale
        group first — and `return_client_to_home` would then "fix" the
        wrong group's stream, leaving the real client stuck on whatever
        stream snapcast auto-assigned to its new group.

        Disconnected clients are also skipped — operations targeting a
        sole-member-disconnected group are never what the caller wants.
        """
        for group in self.get_groups():
            for client in group.get("clients", []):
                if client.get("id") == client_id and client.get("connected"):
                    return group
        return None

    def _client_home_source(self, client_id: str) -> Optional[str]:
        """Look up home_source from server_config for a client."""
        if not self.config_manager:
            return None
        for c in self.config_manager.server_config.get("clients", []):
            if c.get("id") == client_id:
                return c.get("home_source")
        return None

    # ── Write helpers ─────────────────────────────────────────────────────

    def set_group_source(self, group_id: str, source_id: str) -> bool:
        """Set Group.SetStream after verifying the stream exists."""
        status = self.get_server_status()
        if status and "result" in status and "server" in status["result"]:
            streams = status["result"]["server"].get("streams", [])
            available = [s.get("id") for s in streams]
            if source_id not in available:
                print(f"      ⚠️  Source '{source_id}' not in {available}")
                return False

        result = self.send_snapcast_command("Group.SetStream",
                                            {"id": group_id, "stream_id": source_id})
        if result is None or "error" in result or "result" not in result:
            err = (result or {}).get("error", {}).get("message", "no response")
            print(f"      ❌ Group.SetStream failed: {err}")
            return False
        return True

    # ── User-driven operations ────────────────────────────────────────────

    def join_client_to_group(self, client_id: str, target_client_id: str) -> bool:
        """Join `client_id` into `target_client_id`'s current snapcast group.

        Also calls Group.SetStream to force the group's stream to the target's
        `home_source` — defensive against a group whose stream got out of sync
        with its host. The joining client's empty original group will be
        auto-pruned by snapcast.
        """
        target_group = self.find_client_group(target_client_id)
        if not target_group:
            print(f"❌ Target {target_client_id} not in any snapcast group")
            return False

        target_group_id = target_group.get("id")
        existing = [c.get("id") for c in target_group.get("clients", [])]
        if client_id not in existing:
            existing.append(client_id)
        else:
            print(f"ℹ️  {client_id} already in {target_client_id}'s group")
            return True

        result = self.send_snapcast_command("Group.SetClients",
                                            {"id": target_group_id, "clients": existing})
        if not result or "result" not in result:
            print(f"❌ Group.SetClients failed for {client_id} → {target_group_id}")
            return False

        target_home_source = self._client_home_source(target_client_id)
        if target_home_source and target_group.get("stream_id") != target_home_source:
            self.set_group_source(target_group_id, target_home_source)

        print(f"✅ Joined {client_id} → {target_client_id}'s group ({target_group_id[:8]})")
        return True

    def return_client_to_home(self, client_id: str) -> bool:
        """Send a client back to its own group playing its `home_source`.

        Mechanism: Group.SetClients on the current group with everyone except
        this client → snapcast auto-creates a fresh group for the evicted
        client → Group.SetStream that new group to client.home_source.

        If the client is already alone in a group, just retune the stream if
        needed (no eviction).
        """
        home_source = self._client_home_source(client_id)
        if not home_source:
            print(f"❌ {client_id}: no home_source in server_config")
            return False

        current_group = self.find_client_group(client_id)
        if not current_group:
            print(f"❌ {client_id} not currently in any snapcast group")
            return False

        current_group_id = current_group.get("id")
        all_client_ids = [c.get("id") for c in current_group.get("clients", []) if c.get("id")]

        # Already alone? Just fix the stream if needed.
        if all_client_ids == [client_id]:
            if current_group.get("stream_id") != home_source:
                return self.set_group_source(current_group_id, home_source)
            return True

        other_clients = [cid for cid in all_client_ids if cid != client_id]
        result = self.send_snapcast_command("Group.SetClients",
                                            {"id": current_group_id, "clients": other_clients})
        if not result or "result" not in result:
            print(f"❌ Eviction failed for {client_id}")
            return False

        # Snapcast needs a moment to wire up the new group for the evicted client.
        time.sleep(0.5)
        new_group = self.find_client_group(client_id)
        if not new_group:
            print(f"❌ Couldn't find {client_id}'s new group after eviction")
            return False

        if not self.set_group_source(new_group.get("id"), home_source):
            print(f"❌ Failed to set stream on {client_id}'s new home group")
            return False

        print(f"✅ {client_id} returned home → {new_group.get('id')[:8]} @ {home_source}")
        return True

    def leave_group_on_source_change(self, client_id: str, source_id: str) -> List[str]:
        """A client that switches away from the source its group is playing
        can't stay in that group — snapcast would keep feeding it a stream
        it is no longer listening to.

        Non-host member → return just that client home.
        Host (the client whose home_source is the group's stream) → disband:
        every other member goes home, leaving the host alone in its own group.

        Returns the ids of the *other* clients that were sent home, so the
        caller can MQTT-publish their mode (they were moved without asking;
        the client that changed source did ask, and is left alone).
        """
        group = self.find_client_group(client_id)
        if not group:
            return []
        members = [c.get("id") for c in group.get("clients", [])
                   if c.get("connected") and c.get("id")]
        if len(members) < 2:
            return []

        # Group stream is `source_<host>_<source_id>`.
        parts = (group.get("stream_id") or "").split("_", 2)
        if len(parts) != 3 or parts[0] != "source":
            return []
        host_id, group_source = parts[1], parts[2]
        if source_id == group_source:
            return []

        if client_id != host_id:
            print(f"👋 {client_id} switched to {source_id} → leaving group")
            self.return_client_to_home(client_id)
            return []

        print(f"💥 Host {client_id} left {group_source} → disbanding group")
        return [cid for cid in members
                if cid != client_id and self.return_client_to_home(cid)]

    # ── Reconcile ─────────────────────────────────────────────────────────

    def reconcile_stream_assignments(self, groups: Optional[List[Dict[str, Any]]] = None) -> bool:
        """Retune any single-connected-client group whose stream_id doesn't
        match that client's home_source. Returns True if anything changed.

        This is the self-heal for the "orphaned stream" slip: a joined client
        left alone in a group that is still pointed at another client's stream
        — e.g. after the host is returned home, which evicts the host into a
        fresh group but never retunes the group it left behind. The lone
        survivor keeps playing the host's stream, so handle_get_groups derives
        the wrong home_client_id and the UI shows the wrong client's sources.

        Idempotent — fires only on a real mismatch — so it is safe to run on
        every /api/groups read as well as at boot. Recovers equally from
        snapcast's prune-and-recreate cycle where a fresh group inherits a
        default/wrong stream.

        `groups` may be passed by a caller that already fetched
        Server.GetStatus, to skip a redundant round-trip; otherwise it is
        fetched here. Never moves connected clients between groups.
        """
        if not self.config_manager:
            return False
        if groups is None:
            groups = self.get_groups()

        changed = False
        for group in groups:
            connected = [c for c in group.get("clients", []) if c.get("connected")]
            if len(connected) != 1:
                continue
            sole_id = connected[0].get("id")
            home_source = self._client_home_source(sole_id)
            if not home_source:
                continue
            if group.get("stream_id") == home_source:
                continue
            group_id = group.get("id")
            print(f"🔧 Reconcile: setting group {group_id[:8]}'s stream → {home_source} (sole client {sole_id})")
            if self.set_group_source(group_id, home_source):
                changed = True
        return changed

    # ── Startup reconcile ─────────────────────────────────────────────────

    def reconcile_startup(self) -> None:
        """One-shot at server boot. Retunes mismatched streams; evicts
        stale snapclient registrations that aren't in server_config.

        Two passes:
          1. Delete snapclient entries whose `id` isn't a registered
             fauxnos client id (e.g. lingering wlan0-MAC registrations
             from a legacy install path). These collide with the real
             client's lookup (same `host.name`) and pollute snapcast's
             state. Server.DeleteClient is the only way to remove them.
          2. Retune mismatched streams via reconcile_stream_assignments
             (now also run live on every /api/groups read).

        Never moves connected clients between groups.
        """
        if not self.config_manager:
            return

        registered_ids = {
            c.get("id") for c in self.config_manager.server_config.get("clients", []) if c.get("id")
        }

        # Pass 1: evict orphan snapclient registrations.
        for group in self.get_groups():
            for client in group.get("clients", []):
                cid = client.get("id")
                if not cid or cid in registered_ids:
                    continue
                if client.get("connected"):
                    # Real connected client we don't know about — leave it,
                    # cleanup logic elsewhere can handle this case.
                    continue
                print(f"🧹 Reconcile: deleting orphan snapclient {cid} (host.name={client.get('host', {}).get('name')})")
                self.send_snapcast_command("Server.DeleteClient", {"id": cid})

        # Pass 2: retune mismatched streams.
        self.reconcile_stream_assignments()
