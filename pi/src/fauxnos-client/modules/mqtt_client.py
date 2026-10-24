#!/usr/bin/env python3
"""
MQTT Client Module

Handles MQTT communication for Fauxnos audio clients.
Publishes status updates and listens for control commands.

Topic schema:
  Control (UI → client):
    set/clients/<deviceId>/volume     payload: "75"
    set/clients/<deviceId>/mode       payload: "spotify", or JSON
                                      {"source": "noise", "fade_ms": 8000}
                                      to crossfade (routines; UI sends plain)
    set/clients/<deviceId>/library/play  payload: {"items": ["lullabies/x.mp3"],
                                                   "loop": false, "fade_ms": 0}
                                      plays on this device's MPD and switches
                                      to the `library` source. Items are
                                      paths under the server's library
                                      folder, or full URLs.
    set/clients/<deviceId>/library/stop  payload: (ignored)
    set/clients/<deviceId>/eq         payload: {"enabled": true,
                                                "bands": {"125": 6.0, ...}}

  Status (client → UI):
    status/clients/<deviceId>/volume  payload: "75"
    status/clients/<deviceId>/mode    payload: "spotify"
    status/clients/<deviceId>/activity payload: "playing"|"silent"
    status/clients/<deviceId>/hello   payload: {"id","name","sources"}
    status/clients/<deviceId>/online  payload: "online"|"offline" (retained;
                                      "offline" is the broker-sent last will)
    status/clients/<deviceId>/eq      payload: {"enabled": bool,
                                                "bands": {hz_str: gain_db}}

  Discovery:
    get/clients/<deviceId>/volume     → client publishes volume
    get/clients/<deviceId>/eq         → client publishes eq state
    get/clients/<deviceId>/status     → client publishes hello + mode
    get/clients/all/status            → all clients publish hello
"""

import json
import logging
import threading
import time
from typing import Callable, Optional, Dict, List

import paho.mqtt.client as mqtt

from .config_manager import ConfigManager

logger = logging.getLogger(__name__)

# The local-MPD source (see modules/library_player.py).
LIBRARY_SOURCE_ID = "library"
# Longest crossfade a command may ask for (10 min). Routines fade over
# seconds to a minute or two; anything past this is a typo.
MAX_FADE_MS = 10 * 60 * 1000

# The broker publishes the last will after 1.5x keepalive without a packet,
# so a room that drops off the network shows offline within ~30s. Each idle
# keepalive is one 2-byte PINGREQ, so shorter is cheap.
KEEPALIVE_S = 20


