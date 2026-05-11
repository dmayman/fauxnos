#!/usr/bin/env python3
"""
MQTT Client Module

Handles MQTT communication for Fauxnos audio clients.
Publishes status updates and listens for control commands.

Topic schema:
  Control (UI → client):
    set/clients/<deviceId>/volume     payload: "75"
    set/clients/<deviceId>/mode       payload: "spotify"

  Status (client → UI):
    status/clients/<deviceId>/volume  payload: "75"
    status/clients/<deviceId>/mode    payload: "spotify"
    status/clients/<deviceId>/activity payload: "playing"|"silent"
    status/clients/<deviceId>/hello   payload: {"id","name","sources"}

  Discovery:
    get/clients/<deviceId>/volume     → client publishes volume
    get/clients/<deviceId>/status     → client publishes hello + mode
    get/clients/all/status            → all clients publish hello
"""

import json
import logging
import time
from typing import Callable, Optional, Dict, List

import paho.mqtt.client as mqtt

from .config_manager import ConfigManager

logger = logging.getLogger(__name__)


class MQTTClient:
    def __init__(self, config_manager: ConfigManager,
                 volume_callback: Callable[[int], bool],
                 mode_callback: Callable[[str], bool],
                 calibration_callback: Optional[Callable[[str, int], bool]] = None,
                 calibration_getter: Optional[Callable[[str], int]] = None,
                 ir_enable_callback: Optional[Callable[[bool], None]] = None,
                 ir_clear_callback: Optional[Callable[[str], None]] = None,
                 ir_state_getter: Optional[Callable[[], dict]] = None,
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
                mapping. Wired to IRListener.clear_command. Learning is a
                separate topic family (phase 4).
            ir_state_getter: () → {"enabled","mappings"} dict. Used to
                populate hello + status/ir/state payloads. Wired to
                IRListener.state_manager.get_ir() in the daemon.
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
        self.calibration_callback = calibration_callback
        self.calibration_getter = calibration_getter
        self.ir_enable_callback = ir_enable_callback
        self.ir_clear_callback = ir_clear_callback
        self.ir_state_getter = ir_state_getter

        # MQTT client setup
        self.client = mqtt.Client(client_id=f"fauxnos-{self.device_id}")
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

        self.connected = False
        self.should_run = True

        # Current state tracking
        self.current_mode = "idle"
        self.current_volume = 0
        self.current_activity = "silent"

        # Build sources list from config
        self.sources_list = self._determine_sources()

    def _determine_sources(self) -> List[str]:
        """Get list of source IDs from config"""
        return list(self.config_manager.sources.keys())

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected = True
            logger.info(f"Connected to MQTT broker at {self.broker_host}:{self.broker_port}")
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
            # IR (hardware remote): enabled toggle + per-command clear.
            # Learning commands (start/cancel) come in phase 4 and use
            # additional sub-topics under .../ir/learn/+.
            f"set/clients/{self.device_id}/ir/enabled",
            f"set/clients/{self.device_id}/ir/clear/+",
            f"get/clients/{self.device_id}/volume",
            f"get/clients/{self.device_id}/status",
            f"get/clients/{self.device_id}/activity",
            f"get/clients/{self.device_id}/calibration",
            f"get/clients/{self.device_id}/ir",
            "get/clients/all/status",
        ]
        for topic in topics:
            self.client.subscribe(topic)
            logger.debug(f"Subscribed to: {topic}")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode('utf-8')
        logger.debug(f"MQTT message: {topic} -> {payload}")

        # Broadcast discovery
        if topic == "get/clients/all/status":
            self._send_hello()
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

            # 6-part topics (extra trailing identifier) are handled
            # before the generic _handle_command interface, which only
            # carries a single sub_action slot.
            if (command_type == "set" and action == "ir"
                    and sub_action == "clear" and tail):
                self._handle_ir_clear(tail)
                return

            self._handle_command(command_type, action, payload, sub_action)

    def _handle_command(
        self,
        command_type: str,
        action: str,
        payload: str,
        sub_action: Optional[str] = None,
    ):
        try:
            if command_type == "set":
                if action == "volume":
                    volume = int(payload)
                    if 0 <= volume <= 100:
                        logger.info(f"MQTT volume command: {volume}%")
                        self.volume_callback(volume)
                        self.update_volume(volume)
                    else:
                        logger.error(f"Invalid volume value: {volume}")

                elif action == "mode":
                    if payload in self.sources_list:
                        logger.info(f"MQTT mode command: {payload}")
                        self.mode_callback(payload)
                        self.update_mode(payload)
                    else:
                        logger.error(f"Invalid mode: {payload}. Available: {self.sources_list}")

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
                        if not (0 <= value <= 100):
                            logger.error(f"Calibration value out of range: {value}")
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
            self.client.connect(self.broker_host, self.broker_port, 60)
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
            self.client.loop_stop()
            self.client.disconnect()

    def _handle_ir_clear(self, command_id: str):
        """Handle set/clients/<id>/ir/clear/<command_id> — forget one mapping."""
        if self.ir_clear_callback is None:
            logger.warning(f"MQTT ir/clear/{command_id} but no callback wired")
            return
        logger.info(f"MQTT ir/clear command: {command_id}")
        self.ir_clear_callback(command_id)
        self.publish_ir_state()

    def _send_hello(self):
        """Announce this device on MQTT"""
        hello_payload = {
            "id": self.device_id,
            "name": self.display_name,
            "sources": self.sources_list,
            "pa_calibrations": self._collect_calibrations(),
            "ir": self._collect_ir_state(),
        }
        topic = f"status/clients/{self.device_id}/hello"
        self.client.publish(topic, json.dumps(hello_payload))
        logger.debug(f"Sent hello: {self.display_name}")

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
        self.client.publish(f"status/clients/{self.device_id}/ir/state", payload)

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
            self.client.publish(
                f"status/clients/{self.device_id}/calibration/{source_id}",
                str(value),
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

    def publish_mode(self):
        if self.connected:
            self.client.publish(f"status/clients/{self.device_id}/mode", self.current_mode)

    def publish_volume(self):
        if self.connected:
            self.client.publish(f"status/clients/{self.device_id}/volume", str(self.current_volume))

    def publish_activity(self):
        if self.connected:
            self.client.publish(f"status/clients/{self.device_id}/activity", self.current_activity)

    def publish_all_status(self):
        if self.connected:
            self.publish_mode()
            self.publish_volume()
            self.publish_activity()
