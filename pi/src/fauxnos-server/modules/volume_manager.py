#!/usr/bin/env python3
"""
Volume Manager

Monitors go-librespot WebSocket events and syncs volume to snapcast clients.
Uses WebSocket /events endpoint for instant volume change notifications.

For now, implements simple 1:1 volume mirroring.
Future: Add proportional group volume scaling.
"""

import json
import os
import threading
import logging
import asyncio
import websockets
import yaml
from pathlib import Path
from typing import Dict, Optional
import paho.mqtt.client as mqtt
from .config_manager import ConfigManager
from .group_manager import SnapcastGroupManager


class VolumeManager:
    def __init__(self, config_manager: ConfigManager):
        """
        Initialize volume manager

        Args:
            config_manager: ConfigManager instance
        """
        self.config_manager = config_manager
        self.group_manager = SnapcastGroupManager(config_manager=config_manager)
        self.running = False
        self.threads = []
        self.logger = logging.getLogger('VolumeManager')

        # Track last known volume for each client to detect changes
        self.last_volumes: Dict[str, int] = {}

        # MQTT publisher for status/clients/<id>/volume after applying changes.
        # Without this, a volume change driven by Spotify (Spotify app slider →
        # go-librespot WS event → snapcast Client.SetVolume) never reaches the
        # web UI, because the UI subscribes to status/clients/+/volume but
        # nothing publishes that topic on this code path. fauxnos_client.py's
        # mqtt_client publishes status only for UI-driven (set/...) commands.
        self.mqtt: Optional[mqtt.Client] = None
        self._init_mqtt()

    def _init_mqtt(self):
        """Connect to the MQTT broker for publishing status updates."""
        try:
            mqtt_cfg = self.config_manager.server_config.get('server', {}).get('mqtt', {})
            host = mqtt_cfg.get('broker_host', 'localhost')
            port = int(mqtt_cfg.get('broker_port', 1883))
            self.mqtt = mqtt.Client(client_id='fauxnos-volume-manager')
            self.mqtt.connect(host, port, keepalive=60)
            self.mqtt.loop_start()
            self.logger.info(f"VolumeManager MQTT publisher connected to {host}:{port}")
        except Exception as e:
            self.logger.warning(f"VolumeManager MQTT connect failed (status updates won't reach UI): {e}")
            self.mqtt = None

    def _publish_volume_status(self, client_id: str, volume: int):
        """Publish status/clients/<client_id>/volume so UI subscribers see the change."""
        if self.mqtt is None:
            return
        try:
            topic = f"status/clients/{client_id}/volume"
            self.mqtt.publish(topic, str(volume))
        except Exception as e:
            self.logger.warning(f"MQTT publish failed for {client_id}: {e}")

    def start(self):
        """Start WebSocket listeners for all clients.

        Skips any client whose go-librespot config has
        `volume_steps: 100` — that's the marker of a single-stage
        client (brief_spotify_volume_sync.md). On those clients,
        fauxnos-client owns the WS event flow end-to-end:
        - phone slider → go-librespot WS → fauxnos client →
          snapcast Client.SetVolume + source_manager state save +
          MQTT publish.
        - fauxnos-client's volume_controller=go_librespot already
          calls snapcast.set_volume(N) on every drag, so this server-
          side mirror would just re-issue the same Client.SetVolume
          with the same value — at best redundant chatter; at worst
          races with the client's write or, paired with an earlier
          mid-development design that pinned snapcast=100 between
          drags, caused an audible UP-then-DOWN blip on every UI move
          (bug discovered 2026-05-11 on fauxnos000).
        """
        if self.running:
            self.logger.warning("Volume manager already running")
            return

        self.running = True
        clients = self.config_manager.list_clients()

        started = 0
        skipped = 0
        for client in clients:
            if self._client_is_single_stage(client.id):
                self.logger.info(
                    f"VolumeManager: skipping {client.id} — single-stage "
                    f"(volume_steps:100); fauxnos-client owns WS flow"
                )
                skipped += 1
                continue
            thread = threading.Thread(
                target=self._run_websocket_listener,
                args=(client.id, client.server_port),
                daemon=True
            )
            thread.start()
            self.threads.append(thread)
            started += 1

        self.logger.info(
            f"Volume manager started for {started} client(s), "
            f"skipped {skipped} single-stage client(s)"
        )

    def _client_is_single_stage(self, client_id: str) -> bool:
        """Return True if this client's go-librespot config has
        `volume_steps: 100` — the marker we write when the client is
        in single-stage spotify mode. Best-effort: any read error or
        missing file is treated as 'not single-stage' so we fall back
        to the old mirroring behavior."""
        cfg_path = Path.home() / ".config" / "go-librespot" / client_id / "config.yml"
        try:
            cfg = yaml.safe_load(cfg_path.read_text()) or {}
            return cfg.get('volume_steps') == 100
        except Exception:
            return False

    def stop(self):
        """Stop all WebSocket listeners"""
        if not self.running:
            return

        self.running = False

        # Wait for threads to finish
        for thread in self.threads:
            thread.join(timeout=2.0)

        self.threads = []

        # Tear down the MQTT publisher
        if self.mqtt is not None:
            try:
                self.mqtt.loop_stop()
                self.mqtt.disconnect()
            except Exception:
                pass
            self.mqtt = None

        self.logger.info("Volume manager stopped")

    def _run_websocket_listener(self, client_id: str, server_port: int):
        """
        Run asyncio event loop for WebSocket listener

        Args:
            client_id: Client ID
            server_port: Go-librespot server port
        """
        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            loop.run_until_complete(self._websocket_listener(client_id, server_port))
        except Exception as e:
            self.logger.error(f"WebSocket listener error for {client_id}: {e}")
        finally:
            loop.close()

    async def _websocket_listener(self, client_id: str, server_port: int):
        """
        Listen to WebSocket events from go-librespot

        Args:
            client_id: Client ID
            server_port: Go-librespot server port
        """
        ws_url = f"ws://localhost:{server_port}/events"
        retry_delay = 5  # Seconds between connection attempts

        self.logger.info(f"Starting WebSocket listener for {client_id} on {ws_url}")

        while self.running:
            try:
                async with websockets.connect(ws_url, ping_interval=20, ping_timeout=10) as websocket:
                    self.logger.info(f"WebSocket connected for {client_id}")

                    async for message in websocket:
                        if not self.running:
                            break

                        try:
                            event = json.loads(message)
                            await self._handle_event(client_id, event)
                        except json.JSONDecodeError as e:
                            self.logger.error(f"Failed to parse event from {client_id}: {e}")
                        except Exception as e:
                            self.logger.error(f"Error handling event for {client_id}: {e}")

            except websockets.exceptions.WebSocketException as e:
                if self.running:
                    self.logger.warning(f"WebSocket disconnected for {client_id}: {e}")
                    self.logger.info(f"Reconnecting to {client_id} in {retry_delay}s...")
                    await asyncio.sleep(retry_delay)
            except Exception as e:
                if self.running:
                    self.logger.error(f"WebSocket error for {client_id}: {e}")
                    await asyncio.sleep(retry_delay)

        self.logger.info(f"WebSocket listener stopped for {client_id}")

    async def _handle_event(self, client_id: str, event: dict):
        """
        Handle WebSocket event from go-librespot

        Args:
            client_id: Client ID
            event: Event data from WebSocket
        """
        # Check if this is a volume change event
        # Format: {"type": "volume", "data": {"value": X, "max": 100}}
        if event.get('type') == 'volume' and 'data' in event:
            data = event['data']
            volume_value = data.get('value', 0)
            volume_max = data.get('max', 100)

            # Normalize to 0-100 range
            if volume_max > 0:
                normalized_volume = int((volume_value / volume_max) * 100)
                normalized_volume = max(0, min(100, normalized_volume))

                # Check if volume actually changed
                last_volume = self.last_volumes.get(client_id)

                if last_volume is None or abs(normalized_volume - last_volume) >= 1:
                    # Volume changed by at least 1% - check if we need group or individual control
                    if self._apply_volume_change(client_id, normalized_volume):
                        self.logger.info(
                            f"Updated {client_id} volume: {last_volume}% → {normalized_volume}%"
                        )
                        self.last_volumes[client_id] = normalized_volume
                        # Mirror the new volume to MQTT so the web UI's volume
                        # slider follows along in real time.
                        self._publish_volume_status(client_id, normalized_volume)

    def _apply_volume_change(self, client_id: str, volume: int) -> bool:
        """
        Apply volume change - either to individual client or to whole group

        Args:
            client_id: Client ID that received the volume change
            volume: Target volume (0-100)

        Returns:
            True if successful
        """
        try:
            # Get current snapcast status to find this client's group
            status = self.group_manager.send_snapcast_command('Server.GetStatus', {})
            if not status or 'result' not in status:
                self.logger.error("Failed to get snapcast status")
                return self._set_snapcast_volume(client_id, volume)

            server_status = status['result']['server']
            groups = server_status.get('groups', [])

            # Find which group this client belongs to
            client_group = None
            for group in groups:
                for client in group.get('clients', []):
                    if client.get('id') == client_id:
                        client_group = group
                        break
                if client_group:
                    break

            if not client_group:
                self.logger.warning(f"Client {client_id} not found in any group")
                return self._set_snapcast_volume(client_id, volume)

            # Check if group has multiple clients
            clients_in_group = client_group.get('clients', [])
            if len(clients_in_group) <= 1:
                # Single client in group - just set individual volume
                return self._set_snapcast_volume(client_id, volume)
            else:
                # Multiple clients - use proportional group volume scaling
                self.logger.info(f"Group has {len(clients_in_group)} clients, applying proportional scaling")
                return self._set_group_volume_proportional(client_group, volume)

        except Exception as e:
            self.logger.error(f"Error in _apply_volume_change: {e}")
            # Fallback to individual volume control
            return self._set_snapcast_volume(client_id, volume)

    def _set_group_volume_proportional(self, group: dict, target_volume: int) -> bool:
        """
        Set group volume using proportional scaling (preserves relative volumes)
        Based on snapweb's algorithm

        Args:
            group: Group dict from snapcast status
            target_volume: Target master volume (0-100)

        Returns:
            True if successful
        """
        try:
            clients = group.get('clients', [])
            if not clients:
                return False

            # Calculate current group average volume
            client_volumes = {}
            group_volume = 0

            for client in clients:
                client_id = client.get('id')
                client_volume = client.get('config', {}).get('volume', {}).get('percent', 0)
                client_volumes[client_id] = client_volume
                group_volume += client_volume

            group_volume /= len(clients)  # Average volume

            # Calculate delta and ratio (snapweb algorithm)
            delta = target_volume - group_volume

            if delta < 0:
                # Volume decreasing
                ratio = (group_volume - target_volume) / group_volume if group_volume > 0 else 0
            else:
                # Volume increasing
                ratio = (target_volume - group_volume) / (100 - group_volume) if group_volume < 100 else 0

            # Apply proportional scaling to each client
            success_count = 0
            for client in clients:
                client_id = client.get('id')
                original_volume = client_volumes[client_id]

                if delta < 0:
                    # Decrease volume proportionally
                    new_volume = original_volume - (ratio * original_volume)
                else:
                    # Increase volume proportionally
                    new_volume = original_volume + (ratio * (100 - original_volume))

                # Clamp to valid range
                new_volume = max(0, min(100, int(round(new_volume))))

                if self._set_snapcast_volume(client_id, new_volume):
                    self.logger.info(f"Scaled {client_id}: {original_volume}% → {new_volume}%")
                    # Update last known volume for this client
                    self.last_volumes[client_id] = new_volume
                    success_count += 1

            self.logger.info(f"Group volume scaled: {group_volume:.1f}% → {target_volume}% ({success_count}/{len(clients)} clients)")
            return success_count > 0

        except Exception as e:
            self.logger.error(f"Error in _set_group_volume_proportional: {e}")
            return False

    def _set_snapcast_volume(self, client_id: str, volume: int) -> bool:
        """
        Set snapcast client volume

        Args:
            client_id: Snapcast client ID
            volume: Volume level (0-100)

        Returns:
            True if successful
        """
        try:
            result = self.group_manager.send_snapcast_command('Client.SetVolume', {
                'id': client_id,
                'volume': {
                    'percent': volume,
                    'muted': False
                }
            })

            if result and 'result' in result:
                return True
            elif result and 'error' in result:
                self.logger.error(f"Snapcast error setting volume for {client_id}: {result['error']}")
                return False
            else:
                return False

        except Exception as e:
            self.logger.error(f"Error setting snapcast volume for {client_id}: {e}")
            return False


# Standalone mode for testing
if __name__ == '__main__':
    import time

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    cm = ConfigManager()
    vm = VolumeManager(cm)

    try:
        vm.start()
        print("Volume manager running... Press Ctrl+C to stop")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
        vm.stop()
