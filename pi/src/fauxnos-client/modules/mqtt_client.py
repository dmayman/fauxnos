#!/usr/bin/env python3
"""
MQTT Client Module
------------------
Handles MQTT communication for Fauxnos audio clients.
Publishes status updates and listens for control commands.
"""

import json
import logging
import threading
import time
from typing import Callable, Optional, Dict, Any

import paho.mqtt.client as mqtt

logger = logging.getLogger('AudioController')


class MQTTClient:
    def __init__(self, device_config: Dict[str, Any], 
                 volume_callback: Callable[[int], None],
                 mode_callback: Callable[[str], None],
                 broker_host: str = "localhost", 
                 broker_port: int = 1883):
        """
        Initialize MQTT client
        
        Args:
            device_config: Device configuration with name, display_name, sources etc.
            volume_callback: Function to call when volume command received
            mode_callback: Function to call when mode change command received  
            broker_host: MQTT broker hostname
            broker_port: MQTT broker port
        """
        self.device_config = device_config
        self.device_id = device_config.get("name", "unknown")
        self.display_name = device_config.get("display_name", self.device_id)
        
        self.broker_host = broker_host
        self.broker_port = broker_port
        
        # Callbacks for handling commands
        self.volume_callback = volume_callback
        self.mode_callback = mode_callback
        
        # MQTT client setup
        self.client = mqtt.Client()
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        
        self.connected = False
        self.should_run = True
        
        # Current state tracking
        self.current_mode = "idle"
        self.current_volume = 0
        self.current_activity = "silent"
        
        # Determine sources from configuration
        self.sources_list = self._determine_sources()
        
    def _determine_sources(self) -> list:
        """Determine device sources from source configuration"""
        sources_list = []
        sources = self.device_config.get("sources", [])
        
        for source in sources:
            if source.get("type") == "internal":
                source_id = source.get("id", "")
                if source_id and source_id not in sources_list:
                    sources_list.append(source_id)
                    
        return sources_list
        
    def _on_connect(self, client, userdata, flags, rc):
        """Callback for when the client receives a CONNACK response"""
        if rc == 0:
            self.connected = True
            logger.info(f"📡 Connected to MQTT broker at {self.broker_host}:{self.broker_port}")
            
            # Subscribe to control topics for this device
            self._subscribe_to_control_topics()
            
            # Send hello message
            self._send_hello()
            
        else:
            logger.error(f"📡 Failed to connect to MQTT broker, return code {rc}")
            
    def _on_disconnect(self, client, userdata, rc):
        """Callback for when the client disconnects"""
        self.connected = False
        if rc != 0:
            logger.warning("📡 Unexpected disconnection from MQTT broker")
        else:
            logger.info("📡 Disconnected from MQTT broker")
            
    def _subscribe_to_control_topics(self):
        """Subscribe to control topics for this device"""
        topics = [
            f"set/clients/{self.device_id}/volume",
            f"set/clients/{self.device_id}/mode",
            f"get/clients/{self.device_id}/volume", 
            f"get/clients/{self.device_id}/status",
            f"get/clients/{self.device_id}/activity",
            "get/clients/all/status"  # Listen for broadcast discovery requests
        ]
        
        for topic in topics:
            self.client.subscribe(topic)
            logger.debug(f"📡 Subscribed to: {topic}")
            
    def _on_message(self, client, userdata, msg):
        """Handle incoming MQTT control messages"""
        topic = msg.topic
        payload = msg.payload.decode('utf-8')
        
        logger.info(f"📨 Received command: {topic} -> {payload}")
        
        # Handle broadcast discovery requests
        if topic == "get/clients/all/status":
            logger.info("📡 Received broadcast discovery request, sending hello message")
            self._send_hello()
            return
        
        # Parse topic to extract command type
        topic_parts = topic.split('/')
        if len(topic_parts) >= 4:
            command_type = topic_parts[0]  # 'set' or 'get'
            device_id = topic_parts[2]
            action = topic_parts[3]
            
            if device_id == self.device_id:
                self._handle_command(command_type, action, payload)
            else:
                logger.warning(f"📡 Received command for wrong device: {device_id}")
        else:
            logger.warning(f"📡 Invalid topic format: {topic}")
            
    def _handle_command(self, command_type: str, action: str, payload: str):
        """Handle MQTT commands"""
        try:
            if command_type == "set":
                if action == "volume":
                    volume = int(payload)
                    if 0 <= volume <= 100:
                        logger.info(f"🔊 MQTT volume command: {volume}%")
                        self.volume_callback(volume)
                        # Update our state and publish confirmation
                        self.update_volume(volume)
                    else:
                        logger.error(f"📡 Invalid volume value: {volume}")
                        
                elif action == "mode":
                    # Validate that the requested mode exists in our sources
                    if payload in self.sources_list:
                        logger.info(f"🎵 MQTT mode command: {payload}")
                        # Use the source ID directly
                        self.mode_callback(payload)
                        # Update our state and publish confirmation
                        self.update_mode(payload)
                    else:
                        logger.error(f"📡 Invalid mode: {payload}. Available modes: {self.sources_list}")
                        
            elif command_type == "get":
                if action == "volume":
                    self.publish_volume()
                elif action == "status":
                    # Send hello message for device discovery, then status
                    self._send_hello()
                    self.publish_mode()
                elif action == "activity":
                    self.publish_activity()
                    
        except ValueError as e:
            logger.error(f"📡 Error parsing command payload: {e}")
        except Exception as e:
            logger.error(f"📡 Error handling command: {e}")
            
    def start(self):
        """Start the MQTT client"""
        if not self.should_run:
            return
            
        try:
            logger.info(f"📡 Starting MQTT client for device: {self.display_name}")
            self.client.connect(self.broker_host, self.broker_port, 60)
            self.client.loop_start()
            
            # Wait for connection
            timeout = 10
            while not self.connected and timeout > 0 and self.should_run:
                time.sleep(0.1)
                timeout -= 0.1
                
            if self.connected:
                logger.info("📡 MQTT client started successfully")
            else:
                logger.error("📡 Failed to connect to MQTT broker within timeout")
                
        except Exception as e:
            logger.error(f"📡 Failed to start MQTT client: {e}")
            
    def stop(self):
        """Stop the MQTT client"""
        self.should_run = False
        if self.connected:
            logger.info("📡 Stopping MQTT client...")
            self.client.loop_stop()
            self.client.disconnect()
            
    def _send_hello(self):
        """Send hello message announcing this device"""
        hello_payload = {
            "id": self.device_id,
            "name": self.display_name,
            "sources": self.sources_list
        }
        
        topic = f"status/clients/{self.device_id}/hello"
        self.client.publish(topic, json.dumps(hello_payload))
        logger.info(f"📡 Sent hello message: {self.display_name} with sources {self.sources_list}")
        
    def update_mode(self, mode: str):
        """Update current mode and publish to MQTT"""
        if self.current_mode != mode:
            self.current_mode = mode
            self.publish_mode()
            
    def update_volume(self, volume: int):
        """Update current volume and publish to MQTT"""
        if self.current_volume != volume:
            self.current_volume = volume
            self.publish_volume()
            
    def update_activity(self, activity: str):
        """Update current activity and publish to MQTT"""
        # activity should be "playing" or "silent"
        if activity not in ["playing", "silent"]:
            logger.warning(f"📡 Invalid activity state: {activity}")
            return
            
        if self.current_activity != activity:
            self.current_activity = activity
            self.publish_activity()
            
    def publish_mode(self):
        """Publish current mode to MQTT"""
        if self.connected:
            topic = f"status/clients/{self.device_id}/mode"
            self.client.publish(topic, self.current_mode)
            logger.debug(f"📡 Published mode: {self.current_mode}")
            
    def publish_volume(self):
        """Publish current volume to MQTT"""
        if self.connected:
            topic = f"status/clients/{self.device_id}/volume"
            self.client.publish(topic, str(self.current_volume))
            logger.debug(f"📡 Published volume: {self.current_volume}%")
            
    def publish_activity(self):
        """Publish current activity to MQTT"""
        if self.connected:
            topic = f"status/clients/{self.device_id}/activity"
            self.client.publish(topic, self.current_activity)
            logger.debug(f"📡 Published activity: {self.current_activity}")
            
    def publish_all_status(self):
        """Publish all current status information"""
        if self.connected:
            self.publish_mode()
            self.publish_volume()
            self.publish_activity()
            logger.info(f"📡 Published all status for {self.display_name}")