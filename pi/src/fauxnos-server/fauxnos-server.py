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
  fauxnos-server.py status
"""

import argparse
import logging
import sys
import threading
import time
import signal
from typing import Dict, Any

# Configure root logging early so submodule loggers (VolumeManager,
# SnapcastClientMonitor, etc.) actually surface in journalctl. Without this
# Python's root logger has no handler attached and every self.logger.info()
# call vanishes into the void. Emit to stderr so systemd's journal captures it.
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    stream=sys.stderr,
)

# Import our modular components
from modules.config_manager import ConfigManager
from modules.api_server import FauxnosAPIServer
from modules.deploy import DeploymentManager
from modules.cleanup import main as cleanup_main
from modules.group_manager import SnapcastGroupManager
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

        # Setup client event callbacks
        self.setup_client_callbacks()

    def log(self, message: str, level: str = "INFO"):
        """Centralized logging — always prints, regardless of self.verbose.

        Verbose can still be used elsewhere for debug-only output; this
        top-level log line is too important to suppress.
        """
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
        """Setup client event callbacks.

        Connect/disconnect events are log-only. Grouping is user-driven via
        /api/groups/join and /api/groups/return-home; no auto-home behavior
        runs in response to a reconnect (that's what caused user-grouping
        to keep getting silently undone).
        """
        def on_client_connect(client_info):
            snapcast_id = client_info.get('id')
            host_name = client_info.get('host', {}).get('name', 'unknown')
            self.log(f"Client connected: ID={snapcast_id}, hostname={host_name}")

        def on_client_disconnect(client_info):
            client_id = client_info.get('id')
            client_name = client_info.get('host', {}).get('name', 'unknown')
            self.log(f"Client disconnected: {client_id} ({client_name})")

        self.client_monitor.set_connect_callback(on_client_connect)
        self.client_monitor.set_disconnect_callback(on_client_disconnect)

    def start_api_server(self):
        """Start the API server in a background thread"""
        self.log("Starting API server...")

        def run_api():
            # Bind dual-stack: '::' with the Pi's default net.ipv6.bindv6only=0
            # accepts both IPv4 and IPv6 on a single socket. Networks where
            # IPv4 client-isolation blocks intra-LAN traffic (e.g. residential
            # wifi APs that drop IPv4 client→client) still let IPv6 through,
            # and modern browsers prefer IPv6 when both are advertised.
            self.api_server.run(host='::', port=8080, debug=False)

        self.api_thread = threading.Thread(target=run_api, daemon=True)
        self.api_thread.start()

    def run_startup_reconcile(self):
        """One-shot at boot: retune any group's stream to match its sole
        connected client's home_source.

        Replaces the old 5-minute maintenance loop. Never moves clients
        between groups — that's user-driven via the /api/groups/* endpoints.
        Only fixes streams to recover from snapcast's prune-and-recreate
        cycle where a fresh group inherits a default stream that doesn't
        match the client's intended home.
        """
        self.log("Running startup reconcile (stream retune only, no moves)...")
        try:
            gm = SnapcastGroupManager(config_manager=self.config_manager)
            gm.reconcile_startup()
            self.log("Startup reconcile complete", "SUCCESS")
        except Exception as e:
            self.log(f"Startup reconcile failed: {e}", "WARNING")

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

        # One-shot startup reconcile: retune any group's stream to match its
        # sole connected client's home_source. Skip in test mode (no snapcast).
        if not self.test_mode:
            self.run_startup_reconcile()

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

            # Find home_source from server config (home_group field is no
            # longer stored — group ownership is derived live from
            # home_source ↔ snapcast stream_id).
            for sc in server_config.get('clients', []):
                if sc.get('id') == client.id:
                    home_source = sc.get('home_source', 'Not set')
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
    print()
    print("  Group join/return-home is user-driven via the web UI →")
    print("  POST /api/groups/join and /api/groups/return-home.")
    print()

    print("💡 COMMON WORKFLOWS")
    print("  • First setup:     add-client → deploy-server")
    print("  • Multiroom join:  drag a device card onto another in the UI")
    print("  • Return home:     drag the joined device out of the group card")
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

  # Show server and client status
  python3 fauxnos-server.py status

  # Show detailed server configuration
  python3 fauxnos-server.py config

  # Show current snapcast groups
  python3 fauxnos-server.py show-groups

Command Overview:
  run              Start the complete server daemon (API + monitoring)
  add-client       Add a new client and deploy infrastructure
  remove-client    Remove a client and clean up infrastructure
  deploy-server    Deploy/update server infrastructure for all clients
  cleanup          Clean up orphaned infrastructure files
  status           Show server status and client information
  config           Show detailed server configuration
  show-groups      Show current snapcast groups

  (Group join / return-home are user-driven via the web UI.)
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

    # Status
    status_parser = subparsers.add_parser('status', help='Show server status')
    status_parser.set_defaults(func=cmd_status)

    # Config
    config_parser = subparsers.add_parser('config', help='Show server configuration')
    config_parser.set_defaults(func=cmd_config)

    # Show groups
    groups_parser = subparsers.add_parser('show-groups', help='Show current snapcast groups')
    groups_parser.set_defaults(func=cmd_show_groups)

    # Parse and execute
    args = parser.parse_args()

    if not hasattr(args, 'func'):
        # Show our custom help instead of argparse default
        cmd_help(args)
        return 1

    return args.func(args)

if __name__ == '__main__':
    exit(main())