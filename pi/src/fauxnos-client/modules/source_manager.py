#!/usr/bin/env python3
"""
Source Manager

Handles audio source switching with smart volume control routing
"""

import logging
import requests
from typing import Dict, Optional
from .config_manager import ConfigManager, SourceConfig
from .pulse_controller import PulseAudioController
from .snapcast_controller import SnapcastController
from .state_manager import StateManager


class SourceManager:
    """Manages audio source switching and volume control"""

    def __init__(self, config_manager: ConfigManager):
        """
        Initialize source manager

        Args:
            config_manager: ConfigManager instance
        """
        self.logger = logging.getLogger(__name__)
        self.config_manager = config_manager

        # Initialize controllers
        self.pulse = PulseAudioController()
        self.snapcast = SnapcastController(host=config_manager.server_host)
        self.state_manager = StateManager(config_manager.state_file)

        # Track current source and volumes
        self.current_source: Optional[str] = None
        self.source_volumes: Dict[str, int] = {}

        # Initialize volumes from config
        for source_id, source in config_manager.sources.items():
            self.source_volumes[source_id] = source.starting_volume

        # Try to load previous state
        self._load_state()

    def _load_state(self):
        """Load previous state from disk"""
        state = self.state_manager.load_state()

        # Restore source volumes
        saved_volumes = state.get('source_volumes', {})
        for source_id, volume in saved_volumes.items():
            if source_id in self.source_volumes:
                self.source_volumes[source_id] = volume

        # Note: Don't restore current_source yet - let initialization do that
        self.logger.info(f"Restored {len(saved_volumes)} source volumes from state")

    def _save_state(self):
        """Save current state to disk"""
        self.state_manager.save_state(self.current_source, self.source_volumes)

    def switch_source(self, source_id: str) -> bool:
        """
        Switch to a different audio source

        Args:
            source_id: ID of source to switch to

        Returns:
            True if successful, False otherwise
        """
        # Validate source exists
        source = self.config_manager.get_source(source_id)
        if not source:
            self.logger.error(f"Source not found: {source_id}")
            return False

        # Check if already on this source
        if self.current_source == source_id:
            self.logger.debug(f"Already on source {source_id}, skipping switch")
            return True

        self.logger.info(f"Switching to source: {source.label} ({source_id})")

        # Handle external sources differently
        if source.type == 'external':
            return self._switch_to_external_source(source)
        else:
            return self._switch_to_internal_source(source)

    def _switch_to_internal_source(self, source: SourceConfig) -> bool:
        """
        Switch to internal source (PulseAudio-based)

        Args:
            source: Source configuration

        Returns:
            True if successful
        """
        # Step 1: Fade out all other internal sources
        self.logger.debug("Fading out other sources...")
        for other_id, other_source in self.config_manager.get_internal_sources().items():
            if other_id != source.id:
                self.pulse.mute_sink(other_source.sink)

        # Step 2: Fade in the new source with appropriate volume control
        target_volume = self.source_volumes[source.id]
        self._set_source_volume(source, target_volume, fade=True)

        # Step 3: Trigger external switch if configured
        if source.external_switch and source.external_switch.enabled:
            self._trigger_external_switch(source.external_switch.url, source.external_switch.payload, source.external_switch.content_type)

        # Update current source and save state
        self.current_source = source.id
        self._save_state()

        self.logger.info(f"Switched to {source.label}")
        return True

    def _switch_to_external_source(self, source: SourceConfig) -> bool:
        """
        Switch to external source (no local PulseAudio control)

        Args:
            source: Source configuration

        Returns:
            True if successful
        """
        # Mute all internal sources
        self.logger.debug("Muting all internal sources...")
        for source_id, internal_source in self.config_manager.get_internal_sources().items():
            self.pulse.mute_sink(internal_source.sink)

        # Trigger external source control
        if source.control_url:
            success = self._trigger_external_switch(source.control_url, source.control_payload)
            if not success:
                self.logger.warning(f"Failed to trigger external source {source.label}")

        # Update current source and save state
        self.current_source = source.id
        self._save_state()

        self.logger.info(f"Switched to external source: {source.label}")
        return True

    def _set_source_volume(self, source: SourceConfig, volume: int, fade: bool = False):
        """
        Set volume for a source using appropriate controller

        Args:
            source: Source configuration
            volume: Target volume (0-100)
            fade: Whether to fade to volume
        """
        if source.type != 'internal':
            self.logger.warning(f"Cannot set volume for external source {source.id}")
            return

        volume_controller = source.volume_controller
        sink_name = source.sink

        if volume_controller == 'self':
            # Use PulseAudio sink for volume control
            if fade:
                current_vol = self.pulse.get_sink_volume(sink_name) or 0
                self.pulse.fade_volume(sink_name, current_vol, volume)
            else:
                self.pulse.set_sink_volume(sink_name, volume)

            self.logger.debug(f"Set {source.label} volume to {volume}% (PA sink control)")

        elif volume_controller == 'snapcast':
            # Keep PA sink at 100%, control via snapcast
            if fade:
                current_vol = self.pulse.get_sink_volume(sink_name) or 0
                self.pulse.fade_volume(sink_name, current_vol, 100)
            else:
                self.pulse.set_sink_volume(sink_name, 100)

            # Use the device name as the snapcast client_id. We always launch
            # snapclient with `--hostID <device.name>` (e.g. fauxnos000), so
            # snapcast knows the client by that exact id. Looking up by MAC
            # was unreliable: install.sh records eth0's MAC in
            # server_config.json, but on a WiFi-attached Pi snapcast sees the
            # wlan0 MAC instead — and they differ on Pi 3B+/Zero 2 W.
            client_id = self.config_manager.device_config.name
            if self.snapcast.set_volume(volume, client_id):
                self.logger.debug(f"Set {source.label} volume to {volume}% (snapcast control, PA at 100%)")
            else:
                self.logger.warning(f"snapcast set_volume failed for client '{client_id}' — is it connected?")

        # Update stored volume
        self.source_volumes[source.id] = volume

    def set_volume(self, volume: int) -> bool:
        """
        Set volume for currently active source

        Args:
            volume: Target volume (0-100)

        Returns:
            True if successful
        """
        if not self.current_source:
            self.logger.error("No active source to set volume for")
            return False

        source = self.config_manager.get_source(self.current_source)
        if not source:
            self.logger.error(f"Current source not found: {self.current_source}")
            return False

        if source.type == 'external':
            self.logger.warning(f"Cannot control volume for external source {source.label}")
            return False

        # Set volume without fading
        self._set_source_volume(source, volume, fade=False)

        # Save state
        self._save_state()

        self.logger.info(f"Set {source.label} volume to {volume}%")
        return True

    def get_current_source(self) -> Optional[str]:
        """Get ID of currently active source"""
        return self.current_source

    def get_source_volume(self, source_id: str) -> Optional[int]:
        """Get stored volume for a source"""
        return self.source_volumes.get(source_id)

    def get_all_source_volumes(self) -> Dict[str, int]:
        """Get all source volumes"""
        return self.source_volumes.copy()

    def initialize_audio_system(self):
        """
        Initialize audio system on startup:
        - Mute all sinks
        - Load previous state or switch to first source
        """
        self.logger.info("Initializing audio system...")

        # Mute all internal sources
        for source_id, source in self.config_manager.get_internal_sources().items():
            self.pulse.mute_sink(source.sink)

        # Try to restore previous source or use first source
        saved_source = self.state_manager.get_current_source()

        if saved_source and saved_source in self.config_manager.sources:
            self.logger.info(f"Restoring previous source: {saved_source}")
            self.switch_source(saved_source)
        else:
            # Use first source as default
            first_source = list(self.config_manager.sources.keys())[0]
            self.logger.info(f"No previous source, using default: {first_source}")
            self.switch_source(first_source)

    def _trigger_external_switch(self, url: str, payload: Dict, content_type: str = 'json') -> bool:
        """
        Trigger external source switch via HTTP POST

        Args:
            url: Webhook URL
            payload: Payload to send
            content_type: 'json' or 'form'

        Returns:
            True if successful
        """
        try:
            self.logger.debug(f"Triggering external switch: {url} ({content_type})")
            if content_type == 'form':
                response = requests.post(url, data=payload, timeout=5)
            else:
                response = requests.post(url, json=payload, timeout=5)

            if response.status_code == 200:
                self.logger.debug("External switch triggered successfully")
                return True
            else:
                self.logger.warning(f"External switch returned status {response.status_code}")
                return False

        except requests.exceptions.Timeout:
            self.logger.error(f"Timeout triggering external switch: {url}")
            return False
        except Exception as e:
            self.logger.error(f"Error triggering external switch: {e}")
            return False


# Standalone testing
if __name__ == '__main__':
    import sys
    from pathlib import Path

    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    if len(sys.argv) < 2:
        print("Usage: python source_manager.py <config_file>")
        print("  Test source manager with a config file")
        sys.exit(1)

    config_file = sys.argv[1]

    try:
        # Load configuration
        cm = ConfigManager(config_file)
        print(f"✓ Configuration loaded")

        # Create source manager
        sm = SourceManager(cm)
        print(f"✓ Source manager initialized")

        # Initialize audio system
        sm.initialize_audio_system()
        print(f"✓ Audio system initialized")
        print(f"  Current source: {sm.current_source}")

        # Show available sources
        print("\nAvailable sources:")
        for source_id, source in cm.sources.items():
            vol = sm.get_source_volume(source_id)
            print(f"  - {source.label} ({source_id}): {vol}%")

        print("\nSource manager ready for testing")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
