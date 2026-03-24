#!/usr/bin/env python3
"""
Fauxnos Server - Unified Interface
==================================
Single entry point for all Fauxnos server operations.

Usage:
  fauxnos-server.py run                    # Start the server daemon
  fauxnos-server.py add-client --name "Kitchen" --mac "aa:bb:cc"
  fauxnos-server.py remove-client --client-id fauxnos001
  fauxnos-server.py deploy-server
  fauxnos-server.py cleanup --dry-run
  fauxnos-server.py assign-groups
  fauxnos-server.py status
"""

import argparse
import sys
import threading
import time
import signal
from typing import Dict, Any

# Import our modular components
from modules.config_manager import ConfigManager
from modules.api_server import FauxnosAPIServer
from modules.deploy import DeploymentManager
from modules.cleanup import main as cleanup_main
from modules.group_manager import assign_all_clients_to_home, SnapcastGroupManager
from modules.client_monitor import SnapcastClientMonitor
from modules.volume_manager import VolumeManager

class FauxnosServer:
    """Main server daemon that orchestrates all components"""

    def __init__(self, test_mode: bool = False, verbose: bool = False):
        self.test_mode = test_mode
        self.verbose = verbose
        self.running = False

        # Initialize components
        self.config_manager = ConfigManager(test_mode=test_mode)
        self.api_server = FauxnosAPIServer(config_manager=self.config_manager, test_mode=test_mode, verbose=verbose)
        self.deployment_manager = DeploymentManager(self.config_manager)
        self.client_monitor = SnapcastClientMonitor()
        self.volume_manager = VolumeManager(config_manager=self.config_manager)

        # Threads for background tasks
        self.api_thread = None
        self.maintenance_thread = None

        # Setup client event callbacks
        self.setup_client_callbacks()

    def log(self, message: str, level: str = "INFO"):
        """Centralized logging"""
        if self.verbose or level in ["ERROR", "WARNING"]:
            colors = {
                "INFO": "\033[1;36m",    # Bright Cyan
                "SUCCESS": "\033[0;32m", # Green
                "WARNING": "\033[1;33m", # Yellow
                "ERROR": "\033[0;31m",   # Red
            }
            reset = "\033[0m"
            prefix = "🔧" if level == "INFO" else "✓" if level == "SUCCESS" else "⚠" if level == "WARNING" else "✗"
            print(f"{colors.get(level, '')}{prefix} [SERVER] {message}{reset}")

    def setup_client_callbacks(self):
        """Setup client event callbacks for group assignment"""
        def on_client_connect(client_info):
            """Handle client connect events"""
            snapcast_id = client_info.get('id')  # This is the client ID (set by --hostID or defaults to MAC)
            host_name = client_info.get('host', {}).get('name', 'unknown')  # This is the actual hostname

            self.log(f"Client connected: ID={snapcast_id}, hostname={host_name} - checking group assignment")

            # Find client in config - the snapcast_id should match our config ID when using --hostID
            client_config = None
            for client in self.config_manager.server_config.get('clients', []):
                # The client ID in config should match the snapcast ID (when using --hostID)
                if client.get('id') == snapcast_id:
                    client_config = client
                    break

            if client_config:
                home_source = client_config.get('home_source')

                if home_source:
                    group_manager = SnapcastGroupManager(config_manager=self.config_manager)
                    # Pass both IDs - config ID for lookups, snapcast ID for operations
                    if group_manager.ensure_client_home_assignment_with_mapping(
                        config_id=client_config['id'],
                        snapcast_id=snapcast_id,
                        preferred_source=home_source
                    ):
                        self.log(f"Assigned {snapcast_id} to correct group and source", "SUCCESS")
                    else:
                        self.log(f"Failed to assign {snapcast_id} correctly", "WARNING")
                else:
                    self.log(f"Client {snapcast_id} missing home source config", "WARNING")
            else:
                self.log(f"Client {snapcast_id} (hostname: {host_name}) not found in server config", "WARNING")

        def on_client_disconnect(client_info):
            """Handle client disconnect events"""
            client_id = client_info.get('id')
            client_name = client_info.get('host', {}).get('name', 'unknown')
            self.log(f"Client disconnected: {client_id} ({client_name})")

        # Set callbacks
        self.client_monitor.set_connect_callback(on_client_connect)
        self.client_monitor.set_disconnect_callback(on_client_disconnect)

    def start_api_server(self):
        """Start the API server in a background thread"""
        self.log("Starting API server...")

        def run_api():
            self.api_server.run(host='0.0.0.0', port=8080, debug=False)

        self.api_thread = threading.Thread(target=run_api, daemon=True)
        self.api_thread.start()

    def start_maintenance_tasks(self):
        """Start periodic maintenance tasks"""
        self.log("Starting maintenance tasks...")

        def maintenance_loop():
            while self.running:
                try:
                    # Every 5 minutes, ensure clients are in correct groups
                    self.log("Running periodic group assignment check...")
                    assign_all_clients_to_home(self.config_manager, dry_run=False)

                    # Sleep for 5 minutes
                    for _ in range(300):  # 5 minutes = 300 seconds
                        if not self.running:
                            break
                        time.sleep(1)

                except Exception as e:
                    self.log(f"Maintenance task error: {e}", "ERROR")
                    time.sleep(60)  # Wait a minute before retrying

        self.maintenance_thread = threading.Thread(target=maintenance_loop, daemon=True)
        self.maintenance_thread.start()

    def start_client_monitoring(self):
        """Start client event monitoring"""
        self.log("Starting client event monitoring...")

        if self.client_monitor.start_monitoring():
            self.log("✅ Client monitoring started", "SUCCESS")
        else:
            self.log("❌ Failed to start client monitoring", "ERROR")

    def start_volume_management(self):
        """Start volume management (WebSocket listeners)"""
        self.log("Starting volume management...")

        try:
            self.volume_manager.start()
            self.log("✅ Volume management started", "SUCCESS")
        except Exception as e:
            self.log(f"❌ Failed to start volume management: {e}", "ERROR")

    def run_daemon(self):
        """Run the complete server daemon"""
        self.log("🚀 Starting Fauxnos Server Daemon")
        self.running = True

        # Setup signal handlers for graceful shutdown
        def signal_handler(signum, frame):
            self.log("Received shutdown signal, stopping server...")
            self.running = False

            # Stop client monitoring
            if hasattr(self, 'client_monitor'):
                self.client_monitor.stop_monitoring()

            # Stop volume management
            if hasattr(self, 'volume_manager'):
                self.volume_manager.stop()

            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Start components
        self.start_api_server()
        self.start_maintenance_tasks()

        # Start client monitoring (skip in test mode)
        if not self.test_mode:
            self.start_client_monitoring()

        # Start volume management (skip in test mode)
        if not self.test_mode:
            self.start_volume_management()

        # Start MQTT listener for external source switching
        if not self.test_mode:
            self.api_server.start_mqtt_listener()

        self.log("✅ Server daemon started successfully!")
        self.log("📡 API server running on port 8080")
        self.log("🔄 Maintenance tasks running every 5 minutes")
        if not self.test_mode:
            self.log("👀 Client event monitoring active")
            self.log("🎚️ Volume management active")
        self.log("Press Ctrl+C to stop")

        # Keep main thread alive
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.log("Shutting down...")
            self.running = False

            # Stop client monitoring
            if hasattr(self, 'client_monitor'):
                self.client_monitor.stop_monitoring()

