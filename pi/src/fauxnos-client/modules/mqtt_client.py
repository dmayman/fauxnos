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
                 broker_host: Optional[str] = None,
                 broker_port: int = 1883):
        """
        Initialize MQTT client

        Args:
            config_manager: ConfigManager instance with device/source info
            volume_callback: Called on volume command → SourceManager.set_volume()
            mode_callback: Called on mode command → SourceManager.switch_source()
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
            f"get/clients/{self.device_id}/volume",
            f"get/clients/{self.device_id}/status",
            f"get/clients/{self.device_id}/activity",
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

        # Parse topic: {command_type}/clients/{device_id}/{action}
        parts = topic.split('/')
        if len(parts) >= 4:
            command_type, _, device_id, action = parts[0], parts[1], parts[2], parts[3]
            if device_id == self.device_id:
                self._handle_command(command_type, action, payload)

    def _handle_command(self, command_type: str, action: str, payload: str):
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

            elif command_type == "get":
                if action == "volume":
                    self.publish_volume()
                elif action == "status":
                    self._send_hello()
                    self.publish_mode()
                elif action == "activity":
                    self.publish_activity()

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

    def _send_hello(self):
        """Announce this device on MQTT"""
        hello_payload = {
            "id": self.device_id,
            "name": self.display_name,
            "sources": self.sources_list
        }
        topic = f"status/clients/{self.device_id}/hello"
        self.client.publish(topic, json.dumps(hello_payload))
        logger.debug(f"Sent hello: {self.display_name}")

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
