#!/usr/bin/env python3
"""
Playback Manager

One WebSocket subscription per client to go-librespot's /events stream;
fetches /status on each (re)connect for the initial snapshot. Republishes
to two retained MQTT topics so any UI joining mid-session immediately
sees the current track + play state:

    status/clients/<client_id>/track     — JSON track metadata
    status/clients/<client_id>/playback  — JSON {is_playing, position_ms, updated_at}

Position is server-stamped at the moment of the last go-librespot event;
the UI interpolates locally between events. The server does NOT send
periodic position updates — that would be wasted MQTT chatter against a
clock the browser can read itself. Real events (play/pause/seek/track-
change) push fresh `position_ms + updated_at` and the UI re-bases.

Source-agnostic shape: `track.source` is currently always "spotify" but
AirPlay (shairport metadata pipe) can be plugged in later without UI
changes.
"""

import asyncio
import json
import logging
import threading
import time
from typing import Dict, Optional

import paho.mqtt.client as mqtt
import requests
import websockets

from .config_manager import ConfigManager


def _now_ms() -> int:
    return int(time.time() * 1000)


class PlaybackManager:
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self.running = False
        self.threads = []
        self.logger = logging.getLogger('PlaybackManager')

        # Last published payloads keyed by client_id, so we can update
        # incrementally (e.g. seek event only carries position) without
        # losing track metadata.
        self._track: Dict[str, dict] = {}
        self._playback: Dict[str, dict] = {}

        self.mqtt: Optional[mqtt.Client] = None
        self._init_mqtt()

    def _init_mqtt(self):
        try:
            mqtt_cfg = self.config_manager.server_config.get('server', {}).get('mqtt', {})
            host = mqtt_cfg.get('broker_host', 'localhost')
            port = int(mqtt_cfg.get('broker_port', 1883))
            self.mqtt = mqtt.Client(client_id='fauxnos-playback-manager')
            self.mqtt.connect(host, port, keepalive=60)
            self.mqtt.loop_start()
            self.logger.info(f"PlaybackManager MQTT publisher connected to {host}:{port}")
        except Exception as e:
            self.logger.warning(f"PlaybackManager MQTT connect failed: {e}")
            self.mqtt = None

    def _publish(self, topic: str, payload: dict):
        if self.mqtt is None:
            return
        try:
            self.mqtt.publish(topic, json.dumps(payload), retain=True)
        except Exception as e:
            self.logger.warning(f"MQTT publish failed for {topic}: {e}")

    def _publish_track(self, client_id: str, track: dict):
        self._track[client_id] = track
        self._publish(f"status/clients/{client_id}/track", track)

    def _publish_playback(self, client_id: str, is_playing: bool, position_ms: int):
        payload = {
            "is_playing": bool(is_playing),
            "position_ms": int(position_ms or 0),
            "updated_at": _now_ms(),
        }
        self._playback[client_id] = payload
        self._publish(f"status/clients/{client_id}/playback", payload)

    def _publish_empty(self, client_id: str):
        """Clear retained topics when a session goes inactive — the UI
        should fall back to a no-track placeholder rather than show
        stale metadata from a previous session."""
        self._track.pop(client_id, None)
        self._playback.pop(client_id, None)
        if self.mqtt:
            try:
                # Retained empty payload — broker drops the retained
                # message, so a fresh subscriber sees nothing instead
                # of the last track.
                self.mqtt.publish(f"status/clients/{client_id}/track", "", retain=True)
                self.mqtt.publish(f"status/clients/{client_id}/playback", "", retain=True)
            except Exception:
                pass

    def start(self):
        if self.running:
            self.logger.warning("Playback manager already running")
            return
        self.running = True
        clients = self.config_manager.list_clients()
        for client in clients:
            t = threading.Thread(
                target=self._run_ws,
                args=(client.id, client.server_port),
                daemon=True,
            )
            t.start()
            self.threads.append(t)
        self.logger.info(f"Playback manager started for {len(self.threads)} client(s)")

    def stop(self):
        if not self.running:
            return
        self.running = False
        for t in self.threads:
            t.join(timeout=2.0)
        self.threads = []
        if self.mqtt is not None:
            try:
                self.mqtt.loop_stop()
                self.mqtt.disconnect()
            except Exception:
                pass
            self.mqtt = None
        self.logger.info("Playback manager stopped")

    def _run_ws(self, client_id: str, server_port: int):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._ws_listener(client_id, server_port))
        except Exception as e:
            self.logger.error(f"Playback WS listener error for {client_id}: {e}")
        finally:
            loop.close()

    async def _ws_listener(self, client_id: str, server_port: int):
        ws_url = f"ws://localhost:{server_port}/events"
        retry_delay = 5
        self.logger.info(f"Starting playback WS listener for {client_id} on {ws_url}")

        while self.running:
            try:
                async with websockets.connect(ws_url, ping_interval=20, ping_timeout=10) as ws:
                    self.logger.info(f"Playback WS connected for {client_id}")
                    # Snapshot on connect so a fresh subscriber gets
                    # current state without waiting for the next event.
                    self._fetch_status_snapshot(client_id, server_port)

                    async for message in ws:
                        if not self.running:
                            break
                        try:
                            event = json.loads(message)
                            self._handle_event(client_id, event, server_port)
                        except json.JSONDecodeError:
                            self.logger.debug(f"non-JSON event from {client_id}")
                        except Exception as e:
                            self.logger.error(f"Error handling event for {client_id}: {e}")

            except websockets.exceptions.WebSocketException as e:
                if self.running:
                    self.logger.debug(f"Playback WS disconnect {client_id}: {e}; retry {retry_delay}s")
                    await asyncio.sleep(retry_delay)
            except Exception as e:
                if self.running:
                    self.logger.debug(f"Playback WS error {client_id}: {e}; retry {retry_delay}s")
                    await asyncio.sleep(retry_delay)

        self.logger.info(f"Playback WS listener stopped for {client_id}")

    def _fetch_status_snapshot(self, client_id: str, server_port: int):
        """Hit go-librespot's /status to seed the retained MQTT topics
        on connect. Idempotent — same shape as a metadata event."""
        try:
            r = requests.get(f"http://localhost:{server_port}/status", timeout=2.0)
            r.raise_for_status()
            status = r.json()
        except Exception as e:
            self.logger.debug(f"status snapshot {client_id}: {e}")
            return

        track = status.get('track') or {}
        if track:
            self._publish_track(client_id, _normalize_track(track))
            self._publish_playback(
                client_id,
                is_playing=not status.get('paused', True) and not status.get('stopped', True),
                position_ms=track.get('position', 0) or 0,
            )
        else:
            self._publish_empty(client_id)

    def _resolve_position(self, client_id: str, data: dict, server_port: int) -> int:
        """Best position for a playback event whose payload may or may
        not carry one.

        go-librespot's `paused`, `playing`, and `seek` events sometimes
        omit `position` from their `data` block (verified empirically on
        v0.x — paused/playing events carry only context/uri/play_origin).
        Falling back to 0 makes the UI jump to 0:00 on every pause/resume.

        Resolution order:
          1. event's `position` field (when present, authoritative)
          2. go-librespot's /status `track.position` (accurate, ~5ms HTTP)
          3. interpolate from prev._playback (last-known good)
        """
        if data.get('position') is not None:
            return int(data['position'])
        try:
            r = requests.get(f"http://localhost:{server_port}/status", timeout=1.0)
            r.raise_for_status()
            track = r.json().get('track') or {}
            if track.get('position') is not None:
                return int(track['position'])
        except Exception as e:
            self.logger.debug(f"status fetch for position fallback {client_id}: {e}")
        prev = self._playback.get(client_id) or {}
        prev_pos = int(prev.get('position_ms') or 0)
        if prev.get('is_playing'):
            elapsed = _now_ms() - int(prev.get('updated_at') or _now_ms())
            return max(0, prev_pos + elapsed)
        return prev_pos

    def _handle_event(self, client_id: str, event: dict, server_port: int):
        etype = event.get('type')
        data = event.get('data') or {}

        if etype == 'metadata':
            # Full track payload — replace the track topic entirely.
            track = _normalize_track(data)
            self._publish_track(client_id, track)
            # Metadata events arrive at the start of a new track; the
            # payload itself doesn't carry position, so fall back to
            # /status (which has the new track.position, typically ~0)
            # rather than zeroing the UI on every track change.
            prev = self._playback.get(client_id, {})
            self._publish_playback(
                client_id,
                is_playing=prev.get('is_playing', False),
                position_ms=self._resolve_position(client_id, data, server_port),
            )
            return

        if etype == 'playing':
            self._publish_playback(
                client_id,
                is_playing=True,
                position_ms=self._resolve_position(client_id, data, server_port),
            )
            return

        if etype in ('paused', 'not_playing'):
            self._publish_playback(
                client_id,
                is_playing=False,
                position_ms=self._resolve_position(client_id, data, server_port),
            )
            return

        if etype == 'seek':
            prev = self._playback.get(client_id, {})
            self._publish_playback(
                client_id,
                is_playing=prev.get('is_playing', False),
                position_ms=self._resolve_position(client_id, data, server_port),
            )
            return

        if etype in ('stopped', 'inactive'):
            self._publish_empty(client_id)
            return

        # Other events (volume, active, will_play) are not playback state.


def _normalize_track(data: dict) -> dict:
    """Flatten go-librespot's metadata payload into the topic shape the
    UI consumes. Field names align with what shairport-sync's metadata
    pipe also exposes, so an AirPlay producer can publish the same shape
    later without touching the UI."""
    artist_names = data.get('artist_names') or []
    if isinstance(artist_names, str):
        artist_names = [artist_names]
    return {
        "source": "spotify",
        "uri": data.get('uri') or '',
        "title": data.get('name') or '',
        "artist": ", ".join(artist_names),
        "album": data.get('album_name') or '',
        "art_url": data.get('album_cover_url') or '',
        "duration_ms": int(data.get('duration') or 0),
    }


if __name__ == '__main__':
    import time as _t
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    )
    cm = ConfigManager()
    pm = PlaybackManager(cm)
    try:
        pm.start()
        print("Playback manager running... Ctrl+C to stop")
        while True:
            _t.sleep(1)
    except KeyboardInterrupt:
        pm.stop()