def cmd_run(args):
    """Run the server daemon"""
    server = FauxnosServer(test_mode=args.test, verbose=args.verbose)
    server.run_daemon()

def cmd_add_client(args):
    """Add a new client"""
    config_manager = ConfigManager(test_mode=args.test)

    if not args.name or not args.mac:
        print("❌ Both --name and --mac are required")
        return 1

    try:
        is_server = getattr(args, 'is_server_device', False)
        new_client = config_manager.add_client(name=args.name, mac=args.mac, is_server_device=is_server)
        print(f"✅ Added client: {new_client.id} ({args.name})")

        # Auto-deploy if requested
        if not args.no_deploy:
            print("🔧 Auto-deploying server infrastructure...")
            deployment_manager = DeploymentManager(config_manager)
            if deployment_manager.deploy_server_configs():
                print("✅ Server infrastructure deployed")

                # Auto-assign groups if requested
                if not args.no_assign:
                    print("🏠 Auto-assigning to home group...")
                    assign_all_clients_to_home(config_manager, dry_run=False)
            else:
                print("❌ Deployment failed")
                return 1

        config_manager.save_server_config()
        return 0

    except Exception as e:
        print(f"❌ Failed to add client: {e}")
        return 1

def cmd_remove_client(args):
    """Remove a client"""
    config_manager = ConfigManager(test_mode=args.test)

    if not args.client_id:
        print("❌ --client-id is required")
        return 1

    try:
        # Check if client exists first
        client = config_manager.get_client(args.client_id)
        if not client:
            print(f"❌ Client {args.client_id} not found")
            return 1

        client_name = client.name

        # Confirm removal unless --force is used
        if not args.force:
            response = input(f"❓ Remove client {args.client_id} ({client_name})? [y/N]: ")
            if response.lower() not in ['y', 'yes']:
                print("❌ Removal cancelled")
                return 0

        # Remove client from config
        if config_manager.remove_client(args.client_id):
            print(f"✅ Removed client: {args.client_id} ({client_name})")

            # Auto-cleanup infrastructure if requested
            if not args.no_cleanup:
                print("🔧 Auto-cleaning server infrastructure...")
                deployment_manager = DeploymentManager(config_manager)
                if deployment_manager.deploy_server_configs():
                    print("✅ Server infrastructure updated")
                else:
                    print("❌ Infrastructure cleanup failed")
                    return 1

            config_manager.save_server_config()
            return 0
        else:
            print(f"❌ Failed to remove client {args.client_id}")
            return 1

    except Exception as e:
        print(f"❌ Failed to remove client: {e}")
        return 1

