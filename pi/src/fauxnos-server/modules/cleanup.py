#!/usr/bin/env python3
"""
Server Infrastructure Cleanup Tool
===================================
Cleans up orphaned services, FIFOs, and configs that don't match server_config.json.
Uses the server config as the source of truth.
"""

import argparse
import subprocess
import os
import glob
import shutil
from .config_manager import ConfigManager

def cleanup_client_services(valid_client_ids, dry_run=False):
    """Stop and remove orphaned snapclient and fauxnos-client services"""
    print("🔧 Checking client services...")

    success = True
    service_patterns = [
        "snapclient-fauxnos",
        "fauxnos-client-fauxnos"
    ]

    for pattern in service_patterns:
        try:
            # Get list of matching services
            result = subprocess.run(
                ["systemctl", "--user", "list-units", "--type=service", "--state=loaded", "--no-legend"],
                capture_output=True, text=True, check=True
            )

            running_services = []
            for line in result.stdout.strip().split('\n'):
                if line and pattern in line:
                    service_name = line.split()[0]
                    running_services.append(service_name)

            # Check each service against valid client IDs
            for service_name in running_services:
                # Extract client ID from service name (e.g., snapclient-fauxnos001 -> fauxnos001)
                if pattern == "snapclient-fauxnos":
                    client_id = service_name.replace("snapclient-", "").replace(".service", "")
                else:  # fauxnos-client-fauxnos
                    client_id = service_name.replace("fauxnos-client-", "").replace(".service", "")

                if client_id not in valid_client_ids:
                    print(f"   🗑️  Orphaned service: {service_name}")
                    if dry_run:
                        print(f"      DRY RUN: Would stop and disable {service_name}")
                    else:
                        try:
                            subprocess.run(["systemctl", "--user", "stop", service_name], check=False)
                            subprocess.run(["systemctl", "--user", "disable", service_name], check=False)

                            # Remove service file
                            service_path = os.path.expanduser(f"~/.config/systemd/user/{service_name}")
                            if os.path.exists(service_path):
                                os.remove(service_path)
                                print(f"      ✅ Stopped, disabled, and removed {service_name}")
                            else:
                                print(f"      ✅ Stopped and disabled {service_name}")
                        except Exception as e:
                            print(f"      ❌ Failed to remove {service_name}: {e}")
                            success = False

        except Exception as e:
            print(f"   ❌ Failed to check {pattern} services: {e}")
            success = False

    return success

def cleanup_go_librespot_services(valid_client_ids, dry_run=False):
    """Stop and remove orphaned go-librespot services"""
    print("🔧 Checking go-librespot services...")

    try:
        # Get list of all go-librespot services
        result = subprocess.run(
            ["systemctl", "--user", "list-units", "--type=service", "--state=loaded", "--no-legend"],
            capture_output=True, text=True, check=True
        )

        running_services = []
        for line in result.stdout.strip().split('\n'):
            if line and 'go-librespot-fauxnos' in line:
                service_name = line.split()[0]
                running_services.append(service_name)

        print(f"   Found go-librespot services: {running_services}")

        removed_count = 0
        for service_name in running_services:
            # Extract client_id from service name (go-librespot-fauxnos001.service -> fauxnos001)
            if 'go-librespot-fauxnos' in service_name:
                client_id = service_name.replace('go-librespot-', '').replace('.service', '')

                if client_id not in valid_client_ids:
                    print(f"   ❌ Found orphaned service: {service_name} (client {client_id} not in config)")

                    if dry_run:
                        print(f"      DRY RUN: Would stop and disable {service_name}")
                    else:
                        # Stop and disable the service
                        subprocess.run(["systemctl", "--user", "stop", service_name],
                                     capture_output=True, check=False)
                        subprocess.run(["systemctl", "--user", "disable", service_name],
                                     capture_output=True, check=False)

                        # Remove service file
                        service_file = os.path.expanduser(f"~/.config/systemd/user/{service_name}")
                        if os.path.exists(service_file):
                            os.remove(service_file)
                            print(f"      ✓ Removed orphaned service: {service_name}")
                            removed_count += 1

        if not dry_run and removed_count > 0:
            # Reload systemd to recognize removed services
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
            print(f"   ✓ Removed {removed_count} orphaned services, reloaded systemd")

        return True

    except Exception as e:
        print(f"   ❌ Failed to cleanup go-librespot services: {e}")
        return False

