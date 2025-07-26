#!/usr/bin/env python3
"""
Spotify DBUS Monitoring and Control
-----------------------------------
Handles spotifyd DBUS event monitoring and playerctl-based controls.
"""

import asyncio
import threading
import logging
import os
from dbus_next.aio import MessageBus
from dbus_next import Message
from dbus_next.constants import BusType

logger = logging.getLogger('AudioController')

class SpotifyMonitor:
    def __init__(self, source_switch_callback, volume_change_callback=None):
        self.source_switch_callback = source_switch_callback
        self.volume_change_callback = volume_change_callback
        self.spotifyd_thread = None
        self.spotifyd_stop_event = threading.Event()
        self.spotifyd_loop = None
        self.current_props = None  # Track current properties interface
        self.current_handler = None  # Track current handler function

    async def _find_spotifyd_name(self, bus):
        """Find spotifyd MPRIS bus name"""
        msg = Message(
            destination='org.freedesktop.DBus',
            path='/org/freedesktop/DBus',
            interface='org.freedesktop.DBus',
            member='ListNames'
        )
        reply = await bus.call(msg)
        names = reply.body[0]
        for name in names:
            if name.startswith('org.mpris.MediaPlayer2.spotifyd'):
                return name
        raise RuntimeError("spotifyd MPRIS bus name not found")

    async def _spotifyd_monitoring_loop(self):
        """Spotifyd DBUS event monitoring loop"""
        logger.info(f"🎵 Started spotifyd DBUS monitoring")
        
        bus = None
        
        while not self.spotifyd_stop_event.is_set():
            try:
                # Create bus connection only once per retry cycle
                if bus is None:
                    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
                
                # Try to find spotifyd
                try:
                    mpris_name = await self._find_spotifyd_name(bus)
                    logger.info(f"Found spotifyd on D-Bus as: {mpris_name}")
                    
                    # Auto-switch to spotify when connection detected
                    self.source_switch_callback('spotify')
                    
                except RuntimeError:
                    logger.debug("Spotifyd not found on D-Bus, retrying in 5 seconds...")
                    await asyncio.sleep(5)
                    continue

                introspection = await bus.introspect(
                    mpris_name,
                    '/org/mpris/MediaPlayer2'
                )
                
                proxy = bus.get_proxy_object(mpris_name, '/org/mpris/MediaPlayer2', introspection)
                props = proxy.get_interface('org.freedesktop.DBus.Properties')

                def on_props_changed(interface, changed, _):
                    for prop, value in changed.items():
                        if prop == 'PlaybackStatus':
                            status = value.value
                            logger.info(f"🎵 Spotifyd PlaybackStatus: {status}")
                            
                            if status == 'Playing':
                                self.source_switch_callback('spotify')
                        elif prop == 'Volume':
                            volume_float = value.value
                            volume_percent = int(volume_float * 100)
                            logger.info(f"🔊 Spotify volume changed to {volume_percent}%")
                            # Call volume change callback if provided
                            if self.volume_change_callback:
                                self.volume_change_callback(volume_percent)
                        elif prop == 'Metadata':
                            metadata = value.value
                            if 'xesam:title' in metadata and 'xesam:artist' in metadata:
                                title = metadata['xesam:title'].value
                                artists = metadata['xesam:artist'].value
                                logger.info(f"🎵 Now playing: {title} by {', '.join(artists)}")
                            
                # Unregister previous handler if it exists
                if self.current_props and self.current_handler:
                    self.current_props.off_properties_changed(self.current_handler)
                
                props.on_properties_changed(on_props_changed)
                
                # Store current handler references for cleanup
                self.current_props = props
                self.current_handler = on_props_changed
                
                logger.info(f"🎵 Listening for spotifyd events...")
                
                # Monitor until spotifyd disconnects
                while not self.spotifyd_stop_event.is_set():
                    await asyncio.sleep(0.5)
                    
                    try:
                        await self._find_spotifyd_name(bus)
                    except RuntimeError:
                        logger.info("🎵 Spotifyd disconnected, will retry connection...")
                        
                        # Unregister handler on disconnection
                        if self.current_props and self.current_handler:
                            self.current_props.off_properties_changed(self.current_handler)
                            self.current_props = None
                            self.current_handler = None
                        
                        break
                    
            except Exception as e:
                logger.error(f"Error in spotifyd monitoring: {e}")
                logger.info("🎵 Will retry spotifyd connection in 10 seconds...")
                
                # Close the bus connection before retrying to prevent leaks
                if bus:
                    try:
                        bus.disconnect()
                    except Exception:
                        pass
                    bus = None
                
                await asyncio.sleep(10)
                
        # Clean up connection on exit
        if bus:
            try:
                bus.disconnect()
                logger.debug("🎵 Closed DBUS connection")
            except Exception as e:
                logger.debug(f"Error closing DBUS connection: {e}")
                
        logger.info("🎵 Stopped spotifyd DBUS monitoring")

    def _run_spotifyd_loop(self):
        """Run the spotifyd async loop in a thread"""
        self.spotifyd_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.spotifyd_loop)
        try:
            self.spotifyd_loop.run_until_complete(self._spotifyd_monitoring_loop())
        except Exception as e:
            logger.error(f"Error in spotifyd loop: {e}")
        finally:
            self.spotifyd_loop.close()

    def start_monitoring(self):
        """Start spotifyd DBUS monitoring"""
        if self.spotifyd_thread and self.spotifyd_thread.is_alive():
            logger.info("Spotifyd monitoring is already running")
            return
            
        self.stop_monitoring()
        
        logger.info("Starting spotifyd DBUS monitoring")
        self.spotifyd_stop_event.clear()
        self.spotifyd_thread = threading.Thread(target=self._run_spotifyd_loop, daemon=True)
        self.spotifyd_thread.start()

    def stop_monitoring(self):
        """Stop spotifyd DBUS monitoring"""
        if not self.spotifyd_thread or not self.spotifyd_thread.is_alive():
            return
            
        self.spotifyd_stop_event.set()
        
        # Clean up handler references
        if self.current_props and self.current_handler:
            try:
                self.current_props.off_properties_changed(self.current_handler)
            except Exception:
                pass
            self.current_props = None
            self.current_handler = None
        
        if self.spotifyd_loop:
            self.spotifyd_loop.call_soon_threadsafe(self.spotifyd_loop.stop)
        
        if self.spotifyd_thread.is_alive():
            self.spotifyd_thread.join(timeout=5.0)
            
        logger.info("Stopped spotifyd DBUS monitoring")

