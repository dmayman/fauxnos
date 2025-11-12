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
            # Only auto-save home group if client is alone in their group (not manually grouped)
            client_config = self.get_client_config(config_id)
            if client_config:
                # Check if this client is alone in the group
                clients_in_group = len(current_group.get("clients", []))
                if clients_in_group == 1:
                    # Client is alone - this is likely their home group
                    self.save_home_group(config_id, current_group_id)
                    print(f"   📝 First time setup - saved home group {current_group_id} for {config_id}")
                else:
                    # Client is grouped with others - don't auto-save as home
                    print(f"   ⚠️ Client {config_id} is grouped with {clients_in_group-1} other(s), not auto-saving as home group")
                    print(f"   💡 To set home group, separate this client first, then run assign-groups again")

        # Get the home group (using config ID)
        home_group_id = self.get_client_home_group(config_id)
        if not home_group_id:
            # No saved home group
            clients_in_group = len(current_group.get("clients", []))
            if clients_in_group == 1:
                # Client is alone - use current group as home
                home_group_id = current_group_id
            else:
                # Client is grouped - they need to be separated to get their own group
                # For now, don't change their group but flag it
                home_group_id = None
                print(f"   ⚠️ No home group saved and client is grouped with others")

        print(f"   Current: group={current_group_id}, source={current_source_id}")
        print(f"   Home: group={home_group_id}, preferred_source={preferred_source}")

        # Check if we need changes
        if home_group_id is None:
            # No home group and client is grouped - we need to separate them
            needs_group_change = False  # Can't move to a non-existent home
            needs_source_change = False  # Don't change source of shared group
            print(f"   ⏸️  Skipping {config_id} - needs to be separated first")
            return True  # Not a failure, just skipped
        else:
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
                    print(f"   ⚠️ Home group {home_group_id} no longer exists")
                    # Create a new group for this client by removing from current group
                    print(f"   🔄 Creating new home group for {config_id}")

                    # Get all clients in current group
                    current_clients = [c.get("id") for c in current_group.get("clients", [])]
                    other_clients = [c for c in current_clients if c != snapcast_id]

                    if other_clients:
                        # Remove this client from the group (keeping others)
                        result = self.send_snapcast_command("Group.SetClients", {
                            "id": current_group_id,
                            "clients": other_clients
                        })

                        if result and "error" not in result:
                            # Client was removed and should be in a new group now
                            # Find the new group
                            import time
                            time.sleep(0.5)  # Give snapcast time to create new group
                            new_group = self.find_client_group(snapcast_id)
                            if new_group:
                                new_group_id = new_group.get("id")
                                print(f"   ✅ Created new home group: {new_group_id}")
                                self.save_home_group(config_id, new_group_id)
                                current_group_id = new_group_id
                                needs_group_change = False
                            else:
                                print(f"   ❌ Failed to find new group after separation")
                                needs_group_change = False
                        else:
                            print(f"   ❌ Failed to separate from current group")
                            needs_group_change = False
                    else:
                        # Client is alone, just update home to current
                        print(f"   📝 Client is alone, updating home group to current")
                        self.save_home_group(config_id, current_group_id)
                        needs_group_change = False

        # Set the source for the group the client is in
        if success and needs_source_change:
            # Always use current_group_id since it's where the client actually is
            target_group = current_group_id
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

        # Check if this client has a remembered home group
        if not self.get_client_home_group(client_id):
            # Only auto-save home group if client is alone in their group (not manually grouped)
            clients_in_group = len(current_group.get("clients", []))
            if clients_in_group == 1:
                # Client is alone - this is likely their home group
                self.remember_client_group(client_id)
            else:
                # Client is grouped with others - don't auto-save as home
                print(f"   ⚠️ Client {client_id} is grouped with {clients_in_group-1} other(s), not auto-saving as home group")
                print(f"   💡 To set home group, separate this client first, then run assign-groups again")

        # Get the home group (could be the one we just remembered)
        home_group_id = self.get_client_home_group(client_id)
        if not home_group_id:
            # No saved home group
            clients_in_group = len(current_group.get("clients", []))
            if clients_in_group == 1:
                # Client is alone - use current group as home
                home_group_id = current_group_id
            else:
                # Client is grouped - they need to be separated to get their own group
                # For now, don't change their group but flag it
                home_group_id = None
                print(f"   ⚠️ No home group saved and client is grouped with others")

        print(f"   Current: group={current_group_id}, source={current_source_id}")
        print(f"   Home: group={home_group_id}, preferred_source={preferred_source}")

        # Check if we need changes
        if home_group_id is None:
            # No home group and client is grouped - we need to separate them
            needs_group_change = False  # Can't move to a non-existent home
            needs_source_change = False  # Don't change source of shared group
            print(f"   ⏸️  Skipping {client_id} - needs to be separated first")
            return True  # Not a failure, just skipped
        else:
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
                    print(f"   ⚠️ Home group {home_group_id} no longer exists")
                    # Create a new group for this client by removing from current group
                    print(f"   🔄 Creating new home group for {client_id}")

                    # Get all clients in current group
                    current_clients = [c.get("id") for c in current_group.get("clients", [])]
                    other_clients = [c for c in current_clients if c != client_id]

                    if other_clients:
                        # Remove this client from the group (keeping others)
                        result = self.send_snapcast_command("Group.SetClients", {
                            "id": current_group_id,
                            "clients": other_clients
                        })

                        if result and "error" not in result:
                            # Client was removed and should be in a new group now
                            # Find the new group
                            import time
                            time.sleep(0.5)  # Give snapcast time to create new group
                            new_group = self.find_client_group(client_id)
                            if new_group:
                                new_group_id = new_group.get("id")
                                print(f"   ✅ Created new home group: {new_group_id}")
                                self.save_home_group(client_id, new_group_id)
                                current_group_id = new_group_id
                                needs_group_change = False
                            else:
                                print(f"   ❌ Failed to find new group after separation")
                                needs_group_change = False
                        else:
                            print(f"   ❌ Failed to separate from current group")
                            needs_group_change = False
                    else:
                        # Client is alone, just update home to current
                        print(f"   📝 Client is alone, updating home group to current")
                        self.save_home_group(client_id, current_group_id)
                        needs_group_change = False

        # Set the source for the group the client is in
        if success and needs_source_change:
            # Always use current_group_id since it's where the client actually is
            target_group = current_group_id
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

    def join_client_to_group(self, client_id: str, target_client_id: str) -> bool:
        """
        Join a client to another client's group (multiroom sync)

        Args:
            client_id: Client to move
            target_client_id: Client whose group to join

        Returns:
            True if successful, False otherwise
        """
        # Find target client's group
        target_group = self.find_client_group(target_client_id)
        if not target_group:
            print(f"❌ Could not find {target_client_id} in any group")
            return False

        target_group_id = target_group.get('id')
        target_source = target_group.get('stream_id')

        # Get all existing clients in target group
        existing_clients = [c.get('id') for c in target_group.get('clients', [])]

        # Add our client if not already in the group
        if client_id not in existing_clients:
            existing_clients.append(client_id)
        else:
            print(f"ℹ️  {client_id} is already in {target_client_id}'s group")
            return True

        # Set the group to have all these clients
        result = self.send_snapcast_command('Group.SetClients', {
            'id': target_group_id,
            'clients': existing_clients
        })

        if result and 'result' in result:
            print(f"✅ Joined {client_id} to {target_client_id}'s group")
            print(f"   Both clients are now in group {target_group_id[:8]}... with source: {target_source}")
            return True
        else:
            print(f"❌ Failed to join {client_id} to group")
            return False

    def separate_client(self, client_id: str, preferred_source: str) -> bool:
        """
        Separate a client from its current group into its own group with correct source.

        This is the "break away" operation - it removes a client from a shared group
        and puts them in their own group with their preferred source.

        Args:
            client_id: Client to separate
            preferred_source: The source to use for the client's new group

        Returns:
            True if successful, False otherwise
        """
        # Find current group
        current_group = self.find_client_group(client_id)
        if not current_group:
            print(f"   ❌ Client {client_id} not found in any group")
            return False

        current_group_id = current_group.get("id")
        clients_in_group = current_group.get("clients", [])

        # Check if already alone
        if len(clients_in_group) == 1:
            print(f"   ℹ️  {client_id} is already in their own group")
            # Just make sure the source is correct
            current_source = current_group.get("stream_id")
            if current_source != preferred_source:
                print(f"   🔄 Setting source to {preferred_source}")
                if self.set_group_source(current_group_id, preferred_source):
                    print(f"   ✅ Source updated")
                    # Save this as their home group
                    self.save_home_group(client_id, current_group_id)
                    return True
                else:
                    return False
            else:
                # Already correct, save as home group
                self.save_home_group(client_id, current_group_id)
                return True

        # Client is grouped with others - separate them
        print(f"   🔀 Separating {client_id} from {len(clients_in_group)-1} other client(s)")

        # Get all client IDs except this one
        other_clients = [c.get("id") for c in clients_in_group if c.get("id") != client_id]

        # Remove this client from the group (keep others)
        result = self.send_snapcast_command("Group.SetClients", {
            "id": current_group_id,
            "clients": other_clients
        })

        if not result or "error" in result:
            print(f"   ❌ Failed to separate client from group")
            return False

        # Wait for snapcast to create the new group
        import time
        time.sleep(0.5)

        # Find the new group this client is in
        new_group = self.find_client_group(client_id)
        if not new_group:
            print(f"   ❌ Failed to find client's new group after separation")
            return False

        new_group_id = new_group.get("id")
        print(f"   ✅ Client separated to new group {new_group_id[:8]}...")

        # Set the correct source for the new group
        print(f"   🔄 Setting source to {preferred_source}")
        if self.set_group_source(new_group_id, preferred_source):
            print(f"   ✅ Source set to {preferred_source}")
            # Save this as their home group
            self.save_home_group(client_id, new_group_id)
            return True
        else:
            print(f"   ❌ Failed to set source")
            return False

    def return_client_to_home(self, client_id: str) -> bool:
        """
        Return a client to their saved home group and source.

        This uses snapcast's native ability to move clients between groups.
        The home group and source must already be saved in the config.

        Args:
            client_id: Client to return home

        Returns:
            True if successful, False otherwise
        """
        # Get client config to find home group and source
        client_config = self.get_client_config(client_id)
        if not client_config:
            print(f"   ❌ Client {client_id} not found in config")
            return False

        home_group_id = client_config.get('home_group')
        home_source = client_config.get('home_source')

        if not home_group_id:
            print(f"   ⚠️  {client_id} has no home group saved - run 'separate-client' first")
            return False

        if not home_source:
            print(f"   ❌ {client_id} has no home_source in config")
            return False

        # Find current group
        current_group = self.find_client_group(client_id)
        if not current_group:
            print(f"   ❌ Client {client_id} not found in any group")
            return False

        current_group_id = current_group.get("id")
        current_source = current_group.get("stream_id")

        print(f"   Current: group={current_group_id[:8]}..., source={current_source}")
        print(f"   Home: group={home_group_id[:8]}..., source={home_source}")

        # Check if already home
        if current_group_id == home_group_id and current_source == home_source:
            print(f"   ✅ {client_id} already at home")
            return True

        # Check if home group still exists
        home_group_exists = False
        for group in self.get_groups():
            if group.get("id") == home_group_id:
                home_group_exists = True
                break

        if not home_group_exists:
            print(f"   ⚠️  Home group {home_group_id[:8]}... no longer exists")
            print(f"   🔄 Creating new home group by separating client...")
            # Use separate_client to create a new home group
            return self.separate_client(client_id, home_source)

        # Move client to home group
        print(f"   🔄 Moving to home group...")
        if not self.move_client_to_group(client_id, home_group_id):
            print(f"   ❌ Failed to move to home group")
            return False

        print(f"   ✅ Moved to home group")

        # Set the correct source (home group might have wrong source)
        if current_source != home_source:
            print(f"   🔄 Setting home group source to {home_source}")
            if self.set_group_source(home_group_id, home_source):
                print(f"   ✅ Source set correctly")
            else:
                print(f"   ⚠️  Failed to set source (client is home but source may be wrong)")
                return False

        return True

    def return_all_clients_to_home(self, dry_run: bool = False) -> bool:
        """
        Return all clients to their saved home groups and sources.

        Args:
            dry_run: If True, only show what would be done

        Returns:
            True if all succeeded, False if any failed
        """
        if not self.config_manager:
            print("❌ No config manager available")
            return False

        clients = self.config_manager.server_config.get('clients', [])
        if not clients:
            print("📋 No clients found in config")
            return True

        print(f"🏠 Returning {len(clients)} client(s) to home groups")
        print("=" * 50)

        if dry_run:
            print("🔍 DRY RUN MODE: No changes will be made")
            print()

        success = True
        for client in clients:
            client_id = client.get('id')
            print(f"\n🔧 Processing {client_id}...")

            if dry_run:
                home_group = client.get('home_group')
                home_source = client.get('home_source')
                print(f"   DRY RUN: Would return to group={home_group}, source={home_source}")
            else:
                if not self.return_client_to_home(client_id):
                    success = False

        print()
        if success:
            print("✅ All clients returned to home!")
        else:
            print("⚠️  Some clients could not be returned home")

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