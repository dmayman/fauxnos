#!/usr/bin/env python3
"""
go-librespot HTTP + WebSocket controller.

go-librespot runs on the server (fauxnos000), one instance per client,
each on its own port (3600 + N). With `external_volume: true` and
`volume_steps: 100` set in its config (see server-side
config_manager.generate_go_librespot_config), the daemon exposes:

  * HTTP `POST /player/volume` — body `{"volume": 0-100}`. Sets the
    volume that gets sent to Spotify Connect (so the mobile-app slider
    moves) AND attenuates the audio fed into the snapcast FIFO.

  * WebSocket `/events` — emits JSON events for state changes the
    daemon learns about FROM Spotify: `{"type":"volume","data":...}`
    when the mobile-app slider moves, `{"type":"active"}` /
    `{"type":"inactive"}` when a session starts/stops, etc.

This module isolates both interfaces behind a single controller class.
The brief_spotify_volume_sync.md flow:

  fauxnos UI moves slider  →  source_manager.set_volume(spotify)
                          →  GoLibrespotController.set_volume(v)  HTTP
                          →  Spotify mobile slider mirrors

  Phone moves Spotify slider  →  go-librespot WS event {volume,data:{value}}
                              →  on_volume callback
                              →  source_manager.on_external_volume_change()
                              →  state persisted + MQTT publish

Echo prevention: every HTTP push opens a 300ms suppression window. WS
volume events landing inside that window are dropped — go-librespot
always echoes our push back over the WS, and without this guard we'd
ping-pong on every set. The window is small enough that a real phone
nudge in the same beat is still picked up afterward; the API is
idempotent so worst case is one frame of stale UI.

Reconnect: WS thread is a simple connect-loop with backoff (1s →
30s). Survives daemon restart, network blips, hostname-not-resolving-
yet at client boot. Setting `running=False` and stopping the WS app
breaks the loop on shutdown.
"""

import json
import logging
import threading
import time
from typing import Callable, Optional

import requests

try:
    import websocket  # websocket-client
except ImportError:
    websocket = None


# Backoff bounds for the WebSocket reconnect loop. 1s first retry,
# doubling, capped at 30s. Tuned so a clean restart of the
# go-librespot service reconnects within ~1s, but a sustained outage
# doesn't hammer the socket.
RECONNECT_BACKOFF_MIN = 1.0
RECONNECT_BACKOFF_MAX = 30.0

# How long after we POST /player/volume to ignore WS volume events.
# go-librespot echoes our push back; 0.3s comfortably covers HTTP +
# socket round-trip on a LAN without dropping real phone-side nudges.
ECHO_SUPPRESS_S = 0.3

# HTTP timeout for /player/volume. Should be short — this is a LAN
# call to a daemon on fauxnos000. If go-librespot is wedged longer
# than this, the volume is effectively dropped, but we'd rather fail
# fast than block the UI thread.
HTTP_TIMEOUT_S = 2.0


