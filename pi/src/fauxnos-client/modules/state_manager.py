#!/usr/bin/env python3
"""
State Manager

Handles persistence of client state (current source, source volumes)
"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional
import tempfile
import os


class StateManager:
    """Manages persistent state for the Fauxnos client"""

    def __init__(self, state_file: Path):
        """
        Initialize state manager

        Args:
            state_file: Path to state file
        """
        self.logger = logging.getLogger(__name__)
        self.state_file = Path(state_file).expanduser()

        # Create parent directory if it doesn't exist
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    def save_state(self, current_source: Optional[str], source_volumes: Dict[str, int]) -> bool:
        """
        Save current state to file

        Args:
            current_source: ID of currently active source (or None)
            source_volumes: Dict mapping source_id → volume level

        Returns:
            True if successful, False otherwise
        """
        try:
            state = {
                'current_source': current_source,
                'source_volumes': source_volumes
            }

            # Write to temporary file first (atomic write)
            temp_fd, temp_path = tempfile.mkstemp(
                dir=self.state_file.parent,
                prefix='.state_',
                suffix='.tmp'
            )

            with os.fdopen(temp_fd, 'w') as f:
                json.dump(state, f, indent=2)

            # Move temporary file to actual state file (atomic on most systems)
            os.replace(temp_path, self.state_file)

            self.logger.debug(f"State saved: source={current_source}")
            return True

        except Exception as e:
            self.logger.error(f"Error saving state: {e}")
            # Clean up temp file if it exists
            try:
                if 'temp_path' in locals():
                    os.remove(temp_path)
            except:
                pass
            return False

    def load_state(self) -> Dict:
        """
        Load state from file

        Returns:
            Dict with 'current_source' and 'source_volumes' keys
            Returns empty state if file doesn't exist or has errors
        """
        # Default empty state
        empty_state = {
            'current_source': None,
            'source_volumes': {}
        }

        if not self.state_file.exists():
            self.logger.info(f"No state file found at {self.state_file}")
            return empty_state

        try:
            with open(self.state_file, 'r') as f:
                state = json.load(f)

            # Validate structure
            if 'current_source' not in state or 'source_volumes' not in state:
                self.logger.warning("State file has invalid structure, using empty state")
                return empty_state

            self.logger.info(f"State loaded: source={state['current_source']}")
            return state

        except json.JSONDecodeError as e:
            self.logger.error(f"Error parsing state file: {e}")
            return empty_state
        except Exception as e:
            self.logger.error(f"Error loading state: {e}")
            return empty_state

    def clear_state(self) -> bool:
        """
        Delete state file

        Returns:
            True if successful, False otherwise
        """
        try:
            if self.state_file.exists():
                self.state_file.unlink()
                self.logger.info("State file cleared")
                return True
            else:
                self.logger.info("No state file to clear")
                return True

        except Exception as e:
            self.logger.error(f"Error clearing state: {e}")
            return False

    def get_current_source(self) -> Optional[str]:
        """
        Get just the current source from saved state

        Returns:
            Source ID or None
        """
        state = self.load_state()
        return state.get('current_source')

    def get_source_volumes(self) -> Dict[str, int]:
        """
        Get just the source volumes from saved state

        Returns:
            Dict mapping source_id → volume
        """
        state = self.load_state()
        return state.get('source_volumes', {})


# Standalone testing
if __name__ == '__main__':
    import argparse

    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    parser = argparse.ArgumentParser(description='Test State Manager')
    parser.add_argument('command', choices=['save', 'load', 'clear'])
    parser.add_argument('--state-file', default='/tmp/fauxnos-client-test-state.json',
                        help='State file path')
    parser.add_argument('--source', help='Current source ID for save')
    parser.add_argument('--volumes', help='Source volumes JSON for save (e.g., \'{"spotify": 50, "analog": 30}\')')

    args = parser.parse_args()

    manager = StateManager(Path(args.state_file))

    if args.command == 'save':
        if not args.source:
            print("Error: --source required for save")
        else:
            volumes = {}
            if args.volumes:
                try:
                    volumes = json.loads(args.volumes)
                except json.JSONDecodeError:
                    print("Error: --volumes must be valid JSON")
                    exit(1)

            if manager.save_state(args.source, volumes):
                print(f"✓ State saved to {args.state_file}")
            else:
                print("✗ Failed to save state")

    elif args.command == 'load':
        state = manager.load_state()
        print(f"Current source: {state['current_source']}")
        print(f"Source volumes: {json.dumps(state['source_volumes'], indent=2)}")

    elif args.command == 'clear':
        if manager.clear_state():
            print(f"✓ State file cleared")
        else:
            print("✗ Failed to clear state")