def cmd_deploy_server(args):
    """Deploy server infrastructure"""
    config_manager = ConfigManager(test_mode=args.test)
    deployment_manager = DeploymentManager(config_manager)

    if deployment_manager.deploy_server_configs():
        print("✅ Server infrastructure deployed successfully")
        return 0
    else:
        print("❌ Deployment failed")
        return 1

def cmd_cleanup(args):
    """Clean up orphaned infrastructure"""
    # Reuse the existing cleanup main function
    sys.argv = ['cleanup.py']
    if args.dry_run:
        sys.argv.append('--dry-run')
    if args.verbose:
        sys.argv.append('--verbose')

    return cleanup_main()

def cmd_assign_groups(args):
    """Assign clients to their home groups"""
    config_manager = ConfigManager(test_mode=args.test)

    if assign_all_clients_to_home(config_manager, dry_run=args.dry_run):
        print("✅ Group assignments completed")
        return 0
    else:
        print("❌ Some group assignments failed")
        return 1

def cmd_status(args):
    """Show server status"""
    config_manager = ConfigManager(test_mode=args.test)

    print("📊 Fauxnos Server Status")
    print("=" * 30)

    # Show clients
    clients = config_manager.get_all_clients()
    print(f"📱 Clients: {len(clients)}")
    for client in clients:
        print(f"   • {client.id} ({client.name})")

    # Show snapcast status (if available)
    try:
        from modules.group_manager import SnapcastGroupManager
        group_manager = SnapcastGroupManager()
        groups = group_manager.get_groups()
        print(f"\n🔊 Snapcast Groups: {len(groups)}")
        for group in groups:
            # Snapcast API returns stream_id directly on the group
            source = group.get('stream_id', 'None')
            client_count = len(group.get('clients', []))
            print(f"   • {group.get('id')} (source: {source}, clients: {client_count})")
    except Exception as e:
        print(f"\n🔊 Snapcast: Unable to connect ({e})")

    return 0

def cmd_reset_groups(args):
    """Reset home groups for testing"""
    print("🔄 Resetting Home Groups")
    print("=" * 50)
    print()

    config_manager = ConfigManager(test_mode=args.test)

    if args.client_id:
        # Reset specific client
        print(f"Resetting home group for client: {args.client_id}")
        for client in config_manager.server_config.get('clients', []):
            if client['id'] == args.client_id:
                if 'home_group' in client:
                    del client['home_group']
                    config_manager.save_server_config()
                    print(f"✅ Reset home group for {args.client_id}")
                else:
                    print(f"ℹ️  {args.client_id} has no home group set")
                break
        else:
            print(f"❌ Client {args.client_id} not found")
    else:
        # Reset all clients
        print("Resetting home groups for all clients...")
        reset_count = 0
        for client in config_manager.server_config.get('clients', []):
            if 'home_group' in client:
                del client['home_group']
                reset_count += 1
                print(f"  - Reset {client['id']}")

        if reset_count > 0:
            config_manager.save_server_config()
            print(f"\n✅ Reset home groups for {reset_count} clients")
        else:
            print("ℹ️  No clients had home groups set")

    print("\n💡 Home groups will be auto-detected on next client connect")
    print("💡 Run 'python3 fauxnos-server.py assign-groups' to trigger reassignment now")
    return 0