class GoLibrespotController:
    """
    Thin wrapper over the go-librespot HTTP + WebSocket interface for
    one client's go-librespot instance.

    Construct, attach callbacks, call `start()`. `set_volume(v)` is
    safe to call from any thread (it's a stateless HTTP POST).
    Callbacks fire from the WebSocket reader thread; if they touch
    shared state, the caller is responsible for locking.
    """

    def __init__(
        self,
        host: str,
        port: int,
        on_volume: Optional[Callable[[int], None]] = None,
        on_active: Optional[Callable[[], None]] = None,
        on_inactive: Optional[Callable[[], None]] = None,
    ):
        self.logger = logging.getLogger(__name__)
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.ws_url = f"ws://{host}:{port}/events"

        self.on_volume = on_volume
        self.on_active = on_active
        self.on_inactive = on_inactive

        # WebSocket plumbing
        self._ws_thread: Optional[threading.Thread] = None
        self._ws_app: Optional["websocket.WebSocketApp"] = None
        self._stop_evt = threading.Event()

        # Echo suppression. Updated whenever we POST a volume; the WS
        # event handler checks now < _suppress_volume_until and drops.
        # Plain monotonic timestamp — no lock needed, single writer
        # (set_volume) + single reader (_on_ws_message) and the worst
        # race is one missed-or-extra event, which is benign.
        self._suppress_volume_until: float = 0.0

    # -------- HTTP --------

    def set_volume(self, volume_pct: int) -> bool:
        """
        POST /player/volume with the requested level. Opens a 300ms
        echo-suppression window so go-librespot's WS confirmation
        doesn't bounce back into source_manager. Returns True on HTTP
        200, False on any failure (connection refused / timeout /
        non-2xx).

        Safe to call from any thread.
        """
        volume_pct = max(0, min(100, int(volume_pct)))
        self._suppress_volume_until = time.monotonic() + ECHO_SUPPRESS_S
        url = f"{self.base_url}/player/volume"
        try:
            resp = requests.post(
                url,
                json={"volume": volume_pct},
                timeout=HTTP_TIMEOUT_S,
            )
            if resp.status_code == 200 or resp.status_code == 204:
                self.logger.debug(f"go-librespot volume → {volume_pct}%")
                return True
            self.logger.warning(
                f"go-librespot set_volume HTTP {resp.status_code}: {resp.text[:120]}"
            )
            return False
        except requests.exceptions.ConnectionError:
            # Daemon not running yet — common at boot. Log at debug,
            # not warning, to avoid spamming the journal during the
            # systemd start ordering race.
            self.logger.debug(f"go-librespot connection refused at {url}")
            return False
        except requests.exceptions.Timeout:
            self.logger.warning(f"go-librespot set_volume timeout at {url}")
            return False
        except Exception as e:
            self.logger.error(f"go-librespot set_volume error: {e}")
            return False

    # -------- WebSocket --------

    def start(self):
        """
        Start the WebSocket reader thread. Idempotent — calling twice
        is a no-op. No-op + warning if `websocket-client` is not
        installed (the daemon still runs; HTTP push from set_volume
        keeps working, we just lose mobile-side change detection).
        """
        if websocket is None:
            self.logger.warning(
                "websocket-client not installed — Spotify-side volume changes "
                "will not propagate to fauxnos. Install with: "
                "pip3 install --user websocket-client --break-system-packages"
            )
            return
        if self._ws_thread is not None and self._ws_thread.is_alive():
            return
        self._stop_evt.clear()
        self._ws_thread = threading.Thread(
            target=self._ws_loop,
            name="go-librespot-ws",
            daemon=True,
        )
        self._ws_thread.start()
        self.logger.info(f"go-librespot WebSocket reader started ({self.ws_url})")

    def stop(self):
        """Stop the WebSocket reader. Idempotent."""
        self._stop_evt.set()
        if self._ws_app is not None:
            try:
                self._ws_app.close()
            except Exception:
                pass
        if self._ws_thread is not None:
            self._ws_thread.join(timeout=2.0)
        self._ws_thread = None
        self._ws_app = None

    def _ws_loop(self):
        """
        Reconnect loop: connect → run_forever (blocks) → backoff →
        retry, until stop is set. run_forever returns either on
        normal close or on error; either way we backoff and try
        again. Backoff resets to 1s after any successful connect, so
        a stable WS that briefly blips doesn't end up at the 30s cap.
        """
        backoff = RECONNECT_BACKOFF_MIN
        while not self._stop_evt.is_set():
            try:
                self._ws_app = websocket.WebSocketApp(
                    self.ws_url,
                    on_open=self._on_ws_open,
                    on_message=self._on_ws_message,
                    on_error=self._on_ws_error,
                    on_close=self._on_ws_close,
                )
                # Reset backoff so a working connection that flaps
                # doesn't compound the delay.
                backoff = RECONNECT_BACKOFF_MIN
                self._ws_app.run_forever(
                    ping_interval=30,
                    ping_timeout=10,
                )
            except Exception as e:
                self.logger.debug(f"WebSocket loop exception: {e}")

            if self._stop_evt.is_set():
                break

            self.logger.debug(f"go-librespot WS reconnect in {backoff:.1f}s")
            # Use Event.wait so stop() interrupts the sleep cleanly.
            if self._stop_evt.wait(backoff):
                break
            backoff = min(backoff * 2, RECONNECT_BACKOFF_MAX)

    def _on_ws_open(self, ws):
        self.logger.info(f"go-librespot WebSocket connected: {self.ws_url}")

    def _on_ws_close(self, ws, status, msg):
        # Frequent on go-librespot restart. Don't warn — _ws_loop
        # will reconnect.
        self.logger.debug(f"go-librespot WebSocket closed: {status} {msg}")

    def _on_ws_error(self, ws, error):
        # Most errors here are connection-refused / DNS-not-ready at
        # boot; downgraded to debug for the same reason as set_volume.
        self.logger.debug(f"go-librespot WebSocket error: {error}")

    def _on_ws_message(self, ws, message: str):
        """
        Dispatch JSON events from go-librespot.

        Event shapes we care about:
          {"type": "volume",   "data": {"value": <0-100>, "max": 100}}
          {"type": "active",   "data": {...}}
          {"type": "inactive", "data": {...}}

        Anything else (track, playing, metadata, seek, …) is ignored
        here — those belong to brief_auto_source_switching.md.
        """
        try:
            evt = json.loads(message)
        except json.JSONDecodeError:
            self.logger.debug(f"go-librespot WS non-JSON: {message[:120]}")
            return

        etype = evt.get("type")
        data = evt.get("data", {})

        if etype == "volume":
            value = data.get("value")
            if value is None:
                return
            # Drop echoes from our own /player/volume POSTs.
            if time.monotonic() < self._suppress_volume_until:
                self.logger.debug(
                    f"go-librespot WS volume {value} (suppressed — own echo)"
                )
                return
            self.logger.debug(f"go-librespot WS volume → {value} (external)")
            if self.on_volume:
                try:
                    self.on_volume(int(value))
                except Exception as e:
                    self.logger.error(f"on_volume callback raised: {e}")

        elif etype == "active":
            self.logger.info("go-librespot session active (Spotify connected)")
            if self.on_active:
                try:
                    self.on_active()
                except Exception as e:
                    self.logger.error(f"on_active callback raised: {e}")

        elif etype == "inactive":
            self.logger.info("go-librespot session inactive")
            if self.on_inactive:
                try:
                    self.on_inactive()
                except Exception as e:
                    self.logger.error(f"on_inactive callback raised: {e}")
