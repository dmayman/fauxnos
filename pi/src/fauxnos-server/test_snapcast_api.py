#!/usr/bin/env python3
"""
Test script to debug Snapcast JSON-RPC API calls
"""

import json
import socket
import sys

def send_snapcast_command(method, params=None, host="localhost", port=1705):
    """Send JSON-RPC command to snapcast server"""
    if params is None:
        params = {}

    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params
    }

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((host, port))

        request_data = json.dumps(request) + "\n"
        print(f"Sending: {request_data}")
        sock.send(request_data.encode())

        response_data = sock.recv(4096).decode()
        sock.close()

        if response_data:
            response = json.loads(response_data.strip())
            print(f"Received: {json.dumps(response, indent=2)}")
            return response
        return None

    except Exception as e:
        print(f"Error: {e}")
        return None

def test_snapcast_api():
    """Test various Snapcast API calls"""

    print("=" * 60)
    print("TESTING SNAPCAST API")
    print("=" * 60)

    # 1. Get server status to see groups and streams
    print("\n1. Getting server status...")
    status = send_snapcast_command("Server.GetStatus")

    if status and "result" in status:
        server = status["result"]["server"]

        # Show available streams
        print("\n📻 Available Streams:")
        for stream in server.get("streams", []):
            print(f"  - ID: {stream['id']}")
            print(f"    Status: {stream['status']}")

        # Show groups
        print("\n👥 Groups:")
        for group in server.get("groups", []):
            print(f"  - Group ID: {group['id']}")
            current_stream = group.get("stream_id", "None")
            print(f"    Current stream: {current_stream}")
            print(f"    Clients: {[c.get('id') for c in group.get('clients', [])]}")

    # 2. Test setting a group's stream with different parameter names
    if len(sys.argv) > 1:
        group_id = sys.argv[1]
        source_id = sys.argv[2] if len(sys.argv) > 2 else "source_fauxnos001_spotify"

        print(f"\n2. Testing Group.SetStream for group {group_id} to source {source_id}")

        # Try with stream_id
        print("\nTrying with 'stream_id' parameter:")
        result = send_snapcast_command("Group.SetStream", {
            "id": group_id,
            "stream_id": source_id
        })

        if result and "error" in result:
            print(f"❌ Failed with stream_id: {result['error']}")

            # Try with streamId
            print("\nTrying with 'streamId' parameter:")
            result = send_snapcast_command("Group.SetStream", {
                "id": group_id,
                "streamId": source_id
            })

            if result and "error" in result:
                print(f"❌ Failed with streamId: {result['error']}")
            elif result and "result" in result:
                print(f"✅ Success with streamId!")
        elif result and "result" in result:
            print(f"✅ Success with stream_id!")

if __name__ == "__main__":
    print("Usage: python3 test_snapcast_api.py [group_id] [source_id]")
    print("  - group_id: Optional, test setting this group's source")
    print("  - source_id: Optional, the source to set (default: source_fauxnos001_spotify)")
    test_snapcast_api()