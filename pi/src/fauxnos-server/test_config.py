#!/usr/bin/env python3
"""
Test script to debug config manager save issues
"""

from modules.config_manager import ConfigManager

print("Testing ConfigManager...")

# Create config manager
cm = ConfigManager()
print(f'Before: {len(cm.server_config.get("clients", []))} clients')

# Add a test client
try:
    client = cm.add_client('Test Client', 'aa:bb:cc:dd:ee:ff')
    print(f'After add: {len(cm.server_config.get("clients", []))} clients')
    print(f'Added client: {client.id} ({client.name})')
except Exception as e:
    print(f'Error adding client: {e}')
    exit(1)

# Try to save
try:
    cm.save_server_config()
    print('Save completed successfully')
except Exception as e:
    print(f'Error saving config: {e}')
    exit(1)

# Verify save by reloading
try:
    cm2 = ConfigManager()
    print(f'After reload: {len(cm2.server_config.get("clients", []))} clients')
    if cm2.server_config.get("clients"):
        for client in cm2.server_config["clients"]:
            print(f'  - {client["id"]} ({client["name"]})')
except Exception as e:
    print(f'Error reloading config: {e}')

print('Test completed')