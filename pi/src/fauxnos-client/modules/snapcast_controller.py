#!/usr/bin/env python3
"""
Snapcast Controller

Handles volume control for snapcast client via JSON-RPC
"""

import json
import logging
import socket
from typing import Optional, Dict, Any


class SnapcastController:
    """Controls snapcast client volume via JSON-RPC"""

    def __init__(self, host: str = 'localhost', port: int = 1705):
        """
        Initialize snapcast controller

        Args:
            host: Snapcast server host
            port: Snapcast JSON-RPC port (default 1705)
        """
        self.logger = logging.getLogger(__name__)
        self.host = host
        self.port = port
        self.request_id = 1

    def _send_command(self, method: str, params: Dict[str, Any]) -> Optional[Dict]:
        """
        Send JSON-RPC command to snapcast server

        Args:
            method: JSON-RPC method name
            params: Method parameters

        Returns:
            Response dict or None if error
        """
        try:
            # Create JSON-RPC request
            request = {
                "jsonrpc": "2.0",
                "id": self.request_id,
                "method": method,
                "params": params
            }
            self.request_id += 1

            # Connect to snapcast server
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((self.host, self.port))

            # Send request
            request_json = json.dumps(request) + '\n'
            sock.sendall(request_json.encode('utf-8'))

            # Receive response
            response_data = b''
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response_data += chunk
                if b'\n' in response_data:
                    break

            sock.close()

            # Parse response
            response_json = response_data.decode('utf-8').strip()
            response = json.loads(response_json)

            if 'error' in response:
                self.logger.error(f"Snapcast error: {response['error']}")
                return None

            return response

        except socket.timeout:
            self.logger.error(f"Timeout connecting to snapcast at {self.host}:{self.port}")
            return None
        except ConnectionRefusedError:
            self.logger.error(f"Connection refused to snapcast at {self.host}:{self.port}")
            return None
        except Exception as e:
            self.logger.error(f"Error sending snapcast command: {e}")
            return None

    def set_volume(self, volume: int, client_id: Optional[str] = None) -> bool:
        """
        Set snapcast client volume

        Args:
            volume: Volume level (0-100)
            client_id: Client ID (if None, uses first available client)

        Returns:
            True if successful, False otherwise
        """
        # Clamp volume
        volume = max(0, min(100, volume))

        # If no client ID provided, get first client
        if client_id is None:
            client_id = self._get_first_client_id()
            if not client_id:
                self.logger.error("No snapcast clients found")
                return False

        try:
            response = self._send_command('Client.SetVolume', {
                'id': client_id,
                'volume': {
                    'percent': volume,
                    'muted': False
                }
            })

            if response and 'result' in response:
                self.logger.debug(f"Set snapcast volume to {volume}%")
                return True
            else:
                return False

        except Exception as e:
            self.logger.error(f"Error setting snapcast volume: {e}")
            return False

    def get_volume(self, client_id: Optional[str] = None) -> Optional[int]:
        """
        Get snapcast client volume

        Args:
            client_id: Client ID (if None, uses first available client)

        Returns:
            Volume level (0-100) or None if error
        """
        # If no client ID provided, get first client
        if client_id is None:
            client_id = self._get_first_client_id()
            if not client_id:
                self.logger.error("No snapcast clients found")
                return None

        try:
            response = self._send_command('Client.GetStatus', {
                'id': client_id
            })

            if response and 'result' in response:
                volume = response['result']['client']['config']['volume']['percent']
                return int(volume)
            else:
                return None

        except Exception as e:
            self.logger.error(f"Error getting snapcast volume: {e}")
            return None

    def _get_first_client_id(self) -> Optional[str]:
        """
        Get ID of first available snapcast client

        Returns:
            Client ID or None if no clients
        """
        try:
            response = self._send_command('Server.GetStatus', {})

            if response and 'result' in response:
                server = response['result']['server']
                groups = server.get('groups', [])

                # Find first client in any group
                for group in groups:
                    clients = group.get('clients', [])
                    if clients:
                        return clients[0]['id']

                return None
            else:
                return None

        except Exception as e:
            self.logger.error(f"Error getting snapcast clients: {e}")
            return None

    def test_connection(self) -> bool:
        """
        Test connection to snapcast server

        Returns:
            True if connected, False otherwise
        """
        response = self._send_command('Server.GetStatus', {})
        return response is not None

    def get_client_id_by_mac(self, mac_address: str) -> Optional[str]:
        """
        Get client ID by MAC address

        Args:
            mac_address: MAC address to search for

        Returns:
            Client ID or None if not found
        """
        try:
            response = self._send_command('Server.GetStatus', {})

            if response and 'result' in response:
                server = response['result']['server']
                groups = server.get('groups', [])

                # Search all clients for matching MAC
                for group in groups:
                    for client in group.get('clients', []):
                        host_info = client.get('host', {})
                        if host_info.get('mac') == mac_address:
                            return client['id']

                return None
            else:
                return None

        except Exception as e:
            self.logger.error(f"Error finding client by MAC: {e}")
            return None


# Standalone testing
if __name__ == '__main__':
    import argparse

    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    parser = argparse.ArgumentParser(description='Test Snapcast controller')
    parser.add_argument('command', choices=['test', 'volume', 'get-volume', 'find-mac'])
    parser.add_argument('--host', default='localhost', help='Snapcast server host')
    parser.add_argument('--port', type=int, default=1705, help='Snapcast JSON-RPC port')
    parser.add_argument('--client-id', help='Client ID')
    parser.add_argument('--mac', help='MAC address to find')
    parser.add_argument('--volume', type=int, help='Volume level (0-100)')

    args = parser.parse_args()

    controller = SnapcastController(args.host, args.port)

    if args.command == 'test':
        if controller.test_connection():
            print(f"✓ Connected to snapcast at {args.host}:{args.port}")
        else:
            print(f"✗ Failed to connect to snapcast at {args.host}:{args.port}")

    elif args.command == 'volume':
        if args.volume is None:
            print("Error: --volume required")
        else:
            if controller.set_volume(args.volume, args.client_id):
                print(f"✓ Set volume to {args.volume}%")
            else:
                print(f"✗ Failed to set volume")

    elif args.command == 'get-volume':
        volume = controller.get_volume(args.client_id)
        if volume is not None:
            print(f"Current volume: {volume}%")
        else:
            print("✗ Failed to get volume")

    elif args.command == 'find-mac':
        if not args.mac:
            print("Error: --mac required")
        else:
            client_id = controller.get_client_id_by_mac(args.mac)
            if client_id:
                print(f"Found client: {client_id}")
            else:
                print(f"No client found with MAC {args.mac}")