def cmd_join_group(args):
    """Join a client to another client's group (multiroom)"""
    config_manager = ConfigManager(test_mode=args.test)
    group_manager = SnapcastGroupManager(config_manager=config_manager)

    print(f"🔗 Joining {args.client_id} to {args.target_id}'s group...")

    if group_manager.join_client_to_group(args.client_id, args.target_id):
        # Show current groups
        print("\n📊 Current groups:")
        groups = group_manager.get_groups()
        for group in groups:
            clients = group.get('clients', [])
            if clients:  # Only show non-empty groups
                client_ids = [c.get('id') for c in clients]
                source = group.get('stream_id')
                print(f"   • Group {group['id'][:8]}... ({source})")
                print(f"     Clients: {', '.join(client_ids)}")
        return 0
    else:
        return 1

def cmd_return_home(args):
    """Return client(s) to their home groups"""
    config_manager = ConfigManager(test_mode=args.test)
    group_manager = SnapcastGroupManager(config_manager=config_manager)

    if args.client_id:
        # Return specific client to home
        print(f"🏠 Returning {args.client_id} to home group...")
        if group_manager.return_client_to_home(args.client_id):
            # Show current groups
            print("\n📊 Current groups:")
            groups = group_manager.get_groups()
            for group in groups:
                clients = group.get('clients', [])
                if clients:  # Only show non-empty groups
                    client_ids = [c.get('id') for c in clients]
                    source = group.get('stream_id')
                    print(f"   • Group {group['id'][:8]}... ({source})")
                    print(f"     Clients: {', '.join(client_ids)}")
            return 0
        else:
            return 1
    else:
        # Return all clients to home
        if group_manager.return_all_clients_to_home(dry_run=args.dry_run):
            return 0
        else:
            return 1

def cmd_show_groups(args):
    """Show current snapcast groups"""
    config_manager = ConfigManager(test_mode=args.test)
    group_manager = SnapcastGroupManager(config_manager=config_manager)

    print("📊 Snapcast Groups")
    print("=" * 60)

    groups = group_manager.get_groups()
    if not groups:
        print("No groups found")
        return 0

    for i, group in enumerate(groups, 1):
        clients = group.get('clients', [])
        if not clients:
            continue  # Skip empty groups

        source = group.get('stream_id', 'None')
        group_id = group.get('id', 'unknown')

        print(f"\nGroup {i}: {group_id[:8]}...")
        print(f"  Source: {source}")
        print(f"  Clients: {len(clients)}")
        for client in clients:
            client_id = client.get('id', 'unknown')
            client_name = client.get('host', {}).get('name', 'unknown')
            volume = client.get('config', {}).get('volume', {}).get('percent', 0)
            connected = "✓" if client.get('connected') else "✗"
            print(f"    [{connected}] {client_id} ({client_name}) @ {volume}%")

    print("\n" + "=" * 60)
    return 0

def cmd_config(args):
    """Show server configuration in readable format"""
    config_manager = ConfigManager(test_mode=args.test)

    print("⚙️  Fauxnos Server Configuration")
    print("=" * 40)

    # Server info
    server_config = config_manager.server_config
    print(f"📍 Server Name: {server_config.get('server_name', 'fauxnos-server')}")
    print(f"🏠 Base Directory: {server_config.get('base_dir', '/home/user')}")

    # Clients section
    clients = config_manager.get_all_clients()
    print(f"\n📱 Clients ({len(clients)}):")
    if not clients:
        print("   (No clients configured)")
    else:
        for client in clients:
            print(f"\n   🔹 {client.id} ({client.name})")
            print(f"      MAC Address: {client.mac}")
            print(f"      Server Port: {client.server_port}")
            print(f"      Zeroconf Port: {client.zeroconf_port}")

            # Find home group/source from server config
            for sc in server_config.get('clients', []):
                if sc.get('id') == client.id:
                    home_group = sc.get('home_group', 'Not set')
                    home_source = sc.get('home_source', 'Not set')
                    print(f"      Home Group: {home_group}")
                    print(f"      Home Source: {home_source}")
                    break

    # Global settings
    print(f"\n🔧 Global Settings:")
    print(f"   Next Client ID: {config_manager.get_next_client_id()}")

    # File locations
    print(f"\n📁 Configuration Files:")
    print(f"   Server Config: {config_manager.config_file}")
    if args.verbose:
        print(f"   Go-Librespot Configs: ~/.config/go-librespot/")
        print(f"   Systemd Services: ~/.config/systemd/user/")
        print(f"   Snapserver Config: ~/.config/snapserver/snapserver.conf")

    return 0