class SpotifyController:
    def __init__(self):
        pass

    def _get_spotifyd_player_name(self):
        """Get the spotifyd player name from playerctl"""
        try:
            with os.popen("playerctl -l 2>/dev/null") as f:
                output = f.read().strip()
            
            if output:
                players = output.split('\n')
                spotifyd_players = [p for p in players if p.startswith('spotifyd')]
                if spotifyd_players:
                    logger.debug(f"Found spotifyd player: {spotifyd_players[0]}")
                    return spotifyd_players[0]
            
            logger.debug("No spotifyd player found")
            return None
        except Exception as e:
            logger.error(f"Error getting spotifyd player name: {e}")
            return None

    def play_pause(self):
        """Toggle play/pause for spotifyd using playerctl"""
        player = self._get_spotifyd_player_name()
        if not player:
            logger.error("No spotifyd player found")
            return False
            
        try:
            result = os.system(f"playerctl -p {player} play-pause 2>/dev/null")
            if result == 0:
                logger.info("🎵 Toggled Spotify play/pause")
                return True
            else:
                logger.error("Error toggling Spotify play/pause")
                return False
        except Exception as e:
            logger.error(f"Error with playerctl command: {e}")
            return False

    def play(self):
        """Start playback for spotifyd using playerctl"""
        player = self._get_spotifyd_player_name()
        if not player:
            logger.error("No spotifyd player found")
            return False
            
        try:
            result = os.system(f"playerctl -p {player} play 2>/dev/null")
            if result == 0:
                logger.info("▶️ Started Spotify playback")
                return True
            else:
                logger.error("Error starting Spotify playback")
                return False
        except Exception as e:
            logger.error(f"Error with playerctl command: {e}")
            return False

    def pause(self):
        """Pause playback for spotifyd using playerctl"""
        player = self._get_spotifyd_player_name()
        if not player:
            logger.error("No spotifyd player found")
            return False
            
        try:
            result = os.system(f"playerctl -p {player} pause 2>/dev/null")
            if result == 0:
                logger.info("⏸️ Paused Spotify playback")
                return True
            else:
                logger.error("Error pausing Spotify playback")
                return False
        except Exception as e:
            logger.error(f"Error with playerctl command: {e}")
            return False

    def next(self):
        """Skip to next track for spotifyd using playerctl"""
        player = self._get_spotifyd_player_name()
        if not player:
            logger.error("No spotifyd player found")
            return False
            
        try:
            result = os.system(f"playerctl -p {player} next 2>/dev/null")
            if result == 0:
                logger.info("⏭️ Skipped to next track")
                return True
            else:
                logger.error("Error skipping to next track")
                return False
        except Exception as e:
            logger.error(f"Error with playerctl command: {e}")
            return False

    def previous(self):
        """Skip to previous track for spotifyd using playerctl"""
        player = self._get_spotifyd_player_name()
        if not player:
            logger.error("No spotifyd player found")
            return False
            
        try:
            result = os.system(f"playerctl -p {player} previous 2>/dev/null")
            if result == 0:
                logger.info("⏮️ Skipped to previous track")
                return True
            else:
                logger.error("Error skipping to previous track")
                return False
        except Exception as e:
            logger.error(f"Error with playerctl command: {e}")
            return False

    def set_volume(self, volume):
        """Set volume for spotifyd using gdbus (bypassing playerctl)"""
        try:
            # Get spotifyd PID
            with os.popen("pidof spotifyd 2>/dev/null") as f:
                spotifyd_pid = f.read().strip()
            
            if not spotifyd_pid:
                logger.error("No spotifyd process found")
                return False
            
            # Convert 0-100 to 0.0-1.0 for D-Bus
            volume_float = max(0.0, min(1.0, float(volume) / 100.0))
            
            # Use gdbus to set volume directly via D-Bus
            cmd = f'gdbus call --system --dest "org.mpris.MediaPlayer2.spotifyd.instance{spotifyd_pid}" --object-path "/org/mpris/MediaPlayer2" --method "org.freedesktop.DBus.Properties.Set" "org.mpris.MediaPlayer2.Player" "Volume" "<double {volume_float}>" 2>/dev/null'
            
            result = os.system(cmd)
            if result == 0:
                logger.info(f"🔊 Set Spotify volume to {volume}%")
                return True
            else:
                logger.error("Error setting Spotify volume via gdbus")
                return False
            
        except Exception as e:
            logger.error(f"Error with gdbus command: {e}")
            return False