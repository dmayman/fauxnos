#!/usr/bin/env python3
"""
Snapcast Volume Controller
-------------------------
Controls Snapcast server volume via JSON-RPC API.
Provides group-based volume control for multiroom audio.
"""

import json
import socket
import logging
from typing import Optional, Dict, Any, List


class SnapcastController:
    def __init__(self, host="localhost", port=1705):
        self.host = host
        self.port = port
        self.logger = logging.getLogger('SnapcastController')
        
    def _send_request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Send JSON-RPC request to Snapcast server"""
        try:
            # Create socket connection
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect((self.host, self.port))
            
            # Build JSON-RPC request
            request = {
                "jsonrpc": "2.0",
                "method": method,
                "id": 1
            }
            
            if params:
                request["params"] = params
                
            # Send request
            request_str = json.dumps(request) + "\n"
            sock.sendall(request_str.encode('utf-8'))
            
            # Receive response
            response = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
                if b'\n' in response:
                    break
            
            sock.close()
            
            # Parse response
            response_str = response.decode('utf-8').strip()
            if response_str:
                result = json.loads(response_str)
                if "error" in result:
                    self.logger.error(f"Snapcast error: {result['error']}")
                    return None
                return result.get("result")
            
        except Exception as e:
            self.logger.error(f"Failed to send request to Snapcast: {e}")
            return None
            
    def get_server_status(self) -> Optional[Dict[str, Any]]:
        """Get complete server status including groups and clients"""
        return self._send_request("Server.GetStatus")
        
    def find_group_by_name(self, group_name: str) -> Optional[Dict[str, Any]]:
        """Find a group by name (matches stream_id or source name)"""
        status = self.get_server_status()
        if not status:
            return None
            
        groups = status.get('server', {}).get('groups', [])
        
        for group in groups:
            # Check stream_id first
            stream_id = group.get('stream_id', '').lower()
            if group_name.lower() in stream_id:
                return group
                
            # Check if any client in the group has the name
            for client in group.get('clients', []):
                client_name = client.get('host', {}).get('name', '').lower()
                if group_name.lower() in client_name:
                    return group
                    
        return None
        
    def set_client_volume(self, client_id: str, volume: int) -> bool:
        """Set volume for a specific client"""
        if not (0 <= volume <= 100):
            self.logger.error(f"Invalid volume: {volume}. Must be 0-100")
            return False
            
        params = {
            "id": client_id,
            "volume": {
                "percent": volume,
                "muted": False
            }
        }
        
        result = self._send_request("Client.SetVolume", params)
        return result is not None
        
    def set_group_volume(self, group_name: str, volume: int) -> bool:
        """Set volume for all clients in a group"""
        if not (0 <= volume <= 100):
            self.logger.error(f"Invalid volume: {volume}. Must be 0-100") 
            return False
            
        # Find the target group
        group = self.find_group_by_name(group_name)
        if not group:
            self.logger.error(f"Group '{group_name}' not found")
            return False
            
        # Set volume for all clients in the group
        clients = group.get('clients', [])
        if not clients:
            self.logger.warning(f"No clients found in group '{group_name}'")
            return False
            
        success_count = 0
        for client in clients:
            client_id = client.get('id')
            client_name = client.get('host', {}).get('name', client_id)
            
            if self.set_client_volume(client_id, volume):
                self.logger.info(f"Set volume to {volume}% for client '{client_name}'")
                success_count += 1
            else:
                self.logger.error(f"Failed to set volume for client '{client_name}'")
                
        total_clients = len(clients)
        self.logger.info(f"Set volume to {volume}% for {success_count}/{total_clients} clients in group '{group_name}'")
        
        return success_count > 0
        
    def get_group_master_volume(self, group_name: str) -> Optional[float]:
        """Calculate master volume for a group (average of all client volumes)"""
        group = self.find_group_by_name(group_name)
        if not group:
            return None
            
        clients = group.get('clients', [])
        if not clients:
            return None
            
        total_volume = 0
        for client in clients:
            client_volume = client.get('config', {}).get('volume', {}).get('percent', 0)
            total_volume += client_volume
            
        return total_volume / len(clients)
    
    def set_group_volume_direct(self, group_name: str, target_volume: int) -> bool:
        """Set group master volume using snapweb-style proportional scaling"""
        if not (0 <= target_volume <= 100):
            self.logger.error(f"Invalid volume: {target_volume}. Must be 0-100") 
            return False
            
        # Find the target group
        group = self.find_group_by_name(group_name)
        if not group:
            self.logger.error(f"Group '{group_name}' not found")
            return False
            
        clients = group.get('clients', [])
        if not clients:
            self.logger.warning(f"No clients found in group '{group_name}'")
            return False
            
        # Store initial client volumes and calculate current group volume
        client_volumes = {}
        group_volume = 0
        
        for client in clients:
            client_id = client.get('id')
            client_volume = client.get('config', {}).get('volume', {}).get('percent', 0)
            client_volumes[client_id] = client_volume
            group_volume += client_volume
            
        group_volume /= len(clients)  # Average volume
        
        # Calculate delta and ratio (exactly like snapweb)
        delta = target_volume - group_volume
        
        if delta < 0:
            # Volume decreasing
            ratio = (group_volume - target_volume) / group_volume if group_volume > 0 else 0
        else:
            # Volume increasing  
            ratio = (target_volume - group_volume) / (100 - group_volume) if group_volume < 100 else 0
            
        # Apply proportional scaling to each client
        success_count = 0
        for client in clients:
            client_id = client.get('id')
            client_name = client.get('host', {}).get('name', client_id)
            original_volume = client_volumes[client_id]
            
            if delta < 0:
                # Decrease volume proportionally
                new_volume = original_volume - (ratio * original_volume)
            else:
                # Increase volume proportionally
                new_volume = original_volume + (ratio * (100 - original_volume))
                
            # Clamp to valid range
            new_volume = max(0, min(100, int(round(new_volume))))
            
            if self.set_client_volume(client_id, new_volume):
                self.logger.info(f"Scaled '{client_name}' volume: {original_volume}% → {new_volume}%")
                success_count += 1
            else:
                self.logger.error(f"Failed to set volume for client '{client_name}'")
                
        total_clients = len(clients)
        self.logger.info(f"Master volume scaling: {success_count}/{total_clients} clients updated")
        self.logger.info(f"Group master volume: {group_volume:.1f}% → {target_volume}%")
        
        return success_count > 0
        
    def list_groups(self) -> List[Dict[str, Any]]:
        """List all groups with their clients"""
        status = self.get_server_status()
        if not status:
            return []
            
        groups = status.get('server', {}).get('groups', [])
        result = []
        
        for group in groups:
            group_info = {
                'id': group.get('id'),
                'stream_id': group.get('stream_id'),
                'muted': group.get('muted', False),
                'clients': []
            }
            
            for client in group.get('clients', []):
                client_info = {
                    'id': client.get('id'),
                    'name': client.get('host', {}).get('name', 'Unknown'),
                    'volume': client.get('config', {}).get('volume', {}).get('percent', 0),
                    'muted': client.get('config', {}).get('volume', {}).get('muted', False)
                }
                group_info['clients'].append(client_info)
                
            result.append(group_info)
            
        return result
        
    def list_clients(self) -> List[Dict[str, Any]]:
        """List all clients across all groups"""
        status = self.get_server_status()
        if not status:
            return []
            
        clients = []
        groups = status.get('server', {}).get('groups', [])
        
        for group in groups:
            group_stream = group.get('stream_id', 'Unknown')
            
            for client in group.get('clients', []):
                client_info = {
                    'id': client.get('id'),
                    'name': client.get('host', {}).get('name', 'Unknown'),
                    'group': group_stream,
                    'volume': client.get('config', {}).get('volume', {}).get('percent', 0),
                    'muted': client.get('config', {}).get('volume', {}).get('muted', False),
                    'connected': client.get('connected', False)
                }
                clients.append(client_info)
                
        return clients
        
    def find_client_by_name(self, client_name: str) -> Optional[str]:
        """Find a client ID by name (case-insensitive partial match)"""
        clients = self.list_clients()
        
        # First try exact match
        for client in clients:
            if client['name'].lower() == client_name.lower():
                return client['id']
                
        # Then try partial match
        for client in clients:
            if client_name.lower() in client['name'].lower():
                return client['id']
                
        return None