class MQTTClient:
    def __init__(self, config_manager: ConfigManager,
                 volume_callback: Callable[[int], bool],
                 mode_callback: Callable[[str], bool],
                 source_volume_getter: Optional[Callable[[str], Optional[int]]] = None,
                 calibration_callback: Optional[Callable[[str, int], bool]] = None,
                 calibration_getter: Optional[Callable[[str], int]] = None,
                 ir_enable_callback: Optional[Callable[[bool], None]] = None,
                 ir_clear_callback: Optional[Callable[[str], None]] = None,
                 ir_state_getter: Optional[Callable[[], dict]] = None,
                 ir_learn_start_callback: Optional[Callable[[str, float], bool]] = None,
                 ir_learn_cancel_callback: Optional[Callable[[], bool]] = None,
                 ir_feedback_volume_callback: Optional[Callable[[int], None]] = None,
                 eq_callback: Optional[Callable[[bool, Optional[Dict[str, float]]], bool]] = None,
                 eq_getter: Optional[Callable[[], Dict]] = None,
                 evc_state_callback: Optional[Callable[[bool, int], None]] = None,
                 evc_mirror_callback: Optional[Callable[[int], None]] = None,
                 library_play_callback: Optional[Callable[[List[str], bool, int], bool]] = None,
                 library_stop_callback: Optional[Callable[[], bool]] = None,
                 broker_host: Optional[str] = None,
                 broker_port: int = 1883):
        """
        Initialize MQTT client

        Args:
            config_manager: ConfigManager instance with device/source info
            volume_callback: Called on volume command → SourceManager.set_volume()
            mode_callback: Called on mode command → SourceManager.switch_source()
            calibration_callback: (source_id, value) → SourceManager.set_calibration().
                Called when 'set/clients/<id>/calibration/<source>' arrives. Optional.
            calibration_getter: (source_id) → int. Used to populate hello/status.
            ir_enable_callback: (bool) → None. Toggle the IR feature flag.
                Wired to IRListener.set_enabled.
            ir_clear_callback: (command_id) → None. Forget a single command's
                mapping. Wired to IRListener.clear_command.
            ir_state_getter: () → {"enabled","mappings"} dict. Used to
                populate hello + status/ir/state payloads. Wired to
                IRListener.state_manager.get_ir() in the daemon.
            ir_learn_start_callback: (command_id, timeout_s) → bool. Enter
                learn mode for the given command. Wired to
                IRListener.start_learning. Returns False if a learn is
                already in flight.
            ir_learn_cancel_callback: () → bool. Cancel an in-flight learn.
                Wired to IRListener.cancel_learning. Returns False if no
                learn was active.
            library_play_callback: (items, loop, fade_ms) → bool. Queue items on
                the local MPD and switch to the library source. Wired to
                FauxnosClient._library_play.
            library_stop_callback: () → bool. Stop local MPD playback.
            broker_host: MQTT broker hostname (defaults to server_host from config)
            broker_port: MQTT broker port
        """
        self.config_manager = config_manager
        self.device_id = config_manager.device_config.name
        self.display_name = config_manager.device_config.display_name or self.device_id

        # Broker defaults to the fauxnos server
        mqtt_config = config_manager.config.get('mqtt', {})
        self.broker_host = broker_host or mqtt_config.get('broker_host', config_manager.server_host)
        self.broker_port = mqtt_config.get('broker_port', broker_port)

        # Callbacks for handling commands
        self.volume_callback = volume_callback
        self.mode_callback = mode_callback
        self.source_volume_getter = source_volume_getter
        self.calibration_callback = calibration_callback
        self.calibration_getter = calibration_getter
        self.ir_enable_callback = ir_enable_callback
        self.ir_clear_callback = ir_clear_callback
        self.ir_state_getter = ir_state_getter
        self.ir_learn_start_callback = ir_learn_start_callback
        self.ir_learn_cancel_callback = ir_learn_cancel_callback
        self.ir_feedback_volume_callback = ir_feedback_volume_callback
        self.eq_callback = eq_callback
        self.eq_getter = eq_getter
        self.evc_state_callback = evc_state_callback
        self.evc_mirror_callback = evc_mirror_callback
        self.library_play_callback = library_play_callback
        self.library_stop_callback = library_stop_callback

        # MQTT client setup
        self.client = mqtt.Client(client_id=f"fauxnos-{self.device_id}")
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        # Set before connect: the broker stores the will at CONNECT time.
        self.client.will_set(self._online_topic(), "offline", retain=True)

        self.connected = False
        self.should_run = True

        # Current state tracking
        self.current_mode = "idle"
        self.current_volume = 0
        self.current_activity = "silent"

        # Build sources list from config
        self.sources_list = self._determine_sources()

        # Volume commands are applied by a worker that takes only the newest
        # value. Applying one can block (a name lookup of the server can take
        # 5s), and replaying every command queued behind it walks the volume,
        # and every UI slider, back through the stale values.
        self._pending_volume: Optional[int] = None
        self._volume_evt = threading.Event()
        # Serializes volume application with the other commands, which run
        # on the paho thread, so a mode switch can't interleave with it.
        self._command_lock = threading.Lock()
        threading.Thread(
            target=self._volume_worker, name="mqtt-volume", daemon=True
        ).start()

    def _determine_sources(self) -> List[str]:
        """Get list of source IDs from config"""
        return list(self.config_manager.sources.keys())

    def _online_topic(self) -> str:
        return f"status/clients/{self.device_id}/online"

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected = True
            logger.info(f"Connected to MQTT broker at {self.broker_host}:{self.broker_port}")
            # Overwrites the retained will from the last time we dropped.
            client.publish(self._online_topic(), "online", retain=True)
            self._subscribe_to_control_topics()
            self._send_hello()
        else:
            logger.error(f"Failed to connect to MQTT broker, return code {rc}")

    def _on_disconnect(self, client, userdata, rc):
        self.connected = False
        if rc != 0:
            logger.warning("Unexpected disconnection from MQTT broker")
        else:
            logger.info("Disconnected from MQTT broker")

    def _subscribe_to_control_topics(self):
        topics = [
            f"set/clients/{self.device_id}/volume",
            f"set/clients/{self.device_id}/mode",
            # Calibration is per-source (5-part topic), so use a + wildcard.
            f"set/clients/{self.device_id}/calibration/+",
            # IR (hardware remote): enabled toggle, per-command clear,
            # and learn-mode lifecycle.
            f"set/clients/{self.device_id}/ir/enabled",
            f"set/clients/{self.device_id}/ir/clear/+",
            f"set/clients/{self.device_id}/ir/learn/start",
            f"set/clients/{self.device_id}/ir/learn/cancel",
            f"set/clients/{self.device_id}/ir/feedback_volume",
            # EQ — JSON payload, see _handle_command's "eq" branch.
            f"set/clients/{self.device_id}/eq",
            # Library player (local MPD): play / stop.
            f"set/clients/{self.device_id}/library/+",
            # External volume controller config (retained, server-published).
            # Tells the client whether its local audio chain should be pinned
            # at unity (external authority owns attenuation), and how far to
            # pad the DAC output to keep that full-scale signal from
            # overloading the analog stage downstream — see
            # SourceManager.set_external_volume_state.
            f"config/clients/{self.device_id}/external_volume_controller",
            # External-volume authoritative-value mirror: server publishes
            # here whenever the external device reports a new volume (knob
            # turn, UI-slider round-trip echo). Client pushes to go-librespot
            # so the Spotify phone slider tracks the external authority.
            f"set/clients/{self.device_id}/external_volume_mirror",
            f"get/clients/{self.device_id}/volume",
            f"get/clients/{self.device_id}/status",
            f"get/clients/{self.device_id}/activity",
            f"get/clients/{self.device_id}/calibration",
            f"get/clients/{self.device_id}/ir",
            f"get/clients/{self.device_id}/eq",
            "get/clients/all/status",
        ]
        for topic in topics:
            self.client.subscribe(topic)
            logger.debug(f"Subscribed to: {topic}")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode('utf-8')
        logger.debug(f"MQTT message: {topic} -> {payload}")

        # Broadcast discovery. The UI fires this on every connect to
        # bootstrap state for all clients. We send hello AND republish
        # the retained status topics — retain alone is enough in theory,
        # but this is the explicit "I just connected, what's current"
        # path and republishing here makes the bootstrap deterministic
        # (no dependence on broker retain behavior or message ordering).
        if topic == "get/clients/all/status":
            self._send_hello()
            self.publish_mode()
            self.publish_volume()
            self.publish_activity()
            self.publish_calibrations()
            self.publish_ir_state()
            self.publish_eq_state()
            return

        # Parse topic: {command_type}/clients/{device_id}/{action}[/{sub_action}[/{cmd_id}]]
        parts = topic.split('/')
        if len(parts) >= 4:
            command_type = parts[0]
            device_id = parts[2]
            action = parts[3]
            sub_action = parts[4] if len(parts) >= 5 else None
            tail = parts[5] if len(parts) >= 6 else None
            if device_id != self.device_id:
                return

            # config/clients/<id>/external_volume_controller — retained
            # payload (JSON) telling us whether this device is in
            # external-volume mode. Routed before the generic handler
            # because it's a "config" command_type, not "set"/"get".
            if (
                command_type == "config"
                and action == "external_volume_controller"
                and self.evc_state_callback is not None
            ):
                try:
                    cfg = json.loads(payload) if payload else {}
                    self.evc_state_callback(
                        bool(cfg.get("enabled", False)),
                        int(cfg.get("output_pad_db", 0) or 0),
                    )
                except Exception as e:
                    logger.warning(f"Failed to parse EVC config payload: {e}")
                return

            # set/clients/<id>/external_volume_mirror — server-published
            # authoritative value from the external device (Photon knob /
            # UI round-trip). Mirror it to go-librespot so the Spotify
            # phone slider tracks. Routed before _handle_command because
            # it's an out-of-band "set" sub-action not in that switch.
            if (
                command_type == "set"
                and action == "external_volume_mirror"
                and self.evc_mirror_callback is not None
            ):
                try:
                    self.evc_mirror_callback(int(payload))
                except Exception as e:
                    logger.warning(f"Failed to handle EVC mirror payload {payload!r}: {e}")
                return

            # 6-part topics (extra trailing identifier) are handled
            # before the generic _handle_command interface, which only
            # carries a single sub_action slot.
            if command_type == "set" and action == "ir":
                if sub_action == "clear" and tail:
                    self._handle_ir_clear(tail)
                    return
                if sub_action == "learn" and tail == "start":
                    self._handle_ir_learn_start(payload)
                    return
                if sub_action == "learn" and tail == "cancel":
                    self._handle_ir_learn_cancel()
                    return

            self._handle_command(command_type, action, payload, sub_action)

    def _volume_worker(self):
        """Apply the newest pending volume; values superseded meanwhile are dropped."""
        while True:
            self._volume_evt.wait()
            # Clear before reading, so a value set after the read re-arms the event.
            self._volume_evt.clear()
            volume = self._pending_volume
            try:
                with self._command_lock:
                    self.volume_callback(volume)
                    self.update_volume(volume)
            except Exception as e:
                logger.error(f"Error applying volume {volume}%: {e}")

    def _handle_command(
        self,
        command_type: str,
        action: str,
        payload: str,
        sub_action: Optional[str] = None,
    ):
        if command_type == "set" and action == "volume":
            try:
                volume = int(payload)
            except ValueError:
                logger.error(f"Invalid volume value: {payload!r}")
                return
            if 0 <= volume <= 100:
                logger.info(f"MQTT volume command: {volume}%")
                self._pending_volume = volume
                self._volume_evt.set()
            else:
                logger.error(f"Invalid volume value: {volume}")
            return
        with self._command_lock:
            self._handle_locked_command(command_type, action, payload, sub_action)

    @staticmethod
    def _fade_ms(value) -> int:
        """Coerce a fade_ms field; anything unusable means no fade."""
        try:
            return max(0, min(int(value or 0), MAX_FADE_MS))
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _parse_mode_payload(cls, payload: str):
        """A mode payload is a bare source id, or JSON {"source", "fade_ms"}.

        Returns (source_id, fade_ms). The UIs send bare ids; routines (Home
        Assistant, the wall panel) send JSON to crossfade.
        """
        text = (payload or "").strip()
        if text.startswith("{"):
            try:
                data = json.loads(text)
            except Exception:
                return text, 0
            if isinstance(data, dict):
                return str(data.get("source", "")), cls._fade_ms(data.get("fade_ms"))
        return text, 0

    def _publish_new_mode(self, source_id: str):
        self.update_mode(source_id)
        # Each source remembers its own volume; the UI is
        # mode-aware and shows the active source's stored
        # level. Without this re-publish, the slider keeps
        # whatever value it had under the PREVIOUS source —
        # e.g. set spotify=15, switch to analog=90, switch
        # back to spotify, UI still reads 90 even though
        # source_manager correctly restored 15.
        if self.source_volume_getter is not None:
            new_vol = self.source_volume_getter(source_id)
            if new_vol is not None:
                self.update_volume(new_vol)

    def _handle_locked_command(
        self,
        command_type: str,
        action: str,
        payload: str,
        sub_action: Optional[str] = None,
    ):
        try:
            if command_type == "set":
                if action == "mode":
                    source_id, fade_ms = self._parse_mode_payload(payload)
                    if source_id in self.sources_list:
                        logger.info(f"MQTT mode command: {source_id}"
                                    + (f" (fade {fade_ms} ms)" if fade_ms else ""))
                        if fade_ms:
                            self.mode_callback(source_id, fade_ms=fade_ms)
                        else:
                            self.mode_callback(source_id)
                        self._publish_new_mode(source_id)
                    else:
                        logger.error(f"Invalid mode: {payload}. Available: {self.sources_list}")

                elif action == "library" and sub_action == "play":
                    # set/clients/<id>/library/play payload:
                    #   {"items": [...], "loop": bool, "fade_ms": int}
                    # ("item": "..." is accepted for a single track.)
                    if self.library_play_callback is None or LIBRARY_SOURCE_ID not in self.sources_list:
                        logger.warning("MQTT library/play but this device has no library source")
                        return
                    try:
                        data = json.loads(payload or "{}")
                    except Exception:
                        logger.error(f"MQTT library/play: bad JSON payload: {payload!r}")
                        return
                    if not isinstance(data, dict):
                        logger.error("MQTT library/play: payload must be an object")
                        return
                    items = data.get("items")
                    if items is None and data.get("item"):
                        items = [data["item"]]
                    if not isinstance(items, list) or not items:
                        logger.error(f"MQTT library/play: 'items' must be a non-empty list: {payload!r}")
                        return
                    loop = bool(data.get("loop", False))
                    fade_ms = self._fade_ms(data.get("fade_ms"))
                    logger.info(f"MQTT library/play: {len(items)} item(s), loop={loop}, fade={fade_ms}")
                    if self.library_play_callback([str(i) for i in items], loop, fade_ms):
                        self._publish_new_mode(LIBRARY_SOURCE_ID)

                elif action == "library" and sub_action == "stop":
                    if self.library_stop_callback is None:
                        logger.warning("MQTT library/stop but no callback wired")
                    else:
                        logger.info("MQTT library/stop")
                        self.library_stop_callback()

                elif action == "calibration" and sub_action:
                    # set/clients/<id>/calibration/<source_id> payload: "75"
                    source_id = sub_action
                    if self.calibration_callback is None:
                        logger.warning(
                            f"MQTT calibration command for {source_id} but no callback wired"
                        )
                    else:
                        try:
                            value = int(payload)
                        except ValueError:
                            logger.error(f"Invalid calibration value: {payload}")
                            return
                        if not (0 <= value <= 200):
                            logger.error(f"Calibration value out of range 0-200: {value}")
                            return
                        logger.info(f"MQTT calibration command: {source_id} → {value}%")
                        if self.calibration_callback(source_id, value):
                            # Echo current value(s) back so the UI can update.
                            # The setter may apply to multiple sources (sources
                            # sharing a sink share calibration), so re-publish
                            # everything we know.
                            self.publish_calibrations()

                elif action == "ir" and sub_action == "enabled":
                    # set/clients/<id>/ir/enabled payload: "true"/"false"
                    if self.ir_enable_callback is None:
                        logger.warning("MQTT ir/enabled command but no callback wired")
                    else:
                        enabled = payload.strip().lower() in ("true", "1", "yes", "on")
                        logger.info(f"MQTT ir/enabled command: {enabled}")
                        self.ir_enable_callback(enabled)
                        self.publish_ir_state()

                elif action == "eq":
                    # set/clients/<id>/eq — payload JSON:
                    #   {"enabled": bool, "bands": {hz_str: gain_db, ...}}
                    # Either key may be omitted (e.g. an enable toggle
                    # sends just "enabled"; a slider drag sends just
                    # "bands"). EqController.set_state handles the
                    # partial-update merge against the persisted state.
                    if self.eq_callback is None:
                        logger.warning("MQTT eq command but no callback wired")
                    else:
                        try:
                            data = json.loads(payload or "{}")
                        except Exception:
                            logger.error(f"MQTT eq: bad JSON payload: {payload!r}")
                            return
                        if not isinstance(data, dict):
                            logger.error(f"MQTT eq: payload must be an object, got {type(data).__name__}")
                            return
                        # If 'enabled' is missing, keep whatever the
                        # controller has now (avoids surprising state
                        # flips on a band-only message).
                        current = self.eq_getter() if self.eq_getter else {"enabled": False}
                        enabled = bool(data.get("enabled", current.get("enabled", False)))
                        bands = data.get("bands")
                        if bands is not None and not isinstance(bands, dict):
                            logger.error(f"MQTT eq: 'bands' must be an object, got {type(bands).__name__}")
                            return
                        logger.info(f"MQTT eq command: enabled={enabled} bands={bands}")
                        if self.eq_callback(enabled, bands):
                            self.publish_eq_state()

                elif action == "ir" and sub_action == "feedback_volume":
                    # set/clients/<id>/ir/feedback_volume payload: "0".."100"
                    if self.ir_feedback_volume_callback is None:
                        logger.warning(
                            "MQTT ir/feedback_volume command but no callback wired"
                        )
                    else:
                        try:
                            vol = int(payload)
                        except ValueError:
                            logger.error(
                                f"Invalid ir/feedback_volume payload: {payload!r}"
                            )
                            return
                        if not (0 <= vol <= 100):
                            logger.error(
                                f"ir/feedback_volume out of range: {vol}"
                            )
                            return
                        logger.info(f"MQTT ir/feedback_volume command: {vol}")
                        self.ir_feedback_volume_callback(vol)
                        self.publish_ir_state()

            elif command_type == "get":
                if action == "volume":
                    self.publish_volume()
                elif action == "status":
                    self._send_hello()
                    self.publish_mode()
                elif action == "activity":
                    self.publish_activity()
                elif action == "calibration":
                    self.publish_calibrations()
                elif action == "ir":
                    self.publish_ir_state()
                elif action == "eq":
                    self.publish_eq_state()

        except ValueError as e:
            logger.error(f"Error parsing command payload: {e}")
        except Exception as e:
            logger.error(f"Error handling command: {e}")

    def start(self):
        """Start the MQTT client (non-blocking — runs paho loop in background thread)"""
        if not self.should_run:
            return

        try:
            logger.info(f"Starting MQTT client for {self.display_name} -> {self.broker_host}:{self.broker_port}")
            self.client.connect(self.broker_host, self.broker_port, KEEPALIVE_S)
            self.client.loop_start()

            # Wait for connection (up to 10s)
            timeout = 10.0
            while not self.connected and timeout > 0 and self.should_run:
                time.sleep(0.1)
                timeout -= 0.1

            if self.connected:
                logger.info("MQTT client connected")
            else:
                logger.warning("MQTT broker not reachable — will retry in background")

        except Exception as e:
            logger.warning(f"MQTT connection failed (will retry): {e}")

    def stop(self):
        """Stop the MQTT client"""
        self.should_run = False
        if self.connected:
            logger.info("Stopping MQTT client")
            # A clean DISCONNECT discards the will, so say offline ourselves.
            # The loop must still be running to flush it.
            info = self.client.publish(self._online_topic(), "offline", retain=True)
            try:
                info.wait_for_publish(timeout=2)
            except Exception:
                pass
            self.client.disconnect()
            self.client.loop_stop()

    def _handle_ir_clear(self, command_id: str):
        """Handle set/clients/<id>/ir/clear/<command_id> — forget one mapping."""
        if self.ir_clear_callback is None:
            logger.warning(f"MQTT ir/clear/{command_id} but no callback wired")
            return
        logger.info(f"MQTT ir/clear command: {command_id}")
        self.ir_clear_callback(command_id)
        self.publish_ir_state()

    def _handle_ir_learn_start(self, payload: str):
        """
        Handle set/clients/<id>/ir/learn/start.

        Payload is JSON: {"command_id": "<id>", "timeout_s": <number>}.
        timeout_s defaults to 15 if omitted. The IRListener publishes
        the resulting lifecycle event ('started' / 'captured' / etc.)
        via the on_learn_event bridge in fauxnos_client.py.
        """
        if self.ir_learn_start_callback is None:
            logger.warning("MQTT ir/learn/start but no callback wired")
            return
        try:
            data = json.loads(payload or "{}")
        except Exception:
            logger.error(f"MQTT ir/learn/start: bad JSON payload: {payload!r}")
            return
        command_id = data.get("command_id")
        if not command_id:
            logger.error("MQTT ir/learn/start: missing command_id")
            return
        timeout_s = float(data.get("timeout_s", 15.0))
        logger.info(f"MQTT ir/learn/start: {command_id} (timeout {timeout_s:.0f}s)")
        ok = self.ir_learn_start_callback(command_id, timeout_s)
        if not ok:
            # IRListener already logs; surface to the bus too so the UI
            # can recover (e.g. another learn was in flight).
            self.client.publish(
                f"status/clients/{self.device_id}/ir/learn_event",
                json.dumps({
                    "event": "rejected",
                    "command_id": command_id,
                    "reason": "listener_busy_or_disabled",
                }),
            )

    def _handle_ir_learn_cancel(self):
        """Handle set/clients/<id>/ir/learn/cancel — abort any in-flight learn."""
        if self.ir_learn_cancel_callback is None:
            logger.warning("MQTT ir/learn/cancel but no callback wired")
            return
        logger.info("MQTT ir/learn/cancel")
        self.ir_learn_cancel_callback()

    def _send_hello(self):
        """Announce this device on MQTT"""
        hello_payload = {
            "id": self.device_id,
            "name": self.display_name,
            "sources": self.sources_list,
            "pa_calibrations": self._collect_calibrations(),
            "ir": self._collect_ir_state(),
            "eq": self._collect_eq_state(),
        }
        topic = f"status/clients/{self.device_id}/hello"
        self.client.publish(topic, json.dumps(hello_payload))
        logger.debug(f"Sent hello: {self.display_name}")

    def _collect_eq_state(self) -> dict:
        """Snapshot of EqController state for hello + status payloads."""
        if self.eq_getter is None:
            return {"enabled": False, "bands": {}}
        try:
            return self.eq_getter() or {"enabled": False, "bands": {}}
        except Exception as e:
            logger.error(f"eq_getter raised: {e}")
            return {"enabled": False, "bands": {}}

    def publish_eq_state(self):
        """Publish status/clients/<id>/eq — retained so a fresh UI sees current state."""
        if not self.connected:
            return
        payload = json.dumps(self._collect_eq_state())
        self.client.publish(
            f"status/clients/{self.device_id}/eq", payload, retain=True
        )

    def _collect_ir_state(self) -> dict:
        """Snapshot of the on-device ir block for hello + status payloads."""
        if self.ir_state_getter is None:
            return {'enabled': False, 'mappings': {}}
        try:
            ir = self.ir_state_getter() or {}
            return {
                'enabled': bool(ir.get('enabled', False)),
                'mappings': dict(ir.get('mappings') or {}),
            }
        except Exception as e:
            logger.error(f"ir_state_getter raised: {e}")
            return {'enabled': False, 'mappings': {}}

    def publish_ir_state(self):
        """Publish status/clients/<id>/ir/state with the full ir block."""
        if not self.connected:
            return
        payload = json.dumps(self._collect_ir_state())
        # Retain so a freshly-loaded UI sees current state immediately,
        # without waiting for the next ir/learn event to fire a publish.
        self.client.publish(
            f"status/clients/{self.device_id}/ir/state", payload, retain=True
        )

    def _collect_calibrations(self) -> dict:
        """Build a {source_id: calibration} map for hello + status payloads."""
        if self.calibration_getter is None:
            return {}
        out = {}
        for source_id in self.sources_list:
            try:
                out[source_id] = int(self.calibration_getter(source_id))
            except Exception:
                pass
        return out

    def publish_calibrations(self):
        """Publish status/clients/<id>/calibration/<source_id> for every source."""
        if not self.connected:
            return
        cals = self._collect_calibrations()
        for source_id, value in cals.items():
            # Retain so a fresh UI tab sees current values without
            # having to wait for the next user-driven calibration nudge.
            self.client.publish(
                f"status/clients/{self.device_id}/calibration/{source_id}",
                str(value),
                retain=True,
            )

    def update_mode(self, mode: str):
        """Update current mode and publish"""
        if self.current_mode != mode:
            self.current_mode = mode
            self.publish_mode()

    def update_volume(self, volume: int):
        """Update current volume and publish"""
        if self.current_volume != volume:
            self.current_volume = volume
            self.publish_volume()

    def update_activity(self, activity: str):
        """Update current activity and publish"""
        if activity in ("playing", "silent") and self.current_activity != activity:
            self.current_activity = activity
            self.publish_activity()

    # `retain=True` on the status/* topics: these are current-state
    # topics, not event topics, so a late-subscribing UI tab (page
    # reload, WiFi blip, install-wizard SSE handoff) must be able to
    # see the latest value immediately. Without retain, the UI's
    # `mqtt.modes[clientId]` stayed undefined after a reconnect, which
    # collapsed the airplay slider's `readOnly` check to false — the
    # iPhone-controlled slider became user-draggable mid-session (and
    # those drags then no-op'd because the source was still airplay).
    # Retained messages cost one broker-side store per topic; with a
    # tiny topic set (4 per client) the overhead is negligible.
    def publish_mode(self):
        if self.connected:
            self.client.publish(
                f"status/clients/{self.device_id}/mode",
                self.current_mode,
                retain=True,
            )

    def publish_volume(self):
        if self.connected:
            self.client.publish(
                f"status/clients/{self.device_id}/volume",
                str(self.current_volume),
                retain=True,
            )

    def publish_activity(self):
        if self.connected:
            self.client.publish(
                f"status/clients/{self.device_id}/activity",
                self.current_activity,
                retain=True,
            )

    def publish_all_status(self):
        if self.connected:
            self.publish_mode()
            self.publish_volume()
            self.publish_activity()
