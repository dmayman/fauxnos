#!/usr/bin/env python3
"""
Volume Manager

Monitors go-librespot WebSocket events and syncs volume to snapcast clients.
Uses WebSocket /events endpoint for instant volume change notifications.

For now, implements simple 1:1 volume mirroring.
Future: Add proportional group volume scaling.
"""

import json
import threading
import logging
import asyncio
import websockets
from typing import Dict, Optional
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

    def start(self):
        """Start WebSocket listeners for all clients"""
        if self.running:
            self.logger.warning("Volume manager already running")
            return

        self.running = True
        clients = self.config_manager.list_clients()

        for client in clients:
            # Start a thread for each client's WebSocket connection
            thread = threading.Thread(
                target=self._run_websocket_listener,
                args=(client.id, client.server_port),
                daemon=True
            )
            thread.start()
            self.threads.append(thread)

        self.logger.info(f"Volume manager started for {len(clients)} clients")

    def stop(self):
        """Stop all WebSocket listeners"""
        if not self.running:
            return

        self.running = False

        # Wait for threads to finish
        for thread in self.threads:
            thread.join(timeout=2.0)

        self.threads = []
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
                    # Volume changed by at least 1% - update snapcast
                    if self._set_snapcast_volume(client_id, normalized_volume):
                        self.logger.info(
                            f"Updated {client_id} volume: {last_volume}% → {normalized_volume}%"
                        )
                        self.last_volumes[client_id] = normalized_volume

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
