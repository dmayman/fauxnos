#!/usr/bin/env python3
"""
Configuration Manager for Fauxnos Client

Handles loading, validation, and management of client configuration from YAML files.
"""

import yaml
import logging
from dataclasses import dataclass
from typing import Dict, List, Any, Optional
from pathlib import Path


@dataclass
class DeviceConfig:
    """Device identification and settings"""
    name: str
    mac: str
    display_name: Optional[str] = None


@dataclass
class ExternalSwitchConfig:
    """Configuration for external source switches"""
    enabled: bool
    url: str
    payload: Dict[str, Any]
    content_type: str = 'json'  # 'json' or 'form'


@dataclass
class SourceConfig:
    """Audio source configuration"""
    id: str
    label: str
    type: str  # 'internal' or 'external'
    starting_volume: int = 50

    # Internal source fields
    sink: Optional[str] = None
    volume_controller: str = 'self'  # 'self', 'snapcast', or 'go_librespot'
    external_switch: Optional[ExternalSwitchConfig] = None

    # PulseAudio loopback calibration (0-100). Applied to the
    # <sink>.monitor → alsa_output loopback as a fixed pre-amp ceiling.
    # Lets the user normalize different sources (Spotify-via-snapcast vs
    # Analog vs AirPlay) without violating the single-stage user-control
    # rule. See docs/VOLUME.md. Default 100 = no attenuation.
    pa_calibration: int = 100

    # External source fields
    control_url: Optional[str] = None
    control_payload: Optional[Dict[str, Any]] = None


@dataclass
class LoggingConfig:
    """Logging configuration"""
    file: str
    level: str = 'INFO'


