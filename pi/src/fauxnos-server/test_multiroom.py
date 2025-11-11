#!/usr/bin/env python3
"""
Test script for multiroom group management
Emulates what a future UI would do for grouping/ungrouping clients
"""

import sys
import argparse
from modules.config_manager import ConfigManager
from modules.group_manager import SnapcastGroupManager, assign_all_clients_to_home

def show_status(gm: SnapcastGroupManager):
    """Display current group status"""
    print("\n" + "=" * 60)
    print("Current Snapcast Groups:")
    print("=" * 60)

    groups = gm.get_groups()
    for i, group in enumerate(groups, 1):
        source = group.get('stream_id', 'None')
        clients = group.get('clients', [])

        print(f"\nGroup {i}: {group['id'][:8]}...")
        print(f"  Source: {source}")
        print(f"  Clients: {len(clients)}")
        for client in clients:
            client_id = client.get('id', 'unknown')
            client_name = client.get('host', {}).get('name', 'unknown')
            volume = client.get('config', {}).get('volume', {}).get('percent', 0)
            print(f"    - {client_id} ({client_name}) @ {volume}%")
    print("=" * 60 + "\n")

def cmd_show(args):
    """Show current group configuration"""
    gm = SnapcastGroupManager()
    show_status(gm)
    return 0

def cmd_join(args):
    """Join a client to another client's group (multiroom)"""
    gm = SnapcastGroupManager()

    print(f"\n🔗 Joining {args.client} to {args.target}'s group...")

    # Find target client's group
    target_group = gm.find_client_group(args.target)
    if not target_group:
        print(f"❌ Could not find {args.target} in any group")
        return 1

    target_group_id = target_group.get('id')
    target_source = target_group.get('stream_id')
    print(f"   Target is in group {target_group_id[:8]}... with source {target_source}")

    # Get all existing clients in target group
    existing_clients = [c.get('id') for c in target_group.get('clients', [])]

    # Add our client if not already in the group
    if args.client not in existing_clients:
        existing_clients.append(args.client)

    # Set the group to have all these clients
    result = gm.send_snapcast_command('Group.SetClients', {
        'id': target_group_id,
        'clients': existing_clients
    })

    if result and 'result' in result:
        print(f"✅ Joined {args.client} to {args.target}'s group")
        print(f"   Both clients are now in the same group with source: {target_source}")
        show_status(gm)
        return 0
    else:
        print(f"❌ Failed to join {args.client}")
        return 1

def cmd_separate(args):
    """Move a client to its own group (back to home group)"""
    cm = ConfigManager()
    gm = SnapcastGroupManager(config_manager=cm)

    print(f"\n🔀 Separating {args.client} to its own group...")

    # Find client in server config
    client_dict = None
    for client in cm.server_config.get('clients', []):
        if client.get('id') == args.client:
            client_dict = client
            break

    if not client_dict:
        print(f"❌ Client {args.client} not found in config")
        return 1

    home_source = client_dict.get('home_source')

    # Use the ensure_client_home_assignment function to move client to its own group
    if gm.ensure_client_home_assignment(args.client, home_source, dry_run=False):
        print(f"✅ Separated {args.client} to its own group")
        show_status(gm)
        return 0
    else:
        print(f"❌ Failed to separate {args.client}")
        return 1

def cmd_reset(args):
    """Reset all clients to their home groups"""
    cm = ConfigManager()

    if args.client:
        print(f"\n🏠 Resetting {args.client} to home group...")
    else:
        print(f"\n🏠 Resetting ALL clients to their home groups...")

    if args.client:
        # Reset specific client
        gm = SnapcastGroupManager(config_manager=cm)

        # Find client in server config
        client_dict = None
        for client in cm.server_config.get('clients', []):
            if client.get('id') == args.client:
                client_dict = client
                break

        if not client_dict:
            print(f"❌ Client {args.client} not found")
            return 1

        home_source = client_dict.get('home_source')
        if gm.ensure_client_home_assignment(args.client, home_source, dry_run=False):
            print(f"✅ Reset {args.client} to home group")
            show_status(gm)
            return 0
        else:
            print(f"❌ Failed to reset {args.client}")
            return 1
    else:
        # Reset all clients
        if assign_all_clients_to_home(cm, dry_run=False):
            print("✅ All clients reset to home groups")
            gm = SnapcastGroupManager()
            show_status(gm)
            return 0
        else:
            print("❌ Some resets failed")
            return 1

def main():
    parser = argparse.ArgumentParser(
        description="Test multiroom group management (emulates future UI)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show current group status
  python3 test_multiroom.py show

  # Join fauxnos001 to fauxnos000's group (multiroom sync)
  python3 test_multiroom.py join fauxnos001 --target fauxnos000

  # Separate fauxnos001 back to its own group
  python3 test_multiroom.py separate fauxnos001

  # Reset all clients to their home groups
  python3 test_multiroom.py reset

  # Reset specific client to home group
  python3 test_multiroom.py reset --client fauxnos001

Workflow:
  1. Use 'show' to see current groups
  2. Use 'join' to create multiroom groups
  3. Use 'separate' or 'reset' to ungroup
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Show command
    show_parser = subparsers.add_parser('show', help='Show current group configuration')
    show_parser.set_defaults(func=cmd_show)

    # Join command
    join_parser = subparsers.add_parser('join', help='Join a client to another client\'s group')
    join_parser.add_argument('client', help='Client ID to move (e.g., fauxnos001)')
    join_parser.add_argument('--target', required=True, help='Client ID to join with (e.g., fauxnos000)')
    join_parser.set_defaults(func=cmd_join)

    # Separate command
    separate_parser = subparsers.add_parser('separate', help='Move a client to its own group')
    separate_parser.add_argument('client', help='Client ID to separate (e.g., fauxnos001)')
    separate_parser.set_defaults(func=cmd_separate)

    # Reset command
    reset_parser = subparsers.add_parser('reset', help='Reset clients to home groups')
    reset_parser.add_argument('--client', help='Specific client to reset (default: all clients)')
    reset_parser.set_defaults(func=cmd_reset)

    args = parser.parse_args()

    if not hasattr(args, 'func'):
        parser.print_help()
        return 1

    return args.func(args)

if __name__ == '__main__':
    sys.exit(main())
