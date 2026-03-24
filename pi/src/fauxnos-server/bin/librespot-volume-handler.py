#!/usr/bin/env python3
"""
Librespot Volume Event Handler

Called by librespot via --onevent flag when volume changes.
Receives client_id as argument and VOLUME from environment.
Updates snapcast client volume via JSON-RPC.

Usage:
  librespot-volume-handler.py <client_id>

Environment variables (set by librespot):
  PLAYER_EVENT: Event type (e.g., "volume_changed")
  VOLUME: New volume level (0-100)
"""

import os
import sys
import json
import socket


def send_snapcast_command(method: str, params: dict, host: str = "localhost", port: int = 1705) -> dict:
    """Send JSON-RPC command to snapcast server"""
    try:
        # Create socket connection
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((host, port))

        # Build JSON-RPC request
        request = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1
        }

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
            return result

        return None

    except Exception as e:
        print(f"Error sending snapcast command: {e}", file=sys.stderr)
        return None


def set_client_volume(client_id: str, volume: int) -> bool:
    """Set volume for a specific snapcast client"""
    # Clamp volume to valid range
    volume = max(0, min(100, int(volume)))

    params = {
        "id": client_id,
        "volume": {
            "percent": volume,
            "muted": False
        }
    }

    result = send_snapcast_command("Client.SetVolume", params)

    if result and "result" in result:
        return True
    elif result and "error" in result:
        print(f"Snapcast error: {result['error']}", file=sys.stderr)
        return False
    else:
        print(f"No response from snapcast", file=sys.stderr)
        return False


def main():
    # Check arguments
    if len(sys.argv) < 2:
        print("Usage: librespot-volume-handler.py <client_id>", file=sys.stderr)
        sys.exit(1)

    client_id = sys.argv[1]

    # Get environment variables
    player_event = os.environ.get('PLAYER_EVENT', '')

    # Only handle volume_changed events
    if player_event != 'volume_changed':
        # Silently exit for other events
        sys.exit(0)

    # Get volume from environment
    volume_str = os.environ.get('VOLUME', '')
    if not volume_str:
        print("VOLUME environment variable not set", file=sys.stderr)
        sys.exit(1)

    try:
        volume = int(volume_str)
    except ValueError:
        print(f"Invalid VOLUME value: {volume_str}", file=sys.stderr)
        sys.exit(1)

    # Set the client volume
    if set_client_volume(client_id, volume):
        # Success - exit quietly
        sys.exit(0)
    else:
        # Failed - exit with error code
        sys.exit(1)


if __name__ == '__main__':
    main()
