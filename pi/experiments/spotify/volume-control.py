#!/usr/bin/env python3
"""
Librespot Volume Controller for Fauxnos
This script manages librespot connection, monitors volume events, 
and syncs them with ALSA softvol, reporting changes through MQTT.
"""

import subprocess
import threading
import re
import time
import paho.mqtt.client as mqtt
import json
import logging
import sys
from typing import Optional, Dict, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class LibrespotVolumeController:
    def __init__(
        self,
        mqtt_broker: str = "localhost",
        mqtt_port: int = 1883,
        mqtt_topic_prefix: str = "fauxnos",
        device_name: str = "Fauxnos",
        initial_volume: int = 50
    ):
        self.mqtt_broker = mqtt_broker
        self.mqtt_port = mqtt_port
        self.mqtt_topic_prefix = mqtt_topic_prefix
        self.device_name = device_name
        self.current_volume = initial_volume
        self.librespot_process: Optional[subprocess.Popen] = None
        self.should_run = True
        
        # MQTT client setup
        self.mqtt_client = mqtt.Client()
        self.mqtt_client.on_connect = self._on_mqtt_connect
        self.mqtt_client.on_disconnect = self._on_mqtt_disconnect
        
        # Set initial volume
        self._set_alsa_volume(initial_volume)
    
    def _on_mqtt_connect(self, client, userdata, flags, rc):
        """Handle MQTT connection event"""
        logger.info(f"Connected to MQTT broker with result code {rc}")
        # Subscribe to volume control commands
        client.subscribe(f"{self.mqtt_topic_prefix}/volume/set")
    
    def _on_mqtt_disconnect(self, client, userdata, rc):
        """Handle MQTT disconnection event"""
        logger.warning(f"Disconnected from MQTT broker with result code {rc}")
    
    def _set_alsa_volume(self, volume: int) -> bool:
        """Set ALSA softvol volume"""
        try:
            # Convert to percentage for amixer
            percentage = max(0, min(100, volume))
            cmd = f"amixer sset 'Librespot' {percentage}%"
            subprocess.run(cmd, shell=True, check=True, capture_output=True)
            logger.info(f"Set ALSA volume to {percentage}%")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to set ALSA volume: {e}")
            return False
    
    def _publish_volume_change(self, volume: int, source: str = "system"):
        """Publish volume change to MQTT"""
        message = {
            "volume": volume,
            "source": source,
            "device": self.device_name,
            "timestamp": int(time.time())
        }
        
        topic = f"{self.mqtt_topic_prefix}/volume/status"
        self.mqtt_client.publish(topic, json.dumps(message))
        logger.info(f"Published volume change: {volume}% from {source}")
    
    def _monitor_librespot_output(self):
        """Monitor librespot stderr for volume events"""
        if not self.librespot_process:
            return
            
        volume_pattern = re.compile(r'volume.*?(\d+)', re.IGNORECASE)
        event_pattern = re.compile(r'event.*?volume|volume.*?change', re.IGNORECASE)
        
        for line in iter(self.librespot_process.stderr.readline, b''):
            if not self.should_run:
                break
                
            try:
                line_str = line.decode('utf-8').strip()
                
                # Look for volume events
                if event_pattern.search(line_str):
                    logger.debug(f"Librespot event: {line_str}")
                    
                    # Extract volume value
                    volume_match = volume_pattern.search(line_str)
                    if volume_match:
                        volume = int(volume_match.group(1))
                        
                        # Convert Spotify's 0-65535 scale to 0-100%
                        volume_percent = int((volume / 65535) * 100)
                        
                        if volume_percent != self.current_volume:
                            self.current_volume = volume_percent
                            self._set_alsa_volume(volume_percent)
                            self._publish_volume_change(volume_percent, "spotify")
                
            except Exception as e:
                logger.error(f"Error processing librespot output: {e}")
    
    def start_librespot(self):
        """Start librespot process with appropriate parameters"""
        cmd = [
            "librespot",
            "--name", self.device_name,
            "--device", "librespot",  # Use the ALSA PCM device
            "--ignore-volume",  # Custom patch feature
            "--initial-volume", str(self.current_volume),
            "--verbose"  # Enable verbose output for event monitoring
        ]
        
        try:
            self.librespot_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,
                universal_newlines=False
            )
            logger.info(f"Started librespot with device name: {self.device_name}")
            
            # Start monitor thread
            monitor_thread = threading.Thread(
                target=self._monitor_librespot_output,
                daemon=True
            )
            monitor_thread.start()
            
        except Exception as e:
            logger.error(f"Failed to start librespot: {e}")
            raise
    
    def connect_mqtt(self):
        """Connect to MQTT broker"""
        try:
            # self.connect_mqtt()
            # self.mqtt_client.loop_start()
            pass
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
            raise
    
    def run(self):
        """Main run loop"""
        try:
            # Connect to MQTT
            # self.connect_mqtt()
            
            # Start librespot
            self.start_librespot()
            
            # Publish initial status
            self._publish_volume_change(self.current_volume, "initial")
            
            # Keep running until interrupted
            while self.should_run:
                time.sleep(1)
                
                # Check if librespot is still running
                if self.librespot_process and self.librespot_process.poll() is not None:
                    logger.error("Librespot process died unexpectedly")
                    # Attempt to restart
                    time.sleep(5)
                    self.start_librespot()
        
        except KeyboardInterrupt:
            logger.info("Received interrupt signal")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Clean up resources"""
        self.should_run = False
        
        if self.librespot_process:
            self.librespot_process.terminate()
            try:
                self.librespot_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.librespot_process.kill()
        
        # self.mqtt_client.loop_stop()
        # self.mqtt_client.disconnect()
        logger.info("Cleanup completed")

def main():
    """Main entry point"""
    # Configuration can be loaded from environment variables or config file
    controller = LibrespotVolumeController(
        mqtt_broker="192.168.4.112",
        mqtt_port=1883,
        mqtt_topic_prefix="fauxnos",
        device_name="Fauxnos Living Room",
        initial_volume=50
    )
    
    controller.run()

if __name__ == "__main__":
    main()
