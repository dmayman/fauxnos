#!/usr/bin/env python3
"""
Fauxnos MQTT Server
-------------------
Central MQTT server for controlling and monitoring Fauxnos audio clients.
Implements the MQTT protocol defined in README.md for device communication.
"""

import json
import logging
import time
from datetime import datetime
from typing import Dict, Any

import paho.mqtt.client as mqtt
from modules.snapcast_controller import SnapcastController


class FauxnosServer:
    def __init__(self, broker_host="localhost", broker_port=1883, snapcast_host="localhost", snapcast_port=1705):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.client = mqtt.Client()
        self.connected = False
        
        # Store client states
        self.clients: Dict[str, Dict[str, Any]] = {}
        
        # Snapcast controller
        self.snapcast = SnapcastController(snapcast_host, snapcast_port)
        
        # Set up MQTT callbacks
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        
        # Set up logging
        self._setup_logging()
        
    def _setup_logging(self):
        """Set up logging with console handler"""
        self.logger = logging.getLogger('FauxnosServer')
        self.logger.setLevel(logging.INFO)
        
        # Console handler
        console_handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        
    def _on_connect(self, client, userdata, flags, rc):
        """Callback for when the client receives a CONNACK response from the server"""
        if rc == 0:
            self.connected = True
            self.logger.info(f"Connected to MQTT broker at {self.broker_host}:{self.broker_port}")
            
            # Subscribe to all relevant topics
            self._subscribe_to_topics()
        else:
            self.logger.error(f"Failed to connect to MQTT broker, return code {rc}")
            
    def _on_disconnect(self, client, userdata, rc):
        """Callback for when the client disconnects from the server"""
        self.connected = False
        if rc != 0:
            self.logger.warning("Unexpected disconnection from MQTT broker")
        else:
            self.logger.info("Disconnected from MQTT broker")
            
    def _subscribe_to_topics(self):
        """Subscribe to all client status topics"""
        topics = [
            "status/clients/+/hello",
            "status/clients/+/mode", 
            "status/clients/+/volume",
            "status/clients/+/activity"
        ]
        
        for topic in topics:
            self.client.subscribe(topic)
            self.logger.info(f"Subscribed to topic: {topic}")
            
    def _on_message(self, client, userdata, msg):
        """Handle incoming MQTT messages"""
        topic = msg.topic
        payload = msg.payload.decode('utf-8')
        
        self.logger.info(f"Received: {topic} -> {payload}")
        
        # Parse topic to extract device ID and message type
        topic_parts = topic.split('/')
        if len(topic_parts) >= 4 and topic_parts[0] == "status" and topic_parts[1] == "clients":
            device_id = topic_parts[2]
            message_type = topic_parts[3]
            
            self._handle_status_message(device_id, message_type, payload)
        else:
            self.logger.warning(f"Unknown topic format: {topic}")
            
    def _handle_status_message(self, device_id: str, message_type: str, payload: str):
        """Handle status messages from clients"""
        # Ensure client exists in our tracking
        if device_id not in self.clients:
            self.clients[device_id] = {
                "last_seen": datetime.now(),
                "online": True
            }
        
        # Update last seen time
        self.clients[device_id]["last_seen"] = datetime.now()
        self.clients[device_id]["online"] = True
        
        try:
            if message_type == "hello":
                # Parse hello message JSON
                hello_data = json.loads(payload)
                self.clients[device_id].update({
                    "id": hello_data.get("id", device_id),
                    "name": hello_data.get("name", device_id),
                    "sources": hello_data.get("sources", [])
                })
                self.logger.info(f"Device {device_id} ({hello_data.get('name', device_id)}) announced itself")
                
            elif message_type == "mode":
                self.clients[device_id]["mode"] = payload
                device_name = self.clients[device_id].get("name", device_id)
                self.logger.info(f"{device_name} mode changed to: {payload}")
                
            elif message_type == "volume":
                try:
                    volume = int(payload)
                    self.clients[device_id]["volume"] = volume
                    device_name = self.clients[device_id].get("name", device_id)
                    self.logger.info(f"{device_name} volume changed to: {volume}%")
                except ValueError:
                    self.logger.error(f"Invalid volume value from {device_id}: {payload}")
                    
            elif message_type == "activity":
                self.clients[device_id]["activity"] = payload
                device_name = self.clients[device_id].get("name", device_id)
                if payload == "playing":
                    self.logger.info(f"{device_name} is now playing")
                else:
                    self.logger.info(f"{device_name} is now silent")
                    
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse JSON from {device_id}: {e}")
        except Exception as e:
            self.logger.error(f"Error handling message from {device_id}: {e}")
            
    def start(self):
        """Start the MQTT server"""
        try:
            self.logger.info("Starting Fauxnos MQTT Server...")
            self.logger.info(f"Connecting to MQTT broker at {self.broker_host}:{self.broker_port}")
            
            self.client.connect(self.broker_host, self.broker_port, 60)
            self.client.loop_start()
            
            # Wait for connection
            timeout = 10
            while not self.connected and timeout > 0:
                time.sleep(0.1)
                timeout -= 0.1
                
            if not self.connected:
                raise Exception("Failed to connect to MQTT broker within timeout")
                
            self.logger.info("Fauxnos MQTT Server started successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to start MQTT server: {e}")
            raise
            
    def stop(self):
        """Stop the MQTT server"""
        self.logger.info("Stopping Fauxnos MQTT Server...")
        self.client.loop_stop()
        self.client.disconnect()
        
    def set_client_volume(self, device_id: str, volume: int) -> bool:
        """Set volume for a specific client"""
        if not self.connected:
            self.logger.error("Not connected to MQTT broker")
            return False
            
        if not (0 <= volume <= 100):
            self.logger.error(f"Invalid volume value: {volume}. Must be 0-100")
            return False
            
        topic = f"set/clients/{device_id}/volume"
        self.client.publish(topic, str(volume))
        device_name = self.clients.get(device_id, {}).get("name", device_id)
        self.logger.info(f"Sent volume command to {device_name}: {volume}%")
        return True
        
    def set_client_mode(self, device_id: str, mode: str) -> bool:
        """Set mode for a specific client"""
        if not self.connected:
            self.logger.error("Not connected to MQTT broker")
            return False
            
        # Check if device exists and get its sources
        if device_id not in self.clients:
            self.logger.error(f"Device {device_id} not found")
            return False
            
        device_sources = self.clients[device_id].get("sources", [])
        if mode not in device_sources:
            self.logger.error(f"Invalid mode: {mode}. Device {device_id} supports: {device_sources}")
            return False
            
        topic = f"set/clients/{device_id}/mode"
        self.client.publish(topic, mode)
        device_name = self.clients.get(device_id, {}).get("name", device_id)
        self.logger.info(f"Sent mode command to {device_name}: {mode}")
        return True
        
    def get_client_status(self, device_id: str) -> bool:
        """Request status from a specific client"""
        if not self.connected:
            self.logger.error("Not connected to MQTT broker")
            return False
            
        topic = f"get/clients/{device_id}/status"
        self.client.publish(topic, "{}")
        device_name = self.clients.get(device_id, {}).get("name", device_id)
        self.logger.info(f"Requested status from {device_name}")
        return True
        
    def get_client_volume(self, device_id: str) -> bool:
        """Request volume from a specific client"""
        if not self.connected:
            self.logger.error("Not connected to MQTT broker")
            return False
            
        topic = f"get/clients/{device_id}/volume"
        self.client.publish(topic, "{}")
        device_name = self.clients.get(device_id, {}).get("name", device_id)
        self.logger.info(f"Requested volume from {device_name}")
        return True
        
    def get_client_activity(self, device_id: str) -> bool:
        """Request activity status from a specific client"""
        if not self.connected:
            self.logger.error("Not connected to MQTT broker")
            return False
            
        topic = f"get/clients/{device_id}/activity"
        self.client.publish(topic, "{}")
        device_name = self.clients.get(device_id, {}).get("name", device_id)
        self.logger.info(f"Requested activity from {device_name}")
        return True
        
    def list_clients(self):
        """List all known clients and their status"""
        if not self.clients:
            self.logger.info("No clients connected")
            return
            
        self.logger.info("Connected clients:")
        for device_id, info in self.clients.items():
            name = info.get("name", device_id)
            mode = info.get("mode", "unknown")
            volume = info.get("volume", "unknown")
            activity = info.get("activity", "unknown")
            sources = info.get("sources", [])
            last_seen = info.get("last_seen", "never")
            
            self.logger.info(f"  {name} ({device_id})")
            self.logger.info(f"    Mode: {mode} | Volume: {volume}% | Activity: {activity}")
            self.logger.info(f"    Sources: {', '.join(sources)}")
            self.logger.info(f"    Last seen: {last_seen}")


