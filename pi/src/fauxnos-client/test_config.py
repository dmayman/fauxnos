#!/usr/bin/env python3
"""
Test the configuration system for fauxnos-client
"""

import yaml
import json
from pathlib import Path

def test_config_loading():
    """Test loading the config.yaml file"""

    # Check template exists
    template_path = Path(__file__).parent / "configs" / "config.yaml.template"
    print(f"✓ Template exists: {template_path.exists()} at {template_path}")

    # Check if populated config exists
    config_path = Path.home() / "src" / "fauxnos-client" / "config.yaml"
    print(f"✓ Config exists: {config_path.exists()} at {config_path}")

    if config_path.exists():
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        # Check key fields
        client_id = config.get('client_id', '')
        display_name = config.get('display_name', '')
        mac = config.get('mac', '')

        print(f"\nConfig Contents:")
        print(f"  Client ID: {client_id if client_id else '(not set)'}")
        print(f"  Display Name: {display_name if display_name else '(not set)'}")
        print(f"  MAC Address: {mac if mac else '(not set)'}")

        if client_id and display_name and mac:
            print("\n✅ Config is fully populated!")
        else:
            print("\n⚠️  Config exists but is not fully populated. Run setup-client.py to complete.")
    else:
        print("\n⚠️  No config file found. Run setup-client.py first.")

if __name__ == "__main__":
    test_config_loading()