def cleanup_fifo_files(valid_client_ids, dry_run=False):
    """Remove orphaned FIFO files"""
    print("🔧 Checking FIFO files...")

    try:
        fifo_base = "/tmp/snapfifo"
        if not os.path.exists(fifo_base):
            print(f"   ✓ FIFO directory {fifo_base} doesn't exist")
            return True

        # Find all spotify_fauxnosXXX FIFO files
        fifo_pattern = os.path.join(fifo_base, "spotify_fauxnos*")
        existing_fifos = glob.glob(fifo_pattern)

        print(f"   Found FIFO files: {existing_fifos}")

        removed_count = 0
        for fifo_path in existing_fifos:
            # Extract client_id from FIFO name (spotify_fauxnos001 -> fauxnos001)
            fifo_name = os.path.basename(fifo_path)
            if fifo_name.startswith('spotify_'):
                client_id = fifo_name.replace('spotify_', '')

                if client_id not in valid_client_ids:
                    print(f"   ❌ Found orphaned FIFO: {fifo_path} (client {client_id} not in config)")

                    if dry_run:
                        print(f"      DRY RUN: Would remove {fifo_path}")
                    else:
                        os.remove(fifo_path)
                        print(f"      ✓ Removed orphaned FIFO: {fifo_path}")
                        removed_count += 1

        if removed_count > 0:
            print(f"   ✓ Removed {removed_count} orphaned FIFO files")
        else:
            print(f"   ✓ No orphaned FIFO files found")

        return True

    except Exception as e:
        print(f"   ❌ Failed to cleanup FIFO files: {e}")
        return False

def cleanup_go_librespot_configs(valid_client_ids, dry_run=False):
    """Remove orphaned go-librespot configuration directories"""
    print("🔧 Checking go-librespot configs...")

    try:
        config_base = os.path.expanduser("~/.config/go-librespot")
        if not os.path.exists(config_base):
            print(f"   ✓ Config directory {config_base} doesn't exist")
            return True

        # Find all fauxnosXXX config directories
        config_pattern = os.path.join(config_base, "fauxnos*")
        existing_configs = glob.glob(config_pattern)

        print(f"   Found go-librespot config dirs: {existing_configs}")

        removed_count = 0
        for config_dir in existing_configs:
            client_id = os.path.basename(config_dir)

            if client_id not in valid_client_ids:
                print(f"   ❌ Found orphaned config: {config_dir} (client {client_id} not in config)")

                if dry_run:
                    print(f"      DRY RUN: Would remove {config_dir}")
                else:
                    shutil.rmtree(config_dir)
                    print(f"      ✓ Removed orphaned config: {config_dir}")
                    removed_count += 1

        if removed_count > 0:
            print(f"   ✓ Removed {removed_count} orphaned config directories")
        else:
            print(f"   ✓ No orphaned config directories found")

        return True

    except Exception as e:
        print(f"   ❌ Failed to cleanup go-librespot configs: {e}")
        return False

def regenerate_snapserver_config(config_manager, dry_run=False):
    """Regenerate snapserver.conf to remove orphaned sources"""
    print("🔧 Regenerating snapserver.conf...")

    try:
        if dry_run:
            print("   DRY RUN: Would regenerate snapserver.conf with current clients only")
            return True

        # Use existing generate_snapserver_config method
        config_content = config_manager.generate_snapserver_config()

        with open('snapserver.conf', 'w') as f:
            f.write(config_content)

        print("   ✓ Regenerated snapserver.conf with current clients only")
        return True

    except Exception as e:
        print(f"   ❌ Failed to regenerate snapserver config: {e}")
        return False

