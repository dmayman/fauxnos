#!/usr/bin/env python3
"""
Snapcast JSON-RPC Control
-------------------------
Handles Snapcast client volume control via JSON-RPC API.
"""

import json
import socket
import logging
import threading
import time

logger = logging.getLogger('AudioController')

class SnapcastController:
    def __init__(self, host='localhost', port=1705):
        self.host = host
        self.port = port
        self.client_id = None
        self._id_counter = 1
        
    def _get_next_id(self):
        """Get next JSON-RPC request ID"""
        current_id = self._id_counter
        self._id_counter += 1
        return current_id

    def _send_request(self, method, params=None):
        """Send JSON-RPC request to Snapcast server"""
        try:
            # Create JSON-RPC request
            request = {
                "jsonrpc": "2.0",
                "method": method,
                "id": self._get_next_id()
            }
            if params:
                request["params"] = params
            
            # Connect to Snapcast server
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)  # 5 second timeout
            sock.connect((self.host, self.port))
            
            # Send request
            request_json = json.dumps(request) + '\n'
            sock.send(request_json.encode('utf-8'))
            
            # Receive response
            response_data = b''
            while True:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                response_data += chunk
                if b'\n' in response_data:
                    break
            
            sock.close()
            
            # Parse response
            response_text = response_data.decode('utf-8').strip()
            if response_text:
                response = json.loads(response_text)
                if 'error' in response:
                    logger.error(f"Snapcast RPC error: {response['error']}")
                    return None
                return response.get('result')
            
            return None
            
        except Exception as e:
            logger.error(f"Error sending Snapcast request: {e}")
            return None

    def _find_client_id(self):
        """Find the client ID for this device"""
        if self.client_id:
            return self.client_id
            
        try:
            # Get server status to find our client
            result = self._send_request("Server.GetStatus")
            if not result:
                return None
                
            server = result.get('server', {})
            groups = server.get('groups', [])
            
            for group in groups:
                clients = group.get('clients', [])
                for client in clients:
                    # Match by hostname or MAC address if available
                    host_info = client.get('host', {})
                    if host_info.get('name') == socket.gethostname():
                        self.client_id = client.get('id')
                        logger.debug(f"Found Snapcast client ID: {self.client_id}")
                        return self.client_id
            
            # If no exact match, use the first client (single client setup)
            if groups and groups[0].get('clients'):
                first_client = groups[0]['clients'][0]
                self.client_id = first_client.get('id')
                logger.debug(f"Using first Snapcast client ID: {self.client_id}")
                return self.client_id
                
            logger.warning("No Snapcast client found")
            return None
            
        except Exception as e:
            logger.error(f"Error finding Snapcast client: {e}")
            return None

    def set_volume(self, volume):
        """Set volume for Snapcast client (0-100)"""
        try:
            client_id = self._find_client_id()
            if not client_id:
                logger.error("No Snapcast client ID available")
                return False
            
            # Clamp volume to valid range
            volume = max(0, min(100, int(volume)))
            
            # Send volume change request
            params = {
                "id": client_id,
                "volume": {
                    "percent": volume,
                    "muted": False
                }
            }
            
            result = self._send_request("Client.SetVolume", params)
            if result is not None:
                logger.debug(f"Set Snapcast volume to {volume}%")
                return True
            else:
                logger.error("Failed to set Snapcast volume")
                return False
                
        except Exception as e:
            logger.error(f"Error setting Snapcast volume: {e}")
            return False

    def get_volume(self):
        """Get current volume from Snapcast client"""
        try:
            client_id = self._find_client_id()
            if not client_id:
                return None
                
            result = self._send_request("Server.GetStatus")
            if not result:
                return None
                
            server = result.get('server', {})
            groups = server.get('groups', [])
            
            for group in groups:
                clients = group.get('clients', [])
                for client in clients:
                    if client.get('id') == client_id:
                        config = client.get('config', {})
                        volume = config.get('volume', {})
                        return volume.get('percent', 0)
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting Snapcast volume: {e}")
            return None

    def test_connection(self):
        """Test connection to Snapcast server"""
        try:
            result = self._send_request("Server.GetStatus")
            return result is not None
        except Exception as e:
            logger.error(f"Snapcast connection test failed: {e}")
            return False