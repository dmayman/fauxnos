#!/usr/bin/env python3
"""
Snapcast Group Management
=========================
Manages snapcast groups and ensures clients are assigned to their home groups and sources.
"""

import json
import socket
import argparse
import os
from typing import Dict, List, Any, Optional
from .config_manager import ConfigManager

class SnapcastGroupManager:
    """Manages snapcast groups via JSON-RPC API"""

    def __init__(self, snapcast_host: str = "localhost", snapcast_port: int = 1705, config_manager: ConfigManager = None):
        self.snapcast_host = snapcast_host
        self.snapcast_port = snapcast_port
        self.config_manager = config_manager

    def send_snapcast_command(self, method: str, params: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
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
            # Connect to snapcast server
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((self.snapcast_host, self.snapcast_port))

            # Send request
            request_data = json.dumps(request) + "\n"
            sock.send(request_data.encode())

            # Receive response
            response_data = sock.recv(4096).decode()
            sock.close()

            if response_data:
                response = json.loads(response_data.strip())
                return response
            return None

        except Exception as e:
            print(f"❌ Failed to send snapcast command {method}: {e}")
            return None

    def get_server_status(self) -> Optional[Dict[str, Any]]:
        """Get current snapcast server status"""
        return self.send_snapcast_command("Server.GetStatus")

    def get_groups(self) -> List[Dict[str, Any]]:
        """Get list of all groups"""
        status = self.get_server_status()
        if status and "result" in status and "server" in status["result"]:
            return status["result"]["server"].get("groups", [])
        return []

    def find_client_group(self, client_id: str) -> Optional[Dict[str, Any]]:
        """Find which group a client is currently in"""
        groups = self.get_groups()
        for group in groups:
            for client in group.get("clients", []):
                # Check the client ID directly (set by --hostID parameter)
                if client.get("id") == client_id:
                    return group
                # Also check hostname as fallback
                elif client.get("host", {}).get("name") == client_id:
                    return group
        return None

    def move_client_to_group(self, client_id: str, target_group_id: str) -> bool:
        """Move a client to a specific group"""
        result = self.send_snapcast_command("Group.SetClients", {
            "id": target_group_id,
            "clients": [client_id]
        })

        if result is None:
            print(f"      ❌ No response from snapcast server")
            return False
        elif "error" in result:
            error = result["error"]
            print(f"      ❌ Snapcast error: {error.get('message', 'Unknown error')} (code: {error.get('code', 'N/A')})")
            return False
        elif "result" not in result:
            print(f"      ❌ Unexpected response format: {result}")
            return False

        return True

    def set_group_source(self, group_id: str, source_id: str) -> bool:
        """Set the source for a group"""
        # First, let's check what sources are available
        status = self.get_server_status()
        if status and "result" in status and "server" in status["result"]:
            streams = status["result"]["server"].get("streams", [])
            available_sources = [s.get("id") for s in streams]
            print(f"      📋 Available sources: {available_sources}")

            if source_id not in available_sources:
                print(f"      ⚠️  Source '{source_id}' not found in available sources")
                print(f"      ℹ️  Make sure snapserver.conf includes this source")
                return False

        result = self.send_snapcast_command("Group.SetStream", {
            "id": group_id,
            "stream_id": source_id  # Correct - Snapcast uses stream_id with underscore
        })

        if result is None:
            print(f"      ❌ No response from snapcast server")
            return False
        elif "error" in result:
            error = result["error"]
            print(f"      ❌ Snapcast error: {error.get('message', 'Unknown error')} (code: {error.get('code', 'N/A')})")
            print(f"      📝 Debug: Tried to set group '{group_id}' to source '{source_id}'")
            return False
        elif "result" not in result:
            print(f"      ❌ Unexpected response format: {result}")
            return False

        return True

    def get_client_config(self, client_id: str) -> Optional[Dict[str, Any]]:
        """Get client config from config manager"""
        if not self.config_manager:
            return None
        for client in self.config_manager.server_config.get('clients', []):
            if client['id'] == client_id:
                return client
        return None

    def save_home_group(self, client_id: str, group_id: str):
        """Save home group to client config"""
        if not self.config_manager:
            return
        client_config = self.get_client_config(client_id)
        if client_config:
            client_config['home_group'] = group_id
            self.config_manager.save_server_config()
            print(f"   💾 Saved home group {group_id} for {client_id} to config")

    def remember_client_group(self, client_id: str, force: bool = False) -> Optional[str]:
        """Remember which group a client is currently in as their home group"""
        client_config = self.get_client_config(client_id)
        if not client_config:
            print(f"   ⚠️ Client {client_id} not found in config")
            return None

        # Skip if already remembered (unless force is True)
        if not force and client_config.get('home_group'):
            existing = client_config['home_group']
            print(f"   📋 Already have home group for {client_id}: {existing}")
            return existing

        current_group = self.find_client_group(client_id)
        if current_group:
            group_id = current_group.get("id")
            self.save_home_group(client_id, group_id)
            print(f"   📝 Remembered home group for {client_id}: {group_id}")
            return group_id
        return None

    def get_client_home_group(self, client_id: str) -> Optional[str]:
        """Get the remembered home group for a client"""
        client_config = self.get_client_config(client_id)
        if client_config:
            home_group = client_config.get('home_group')
            # Ignore legacy "group_fauxnos001" style groups - let them be auto-detected
            if home_group and home_group.startswith('group_fauxnos'):
                print(f"   🔄 Ignoring legacy home group format: {home_group}")
                return None
            return home_group
        return None

    def reset_client_home_group(self, client_id: str):
        """Reset/forget the home group for a client"""
        client_config = self.get_client_config(client_id)
        if client_config and 'home_group' in client_config:
            del client_config['home_group']
            self.config_manager.save_server_config()
            print(f"   🔄 Reset home group for {client_id}")

    def ensure_client_home_assignment_with_mapping(self, config_id: str, snapcast_id: str,
                                                   preferred_source: str, dry_run: bool = False) -> bool:
        """Ensure a client is in its home group with the correct source (handles ID mapping)"""
        print(f"🔧 Checking assignment for {config_id} (snapcast: {snapcast_id})")

        # Get current status using snapcast ID
        current_group = self.find_client_group(snapcast_id)
        if not current_group:
            print(f"   ❌ Client {snapcast_id} not found in any group")
            return False

        current_group_id = current_group.get("id")
        # Snapcast API returns stream_id directly, not a nested stream object
        current_source_id = current_group.get("stream_id")

        # Check if this client has a remembered home group (using config ID)
        if not self.get_client_home_group(config_id):
            # First time seeing this client - remember their current group
            client_config = self.get_client_config(config_id)
            if client_config:
                self.save_home_group(config_id, current_group_id)
                print(f"   📝 First time setup - saved home group {current_group_id} for {config_id}")

        # Get the home group (using config ID)
        home_group_id = self.get_client_home_group(config_id)
        if not home_group_id:
            home_group_id = current_group_id  # Fallback to current if no memory

        print(f"   Current: group={current_group_id}, source={current_source_id}")
        print(f"   Home: group={home_group_id}, preferred_source={preferred_source}")

        # Check if we need changes
        needs_group_change = current_group_id != home_group_id
        needs_source_change = current_source_id != preferred_source

        if not needs_group_change and not needs_source_change:
            print(f"   ✅ Client {config_id} already correctly assigned")
            return True

        success = True

        # Move client back to home group if needed (using snapcast ID)
        if needs_group_change:
            if dry_run:
                print(f"   DRY RUN: Would move client back to home group {home_group_id}")
            else:
                print(f"   🔄 Moving client back to home group {home_group_id}")

                # Check if home group still exists
                home_group_exists = False
                for group in self.get_groups():
                    if group.get("id") == home_group_id:
                        home_group_exists = True
                        break

                if home_group_exists:
                    if self.move_client_to_group(snapcast_id, home_group_id):
                        print(f"   ✅ Moved back to home group")
                        current_group_id = home_group_id
                    else:
                        print(f"   ❌ Failed to move to home group")
                        success = False
                else:
                    print(f"   ⚠️ Home group {home_group_id} no longer exists, updating to current group")
                    self.save_home_group(config_id, current_group_id)
                    needs_group_change = False

        # Set the source for the group the client is in
        if success and needs_source_change:
            target_group = home_group_id if not needs_group_change else current_group_id
            if dry_run:
                print(f"   DRY RUN: Would set group {target_group} source to {preferred_source}")
            else:
                print(f"   🔄 Setting group {target_group} source to {preferred_source}")
                if self.set_group_source(target_group, preferred_source):
                    print(f"   ✅ Set correct source")
                else:
                    print(f"   ❌ Failed to set source")
                    success = False

        return success

    def ensure_client_home_assignment(self, client_id: str, preferred_source: str, dry_run: bool = False) -> bool:
        """Ensure a client is in its home group with the correct source"""
        print(f"🔧 Checking assignment for {client_id}")

        # Get current status
        current_group = self.find_client_group(client_id)
        if not current_group:
            print(f"   ❌ Client {client_id} not found in any group")
            return False

        current_group_id = current_group.get("id")
        # Snapcast API returns stream_id directly, not a nested stream object
        current_source_id = current_group.get("stream_id")

        # First time seeing this client? Remember their current group as home
        if not self.get_client_home_group(client_id):
            self.remember_client_group(client_id)

        # Get the home group (could be the one we just remembered)
        home_group_id = self.get_client_home_group(client_id)
        if not home_group_id:
            home_group_id = current_group_id  # Fallback to current if no memory

        print(f"   Current: group={current_group_id}, source={current_source_id}")
        print(f"   Home: group={home_group_id}, preferred_source={preferred_source}")

        # Check if we need changes
        needs_group_change = current_group_id != home_group_id
        needs_source_change = current_source_id != preferred_source

        if not needs_group_change and not needs_source_change:
            print(f"   ✅ Client {client_id} already correctly assigned")
            return True

        success = True

        # Move client back to home group if needed
        if needs_group_change:
            if dry_run:
                print(f"   DRY RUN: Would move client back to home group {home_group_id}")
            else:
                print(f"   🔄 Moving client back to home group {home_group_id}")

                # Check if home group still exists
                home_group_exists = False
                for group in self.get_groups():
                    if group.get("id") == home_group_id:
                        home_group_exists = True
                        break

                if home_group_exists:
                    if self.move_client_to_group(client_id, home_group_id):
                        print(f"   ✅ Moved back to home group")
                        current_group_id = home_group_id
                    else:
                        print(f"   ❌ Failed to move to home group")
                        success = False
                else:
                    print(f"   ⚠️ Home group {home_group_id} no longer exists, updating to current group")
                    needs_group_change = False
                    # Save the current group as the new home group
                    self.save_home_group(client_id, current_group_id)

        # Set the source for the group the client is in
        if success and needs_source_change:
            target_group = home_group_id if not needs_group_change else current_group_id
            if dry_run:
                print(f"   DRY RUN: Would set group {target_group} source to {preferred_source}")
            else:
                print(f"   🔄 Setting group {target_group} source to {preferred_source}")
                if self.set_group_source(target_group, preferred_source):
                    print(f"   ✅ Set correct source")
                else:
                    print(f"   ❌ Failed to set source")
                    success = False

        return success

def assign_all_clients_to_home(config_manager: ConfigManager, dry_run: bool = False) -> bool:
    """Assign all clients to their home groups and sources"""
    print("🏠 Assigning clients to home groups and sources")
    print("=" * 50)

    if dry_run:
        print("🔍 DRY RUN MODE: No changes will be made")
        print()

    group_manager = SnapcastGroupManager(config_manager=config_manager)
    clients = config_manager.get_all_clients()

    if not clients:
        print("📋 No clients found in server config")
        return True

    success = True
    for client in clients:
        # Get home assignment from server config
        server_client = None
        for sc in config_manager.server_config['clients']:
            if sc['id'] == client.id:
                server_client = sc
                break

        if not server_client:
            print(f"❌ Client {client.id} not found in server config")
            success = False
            continue

        home_source = server_client.get('home_source')

        if not home_source:
            print(f"❌ Client {client.id} missing home_source in config")
            success = False
            continue

        client_success = group_manager.ensure_client_home_assignment(
            client.id, home_source, dry_run
        )
        success = success and client_success
        print()

    if success:
        print("✅ All clients assigned to home groups and sources!")
    else:
        print("❌ Some client assignments failed")

    return success

def main():
    parser = argparse.ArgumentParser(
        description="Manage snapcast groups and client assignments",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check current assignments without making changes
  python3 group_manager.py --dry-run

  # Assign all clients to their home groups and sources
  python3 group_manager.py

  # Show verbose output
  python3 group_manager.py --verbose
        """
    )

    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be done without making changes')
    parser.add_argument('--verbose', action='store_true',
                       help='Show detailed output')

    args = parser.parse_args()

    try:
        config_manager = ConfigManager()
        success = assign_all_clients_to_home(config_manager, args.dry_run)
        return 0 if success else 1
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1

if __name__ == '__main__':
    exit(main())