def cmd_help(args):
    """Show concise help for all commands"""
    print("📚 Fauxnos Server Commands")
    print("=" * 70)
    print()

    print("🎛️  SERVER MANAGEMENT")
    print("  run                Start server daemon (API + monitoring + volume sync)")
    print("  status             Show server and client status")
    print("  config             Show detailed configuration")
    print()

    print("👥 CLIENT MANAGEMENT")
    print("  add-client         Add new client and deploy infrastructure")
    print("                     --name NAME --mac MAC [--is-server-device]")
    print("  remove-client      Remove client and cleanup")
    print("                     --client-id ID [--force]")
    print()

    print("🏗️  INFRASTRUCTURE")
    print("  deploy-server      Deploy/update snapserver and go-librespot configs")
    print("  cleanup            Remove orphaned service files [--dry-run]")
    print()

    print("🏠 GROUP MANAGEMENT")
    print("  show-groups        Display current snapcast groups and clients")
    print("  join-group         Join client to another's group (multiroom)")
    print("                     CLIENT_ID TARGET_ID")
    print("  return-home        Return client(s) to saved home groups")
    print("                     [--client-id ID] [--dry-run]")
    print("  assign-groups      Auto-assign all clients to home (first setup)")
    print("                     [--dry-run]")
    print("  reset-groups       Clear saved home groups for testing")
    print("                     [--client-id ID]")
    print()

    print("💡 COMMON WORKFLOWS")
    print("  • First setup:     add-client → deploy-server → assign-groups")
    print("  • Multiroom:       join-group fauxnos001 fauxnos000")
    print("  • Return home:     return-home --client-id fauxnos001")
    print("  • Return all home: return-home")
    print()

    print("🔧 GLOBAL FLAGS")
    print("  --test             Run in test mode (use test config)")
    print("  --verbose          Show detailed output")
    print()

    print("📖 For detailed help: python3 fauxnos-server.py COMMAND --help")
    return 0