def parse_command(command_str: str):
    """Parse a command string into command and arguments"""
    parts = command_str.strip().split()
    if not parts:
        return None, []
        
    command = parts[0].lower()
    args = parts[1:]
    
    return command, args


def main():
    """Main CLI interface for the Fauxnos MQTT Server"""
    # You can customize broker settings here
    BROKER_HOST = "localhost"
    BROKER_PORT = 1883
    
    server = FauxnosServer(BROKER_HOST, BROKER_PORT)
    
    try:
        server.start()
        
        print("\nFauxnos MQTT Server CLI")
        print("=======================")
        print("Type 'help' for available commands")
        print()
        
        while True:
            try:
                command_str = input("> ").strip()
                if not command_str:
                    continue
                    
                command, args = parse_command(command_str)
                
                if command == 'help':
                    print("\nAvailable commands:")
                    print("  help                           - Show this help")
                    print("  list                           - List all connected clients")
                    print("  set <deviceId> volume <0-100>  - Set client volume")
                    print("  set <deviceId> mode <mode>     - Set client mode (snapcast/librespot/analog)")
                    print("  get <deviceId> status          - Request client status")
                    print("  get <deviceId> volume          - Request client volume")
                    print("  get <deviceId> activity        - Request client activity")
                    print("  volume <0-100>                 - Set Snapcast spotify group master volume")
                    print("  volume <client> <0-100>        - Set volume for specific client")
                    print("  volume                         - Get current spotify group master volume")
                    print("  clients                        - List all Snapcast clients")
                    print("  snapcast groups                - List Snapcast groups and clients")
                    print("  quit                           - Exit the server")
                    print()
                    
                elif command == 'list':
                    server.list_clients()
                    
                elif command == 'clients':
                    clients = server.snapcast.list_clients()
                    if not clients:
                        print("No Snapcast clients found")
                    else:
                        print("\nSnapcast Clients:")
                        for client in clients:
                            name = client['name']
                            group = client['group']
                            volume = client['volume']
                            connected = "✓" if client['connected'] else "✗"
                            muted = " (muted)" if client['muted'] else ""
                            print(f"  {name} - Group: {group} | Volume: {volume}%{muted} | Connected: {connected}")
                        print()
                    
                elif command == 'set':
                    if len(args) < 3:
                        print("Usage: set <deviceId> volume <0-100> | set <deviceId> mode <mode>")
                        continue
                        
                    device_id = args[0]
                    action = args[1].lower()
                    value = args[2]
                    
                    if action == 'volume':
                        try:
                            volume = int(value)
                            server.set_client_volume(device_id, volume)
                        except ValueError:
                            print(f"Invalid volume: {value}. Must be an integer 0-100")
                    elif action == 'mode':
                        server.set_client_mode(device_id, value)
                    else:
                        print(f"Unknown action: {action}. Use 'volume' or 'mode'")
                        
                elif command == 'get':
                    if len(args) < 2:
                        print("Usage: get <deviceId> status | get <deviceId> volume | get <deviceId> activity")
                        continue
                        
                    device_id = args[0]
                    info_type = args[1].lower()
                    
                    if info_type == 'status':
                        server.get_client_status(device_id)
                    elif info_type == 'volume':
                        server.get_client_volume(device_id)
                    elif info_type == 'activity':
                        server.get_client_activity(device_id)
                    else:
                        print(f"Unknown info type: {info_type}. Use 'status', 'volume', or 'activity'")
                        
                elif command == 'volume':
                    # No arguments - get current master volume
                    if len(args) == 0:
                        master_volume = server.snapcast.get_group_master_volume("spotify")
                        if master_volume is not None:
                            print(f"Spotify group master volume: {master_volume:.1f}%")
                        else:
                            print("Could not get spotify group master volume (group not found or no clients)")
                        continue
                        
                    # Check if it's a client-specific volume command
                    if len(args) == 2:
                        client_name = args[0]
                        try:
                            volume = int(args[1])
                            
                            # Find client by name
                            client_id = server.snapcast.find_client_by_name(client_name)
                            if not client_id:
                                print(f"Client '{client_name}' not found. Use 'clients' to see available clients.")
                                continue
                                
                            if server.snapcast.set_client_volume(client_id, volume):
                                print(f"Set volume to {volume}% for client '{client_name}'")
                            else:
                                print(f"Failed to set volume for client '{client_name}'")
                        except ValueError:
                            print(f"Invalid volume: {args[1]}. Must be an integer 0-100")
                    
                    # Single argument - group volume command
                    elif len(args) == 1:
                        try:
                            volume = int(args[0])
                            
                            # Get current master volume for comparison
                            current_master = server.snapcast.get_group_master_volume("spotify")
                            if current_master is not None:
                                print(f"Current master volume: {current_master:.1f}%")
                            
                            # Use proportional scaling (snapweb-style)
                            if server.snapcast.set_group_volume_direct("spotify", volume):
                                print(f"✓ Set spotify group master volume to {volume}%")
                            else:
                                print(f"✗ Failed to set Snapcast master volume")
                        except ValueError:
                            print(f"Invalid volume: {args[0]}. Must be an integer 0-100")
                    else:
                        print("Usage: volume | volume <0-100> | volume <client> <0-100>")
                        
                elif command == 'snapcast':
                    if len(args) < 1:
                        print("Usage: snapcast groups")
                        continue
                        
                    if args[0] == 'groups':
                        groups = server.snapcast.list_groups()
                        if not groups:
                            print("No Snapcast groups found")
                        else:
                            print("\nSnapcast Groups:")
                            for group in groups:
                                stream_id = group['stream_id']
                                muted = " (MUTED)" if group['muted'] else ""
                                
                                # Calculate and show master volume
                                master_volume = server.snapcast.get_group_master_volume(stream_id)
                                master_vol_str = f" | Master: {master_volume:.1f}%" if master_volume is not None else ""
                                
                                print(f"  Group: {stream_id}{muted}{master_vol_str}")
                                
                                for client in group['clients']:
                                    name = client['name']
                                    volume = client['volume']
                                    client_muted = " (muted)" if client['muted'] else ""
                                    print(f"    - {name}: {volume}%{client_muted}")
                                print()
                    else:
                        print(f"Unknown snapcast command: {args[0]}. Use 'groups'")
                        
                elif command == 'quit':
                    break
                    
                else:
                    print(f"Unknown command: {command}. Type 'help' for available commands")
                    
            except KeyboardInterrupt:
                print("\nShutting down...")
                break
            except Exception as e:
                print(f"Error processing command: {e}")
                
    except Exception as e:
        print(f"Failed to start server: {e}")
    finally:
        server.stop()
        print("Goodbye!")


if __name__ == "__main__":
    main()