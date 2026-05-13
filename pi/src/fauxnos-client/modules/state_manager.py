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

    def save_state(
        self,
        current_source: Optional[str],
        source_volumes: Dict[str, int],
        pa_calibrations: Optional[Dict[str, int]] = None,
        ir: Optional[Dict] = None,
    ) -> bool:
        """
        Save current state to file

        Args:
            current_source: ID of currently active source (or None)
            source_volumes: Dict mapping source_id → volume level
            pa_calibrations: Dict mapping source_id → PA loopback
                calibration percent (override of YAML's pa_calibration).
                Optional — if None, existing on-disk value is preserved.
            ir: Hardware-remote state block:
                {"enabled": bool, "mappings": {cmd_id: {"protocol", "scancode"} | None}}.
                Optional — if None, existing on-disk value is preserved.

        Returns:
            True if successful, False otherwise
        """
        try:
            # Preserve existing pa_calibrations if caller didn't pass one.
            # Otherwise we'd wipe them on every save_state(current_source, ...) call.
            existing_raw = self._load_raw()
            if pa_calibrations is None:
                pa_calibrations = existing_raw.get('pa_calibrations', {})
            if ir is None:
                ir = existing_raw.get('ir', {'enabled': False, 'mappings': {}})

            state = {
                'current_source': current_source,
                'source_volumes': source_volumes,
                'pa_calibrations': pa_calibrations,
                'ir': ir,
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

    def _load_raw(self) -> Dict:
        """Load raw state dict (no validation, no defaults). Used to merge new fields."""
        if not self.state_file.exists():
            return {}
        try:
            with open(self.state_file, 'r') as f:
                return json.load(f) or {}
        except Exception:
            return {}

    def get_pa_calibration(self, source_id: str) -> Optional[int]:
        """
        Get persisted PA loopback calibration for a source. Returns None
        if not set in state (caller should fall back to YAML default).
        """
        state = self.load_state()
        cals = state.get('pa_calibrations', {}) or {}
        v = cals.get(source_id)
        if v is None:
            return None
        try:
            return max(0, min(200, int(v)))
        except (TypeError, ValueError):
            return None

    def set_pa_calibration(self, source_id: str, value: int) -> bool:
        """
        Persist a single source's PA loopback calibration. Other state
        fields are preserved. Range: 0-200 (100 = unity, >100 = boost).
        """
        state = self.load_state()
        cals = dict(state.get('pa_calibrations', {}) or {})
        cals[source_id] = max(0, min(200, int(value)))
        return self.save_state(
            current_source=state.get('current_source'),
            source_volumes=state.get('source_volumes', {}),
            pa_calibrations=cals,
        )

    # --- IR (hardware remote) state ---
    #
    # Shape on disk:
    #   "ir": {
    #     "enabled": bool,
    #     "mappings": {
    #       "volume_up": {"protocol": "nec", "scancode": "0x1FE807F"},
    #       "volume_down": null,
    #       ...
    #     }
    #   }
    # mappings entries are either None (unlearned) or a 2-key dict.

    # Default feedback volume for the IR remote's per-notch sounds.
    # Tuned 2026-05-10 after the unattenuated 100% on fauxnos000 was
    # painfully loud. Each surface (paplay --volume) scales linearly,
    # so 30% is roughly -10 dB from full scale.
    IR_FEEDBACK_VOLUME_DEFAULT = 30

    def get_ir(self) -> Dict:
        """Return the full ir block, with empty defaults if absent."""
        state = self.load_state()
        ir = state.get('ir') or {}
        return {
            'enabled': bool(ir.get('enabled', False)),
            'mappings': dict(ir.get('mappings') or {}),
            'feedback_volume': self._clamp_vol(
                ir.get('feedback_volume', self.IR_FEEDBACK_VOLUME_DEFAULT)
            ),
        }

    @staticmethod
    def _clamp_vol(v) -> int:
        try:
            return max(0, min(100, int(v)))
        except (TypeError, ValueError):
            return StateManager.IR_FEEDBACK_VOLUME_DEFAULT

    def set_ir_enabled(self, enabled: bool) -> bool:
        """Toggle the IR feature flag, preserving the mapping table."""
        state = self.load_state()
        ir = state.get('ir') or {'enabled': False, 'mappings': {}}
        ir['enabled'] = bool(enabled)
        return self.save_state(
            current_source=state.get('current_source'),
            source_volumes=state.get('source_volumes', {}),
            pa_calibrations=state.get('pa_calibrations', {}),
            ir=ir,
        )

    def set_ir_feedback_volume(self, volume_pct: int) -> bool:
        """Persist the per-notch sound playback volume (0-100)."""
        state = self.load_state()
        ir = state.get('ir') or {'enabled': False, 'mappings': {}}
        ir['feedback_volume'] = self._clamp_vol(volume_pct)
        return self.save_state(
            current_source=state.get('current_source'),
            source_volumes=state.get('source_volumes', {}),
            pa_calibrations=state.get('pa_calibrations', {}),
            ir=ir,
        )

    def set_ir_mapping(self, command_id: str, protocol: Optional[str],
                       scancode: Optional[str]) -> bool:
        """
        Set (or clear) a single command's IR mapping. Pass protocol=None
        and scancode=None to clear. Other commands' mappings are
        preserved.
        """
        state = self.load_state()
        ir = state.get('ir') or {'enabled': False, 'mappings': {}}
        mappings = dict(ir.get('mappings') or {})
        if protocol is None or scancode is None:
            mappings[command_id] = None
        else:
            mappings[command_id] = {
                'protocol': str(protocol),
                # Normalize to lowercase 0x... form so equality matches
                # whatever the listener parses out of ir-keytable output.
                'scancode': str(scancode).lower(),
            }
        ir['mappings'] = mappings
        return self.save_state(
            current_source=state.get('current_source'),
            source_volumes=state.get('source_volumes', {}),
            pa_calibrations=state.get('pa_calibrations', {}),
            ir=ir,
        )

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
            'source_volumes': {},
            'pa_calibrations': {},
            'ir': {'enabled': False, 'mappings': {}},
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

            # pa_calibrations + ir were added later — fill in if missing
            state.setdefault('pa_calibrations', {})
            state.setdefault('ir', {'enabled': False, 'mappings': {}})

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