def main():
    parser = argparse.ArgumentParser(
        description="Fauxnos Server - Unified Interface",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start the server daemon
  python3 fauxnos-server.py run

  # Add a new client
  python3 fauxnos-server.py add-client --name "Kitchen" --mac "aa:bb:cc:dd:ee:ff"

  # Remove a client
  python3 fauxnos-server.py remove-client --client-id fauxnos001

  # Deploy/redeploy server infrastructure
  python3 fauxnos-server.py deploy-server

  # Clean up orphaned infrastructure
  python3 fauxnos-server.py cleanup --dry-run

  # Assign all clients to their home groups
  python3 fauxnos-server.py assign-groups

  # Show server and client status
  python3 fauxnos-server.py status

  # Show detailed server configuration
  python3 fauxnos-server.py config

  # Reset home groups for testing
  python3 fauxnos-server.py reset-groups
  python3 fauxnos-server.py reset-groups --client-id fauxnos001

  # Show current snapcast groups
  python3 fauxnos-server.py show-groups

  # Join clients together (multiroom sync)
  python3 fauxnos-server.py join-group fauxnos001 fauxnos000

  # Return client(s) to their home groups
  python3 fauxnos-server.py return-home --client-id fauxnos001  # single client
  python3 fauxnos-server.py return-home                          # all clients

Command Overview:
  run              Start the complete server daemon (API + monitoring + maintenance)
  add-client       Add a new client and deploy infrastructure
  remove-client    Remove a client and clean up infrastructure
  deploy-server    Deploy/update server infrastructure for all clients
  cleanup          Clean up orphaned infrastructure files
  assign-groups    Assign all clients to their home groups and sources
  status           Show server status and client information
  config           Show detailed server configuration
  reset-groups     Reset home groups (for testing auto-detection)
  show-groups      Show current snapcast groups
  join-group       Join a client to another client's group (multiroom)
  return-home      Return client(s) to their saved home groups
        """
    )

    # Global options
    parser.add_argument('--test', action='store_true',
                       help='Run in test mode')
    parser.add_argument('--verbose', action='store_true',
                       help='Show verbose output')

    # Subcommands
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Help
    help_parser = subparsers.add_parser('help', help='Show command help')
    help_parser.set_defaults(func=cmd_help)

    # Run daemon
    run_parser = subparsers.add_parser('run', help='Start the server daemon')
    run_parser.set_defaults(func=cmd_run)

    # Add client
    add_parser = subparsers.add_parser('add-client', help='Add a new client')
    add_parser.add_argument('--name', required=True, help='Display name for client')
    add_parser.add_argument('--mac', required=True, help='MAC address of client')
    add_parser.add_argument('--is-server-device', action='store_true', help='Mark as server device (forces fauxnos000 ID)')
    add_parser.add_argument('--no-deploy', action='store_true', help='Skip auto-deployment')
    add_parser.add_argument('--no-assign', action='store_true', help='Skip auto-group assignment')
    add_parser.set_defaults(func=cmd_add_client)

    # Remove client
    remove_parser = subparsers.add_parser('remove-client', help='Remove a client')
    remove_parser.add_argument('--client-id', required=True, help='Client ID to remove (e.g., fauxnos001)')
    remove_parser.add_argument('--force', action='store_true', help='Skip confirmation prompt')
    remove_parser.add_argument('--no-cleanup', action='store_true', help='Skip auto-cleanup of infrastructure')
    remove_parser.set_defaults(func=cmd_remove_client)

    # Deploy server
    deploy_parser = subparsers.add_parser('deploy-server', help='Deploy server infrastructure')
    deploy_parser.set_defaults(func=cmd_deploy_server)

    # Cleanup
    cleanup_parser = subparsers.add_parser('cleanup', help='Clean up orphaned infrastructure')
    cleanup_parser.add_argument('--dry-run', action='store_true', help='Show what would be cleaned')
    cleanup_parser.set_defaults(func=cmd_cleanup)

    # Assign groups
    assign_parser = subparsers.add_parser('assign-groups', help='Assign clients to home groups')
    assign_parser.add_argument('--dry-run', action='store_true', help='Show what would be assigned')
    assign_parser.set_defaults(func=cmd_assign_groups)

    # Status
    status_parser = subparsers.add_parser('status', help='Show server status')
    status_parser.set_defaults(func=cmd_status)

    # Config
    config_parser = subparsers.add_parser('config', help='Show server configuration')
    config_parser.set_defaults(func=cmd_config)

    # Reset groups (for testing)
    reset_parser = subparsers.add_parser('reset-groups', help='Reset home groups for testing')
    reset_parser.add_argument('--client-id', help='Reset specific client (default: all)')
    reset_parser.set_defaults(func=cmd_reset_groups)

    # Show groups
    groups_parser = subparsers.add_parser('show-groups', help='Show current snapcast groups')
    groups_parser.set_defaults(func=cmd_show_groups)

    # Join group (multiroom)
    join_parser = subparsers.add_parser('join-group', help='Join a client to another client\'s group (multiroom)')
    join_parser.add_argument('client_id', help='Client ID to move (e.g., fauxnos001)')
    join_parser.add_argument('target_id', help='Client ID to join with (e.g., fauxnos000)')
    join_parser.set_defaults(func=cmd_join_group)

    # Return home
    return_parser = subparsers.add_parser('return-home', help='Return client(s) to their saved home groups')
    return_parser.add_argument('--client-id', help='Client ID to return home (default: all clients)')
    return_parser.add_argument('--dry-run', action='store_true', help='Show what would be done (all clients only)')
    return_parser.set_defaults(func=cmd_return_home)

    # Parse and execute
    args = parser.parse_args()

    if not hasattr(args, 'func'):
        # Show our custom help instead of argparse default
        cmd_help(args)
        return 1

    return args.func(args)

if __name__ == '__main__':
    exit(main())