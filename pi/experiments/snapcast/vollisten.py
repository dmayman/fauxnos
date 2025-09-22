#!/usr/bin/env python3
import json
import sys
import time
import signal
import requests

# ------------- CONFIG -------------
SNAPCAST_JSONRPC = "http://localhost:1780/jsonrpc"   # Snapserver JSON-RPC URL

POLL_INTERVAL_SEC = 0.35   # how often to poll each go-librespot instance
TIMEOUT_SEC = 2.5          # HTTP timeout

# List each stream you want to mirror volume for.
# gls_url: go-librespot API endpoint (the /player/volume URL)
# snap_stream_id: the Snapcast stream id (exactly as shown in Server.GetStatus -> streams[].id)
STREAMS = [
    {
        "name": "Stream1",
        "gls_url": "http://localhost:3678/player/volume",  # e.g., FauxnosGo_Stream1 instance
        "snap_stream_id": "Spotify1",
    },
    {
        "name": "Stream2",
        "gls_url": "http://localhost:3679/player/volume",  # e.g., FauxnosGo_Stream2 instance
        "snap_stream_id": "Spotify2",
    },
    # Add more here if you create more streams
]

# Optional: clamp or scale volume (leave as identity by default)
def transform_volume(v: int) -> int:
    """Map go-librespot volume (0..100) -> Snapcast percent (0..100)."""
    v = 0 if v < 0 else 100 if v > 100 else int(round(v))
    return v
# ----------------------------------


class Bridge:
    def __init__(self):
        self.session = requests.Session()
        self.last_volume = {s["snap_stream_id"]: None for s in STREAMS}

    # ---- Snapcast RPC helpers ----
    def _rpc(self, method: str, params: dict = None):
        payload = {"jsonrpc": "2.0", "id": int(time.time() * 1000), "method": method}
        if params is not None:
            payload["params"] = params
        resp = self.session.post(SNAPCAST_JSONRPC, json=payload, timeout=TIMEOUT_SEC)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"Snapcast RPC error: {data['error']}")
        return data.get("result")

    def snap_get_status(self):
        return self._rpc("Server.GetStatus")

    def snap_set_client_volume(self, client_id: str, percent: int):
        return self._rpc("Client.SetVolume", {"id": client_id, "volume": {"percent": percent}})

    # --------------------------------

    def clients_on_stream(self, status: dict, stream_id: str):
        """Return list of client IDs currently listening to the given stream."""
        ids = []
        server = status.get("server", {})
        for group in server.get("groups", []):
            if group.get("stream_id") == stream_id:
                for c in group.get("clients", []):
                    # Only act on connected clients
                    if c.get("connected", False):
                        ids.append(c.get("id"))
        return ids

    def get_gls_volume(self, url: str) -> int | None:
        """Return current go-librespot volume (0..100), or None if unavailable."""
        try:
            r = self.session.get(url, timeout=TIMEOUT_SEC)
            r.raise_for_status()
            js = r.json()
            # Expect {"value": N, "max": 100}
            val = js.get("value")
            if val is None:
                return None
            return transform_volume(int(val))
        except Exception as e:
            # print(f"[WARN] Failed to read volume from {url}: {e}", file=sys.stderr)
            return None

    def tick_once(self):
        # Fetch snapserver status once per cycle (so routing changes are picked up)
        try:
            status = self.snap_get_status()
        except Exception as e:
            print(f"[WARN] Snapcast Server.GetStatus failed: {e}", file=sys.stderr)
            return

        for entry in STREAMS:
            gls_url = entry["gls_url"]
            stream_id = entry["snap_stream_id"]

            vol = self.get_gls_volume(gls_url)
            if vol is None:
                continue

            if vol == self.last_volume.get(stream_id):
                continue  # no change, skip

            # Who's listening to this stream right now?
            client_ids = self.clients_on_stream(status, stream_id)

            # Fan-out volume set to those clients
            for cid in client_ids:
                try:
                    self.snap_set_client_volume(cid, vol)
                except Exception as e:
                    print(f"[WARN] Client.SetVolume failed for {cid} -> {vol}: {e}", file=sys.stderr)

            if client_ids:
                print(f"[INFO] {stream_id}: volume {self.last_volume.get(stream_id)} -> {vol} (clients: {len(client_ids)})")
            self.last_volume[stream_id] = vol

    def loop(self):
        print("[INFO] Starting go-librespot → Snapcast volume bridge")
        print(f"[INFO] Snapcast RPC: {SNAPCAST_JSONRPC}")
        for s in STREAMS:
            print(f"[INFO] Watching {s['gls_url']} -> stream '{s['snap_stream_id']}'")
        try:
            while True:
                self.tick_once()
                time.sleep(POLL_INTERVAL_SEC)
        except KeyboardInterrupt:
            print("\n[INFO] Stopped.")


def main():
    # Friendly warning if requests is missing fields we rely on
    b = Bridge()
    b.loop()


if __name__ == "__main__":
    # Ensure we exit cleanly on SIGTERM (systemd compatibility)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    main()