def reset_snapserver_state(dry_run=False):
    """Reset Snapcast server state to remove stale/duplicate clients"""
    print("🔧 Resetting Snapcast server state...")

    try:
        import os
        import subprocess

        # Check both possible locations for the state file
        possible_state_files = [
            os.path.expanduser("~/.config/snapserver/server.json"),  # Primary location
            os.path.expanduser("~/.config/snapcast/server.json")     # Alternative location
        ]

        state_file = None
        for path in possible_state_files:
            if os.path.exists(path):
                state_file = path
                print(f"   Found state file at: {state_file}")
                break

        if not state_file:
            state_file = possible_state_files[0]  # Default to snapserver location

        if dry_run:
            if os.path.exists(state_file):
                print(f"   DRY RUN: Would remove {state_file}")
                print("   DRY RUN: Would restart snapserver to regenerate clean state")
            else:
                print(f"   State file {state_file} does not exist")
            return True

        # Check if snapserver is running
        result = subprocess.run(["systemctl", "--user", "is-active", "snapserver.service"],
                              capture_output=True, text=True)
        was_running = result.stdout.strip() == "active"

        if was_running:
            # Stop snapserver before removing state
            print("   Stopping snapserver...")
            subprocess.run(["systemctl", "--user", "stop", "snapserver.service"],
                         capture_output=True, check=False)

        # Remove the state file if it exists
        if os.path.exists(state_file):
            # Backup the old state just in case
            backup_file = state_file + ".bak"
            os.rename(state_file, backup_file)
            print(f"   ✓ Backed up old state to {backup_file}")
            print(f"   ✓ Removed stale server.json")
        else:
            print(f"   No existing state file found at {state_file}")

        if was_running:
            # Restart snapserver to create fresh state
            print("   Starting snapserver with fresh state...")
            subprocess.run(["systemctl", "--user", "start", "snapserver.service"],
                         capture_output=True, check=False)
            print("   ✓ Snapserver restarted with clean state")
            print("   ℹ️  Clients will automatically reconnect and be added to the new state")
        else:
            print("   ℹ️  Snapserver was not running. State will be fresh on next start.")

        return True

    except Exception as e:
        print(f"   ❌ Failed to reset snapserver state: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(
        description="Clean up orphaned Fauxnos infrastructure",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # See what would be cleaned up without making changes
  python3 cleanup.py --dry-run

  # Actually clean up orphaned infrastructure
  python3 cleanup.py

  # Verbose output
  python3 cleanup.py --verbose
        """
    )

    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be cleaned up without making changes')
    parser.add_argument('--verbose', action='store_true',
                       help='Show detailed output')

    args = parser.parse_args()

    print("🧹 Fauxnos Infrastructure Cleanup")
    print("=" * 50)

    if args.dry_run:
        print("🔍 DRY RUN MODE: No changes will be made")
        print()

    # Load server config to get valid client list
    try:
        config_manager = ConfigManager()
        valid_client_ids = [client['id'] for client in config_manager.server_config['clients']]
        print(f"📋 Valid clients according to server config: {valid_client_ids}")
        print()
    except Exception as e:
        print(f"❌ Failed to load server config: {e}")
        return 1

    # Run cleanup operations
    cleanup_success = True

    cleanup_success &= cleanup_client_services(valid_client_ids, args.dry_run)
    cleanup_success &= cleanup_go_librespot_services(valid_client_ids, args.dry_run)
    cleanup_success &= cleanup_fifo_files(valid_client_ids, args.dry_run)
    cleanup_success &= cleanup_go_librespot_configs(valid_client_ids, args.dry_run)
    cleanup_success &= regenerate_snapserver_config(config_manager, args.dry_run)
    cleanup_success &= reset_snapserver_state(args.dry_run)

    print()
    if cleanup_success:
        print("✅ Infrastructure cleanup completed successfully!")
        if not args.dry_run:
            print("💡 Snapserver state has been reset. Clients will reconnect automatically.")
    else:
        print("❌ Some cleanup operations failed")
        return 1

    return 0

if __name__ == '__main__':
    exit(main())