class ConfigManager:
    """Manages client configuration from YAML files"""

    def __init__(self, config_file: str = None):
        """
        Initialize configuration manager

        Args:
            config_file: Path to YAML config file. Defaults to ~/.config/fauxnos/client_config.yaml
        """
        self.logger = logging.getLogger(__name__)

        if config_file is None:
            config_file = Path.home() / ".config" / "fauxnos" / "client_config.yaml"

        self.config_file = Path(config_file)
        self.config = self._load_config()

        # Parse configuration into structured objects
        self.device_config = self._parse_device_config()
        self.sources = self._parse_sources()
        self.logging_config = self._parse_logging_config()
        self.state_file = self._parse_state_file()
        self.server_host = self.config.get('server_host', 'fauxnos000.local')
        self.go_librespot_host, self.go_librespot_port = self._parse_go_librespot_endpoint()

    def _load_config(self) -> Dict[str, Any]:
        """Load YAML configuration file"""
        if not self.config_file.exists():
            raise FileNotFoundError(
                f"Config file not found: {self.config_file}\n"
                f"Please create a config file or run config-wizard"
            )

        try:
            with open(self.config_file, 'r') as f:
                config = yaml.safe_load(f)

            if not config:
                raise ValueError("Config file is empty")

            return config

        except yaml.YAMLError as e:
            raise ValueError(f"Error parsing YAML config: {e}")
        except Exception as e:
            raise ValueError(f"Error loading config: {e}")

    def _parse_device_config(self) -> DeviceConfig:
        """Parse device configuration section"""
        device = self.config.get('device', {})

        if not device.get('name'):
            raise ValueError("device.name is required in config")
        if not device.get('mac'):
            raise ValueError("device.mac is required in config")

        return DeviceConfig(
            name=device['name'],
            mac=device['mac'],
            display_name=device.get('display_name', device['name'].title())
        )

    def _parse_sources(self) -> Dict[str, SourceConfig]:
        """Parse sources configuration"""
        sources_list = self.config.get('sources', [])

        if not sources_list:
            raise ValueError("At least one source is required in config")

        sources = {}

        for source_data in sources_list:
            source_id = source_data.get('id')
            if not source_id:
                raise ValueError("Each source must have an 'id' field")

            source_type = source_data.get('type')
            if source_type not in ['internal', 'external']:
                raise ValueError(f"Source {source_id}: type must be 'internal' or 'external'")

            # Parse external switch config if present
            external_switch = None
            if 'external_switch' in source_data:
                ext_switch_data = source_data['external_switch']
                if ext_switch_data.get('enabled', False):
                    external_switch = ExternalSwitchConfig(
                        enabled=True,
                        url=ext_switch_data.get('url', ''),
                        payload=ext_switch_data.get('payload', {}),
                        content_type=ext_switch_data.get('content_type', 'json')
                    )

            # Validate internal source fields
            if source_type == 'internal':
                if not source_data.get('sink'):
                    raise ValueError(f"Internal source {source_id}: 'sink' field is required")

                volume_controller = source_data.get('volume_controller', 'self')
                if volume_controller not in ['self', 'snapcast', 'go_librespot']:
                    raise ValueError(
                        f"Source {source_id}: volume_controller must be "
                        f"'self', 'snapcast', or 'go_librespot'"
                    )

            # Create source config
            sources[source_id] = SourceConfig(
                id=source_id,
                label=source_data.get('label', source_id.title()),
                type=source_type,
                starting_volume=source_data.get('starting_volume', 50),
                sink=source_data.get('sink'),
                volume_controller=source_data.get('volume_controller', 'self'),
                external_switch=external_switch,
                pa_calibration=int(source_data.get('pa_calibration', 100)),
                control_url=source_data.get('control_url'),
                control_payload=source_data.get('control_payload')
            )

        return sources

    def _parse_logging_config(self) -> LoggingConfig:
        """Parse logging configuration"""
        logging_data = self.config.get('logging', {})

        log_file = logging_data.get('file', '~/logs/fauxnos-client.log')
        log_level = logging_data.get('level', 'INFO')

        # Expand ~ in path
        log_file = str(Path(log_file).expanduser())

        return LoggingConfig(file=log_file, level=log_level)

    def _parse_state_file(self) -> Path:
        """Parse state file path"""
        state_file = self.config.get('state_file', '~/.config/fauxnos/client_state.json')
        return Path(state_file).expanduser()

    def _parse_go_librespot_endpoint(self) -> (str, int):
        """
        Resolve where the client's go-librespot daemon listens for
        HTTP + WebSocket. Convention: go-librespot runs ON THE SERVER
        (one instance per client), each on `3600 + N` where N is the
        client number parsed from `fauxnos<NNN>`. Host is the fauxnos
        server. An explicit `go_librespot:` block in YAML overrides
        either field — useful for unusual topologies or testing.

        Falls back to (server_host, 3600) if the device name doesn't
        match the fauxnosNNN convention so the client still boots; in
        that case spotify-controlled volume just won't work until the
        operator fills in the override.
        """
        override = self.config.get('go_librespot', {}) or {}

        # Derive port from device name suffix: fauxnos001 → 3601.
        derived_port = 3600
        name = self.device_config.name
        if name.startswith('fauxnos') and name[7:].isdigit():
            derived_port = 3600 + int(name[7:])

        host = override.get('host', self.server_host)
        port = int(override.get('port', derived_port))
        return host, port

    def get_source(self, source_id: str) -> Optional[SourceConfig]:
        """Get source configuration by ID"""
        return self.sources.get(source_id)

    def get_internal_sources(self) -> Dict[str, SourceConfig]:
        """Get all internal sources"""
        return {
            source_id: source
            for source_id, source in self.sources.items()
            if source.type == 'internal'
        }

    def get_external_sources(self) -> Dict[str, SourceConfig]:
        """Get all external sources"""
        return {
            source_id: source
            for source_id, source in self.sources.items()
            if source.type == 'external'
        }

    def validate(self) -> List[str]:
        """
        Validate configuration

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        # Check device config
        try:
            self._parse_device_config()
        except ValueError as e:
            errors.append(f"Device config error: {e}")

        # Check sources
        try:
            sources = self._parse_sources()
            if not sources:
                errors.append("No sources defined")
        except ValueError as e:
            errors.append(f"Sources config error: {e}")

        # Check for duplicate source IDs
        source_ids = [s.get('id') for s in self.config.get('sources', [])]
        duplicates = [sid for sid in source_ids if source_ids.count(sid) > 1]
        if duplicates:
            errors.append(f"Duplicate source IDs: {set(duplicates)}")

        return errors


# Standalone testing
if __name__ == '__main__':
    import sys

    config_file = sys.argv[1] if len(sys.argv) > 1 else None

    try:
        cm = ConfigManager(config_file)
        print(f"Configuration loaded successfully!")
        print(f"Device: {cm.device_config.display_name} ({cm.device_config.name})")
        print(f"MAC: {cm.device_config.mac}")
        print(f"\nSources ({len(cm.sources)}):")
        for source_id, source in cm.sources.items():
            print(f"  - {source.label} ({source_id})")
            print(f"    Type: {source.type}")
            if source.type == 'internal':
                print(f"    Sink: {source.sink}")
                print(f"    Volume Controller: {source.volume_controller}")

        # Validation
        errors = cm.validate()
        if errors:
            print("\nValidation errors:")
            for error in errors:
                print(f"  - {error}")
        else:
            print("\nConfiguration is valid!")

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
