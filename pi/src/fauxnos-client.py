#!/usr/bin/env python3
"""
Audio Source Control and Mixer
------------------------------
This script manages audio source switching between analogsink, snapsink, and libresink,
with smooth volume transitions and appropriate notification sounds.
"""

# TODO: add support for squeezelite instead of librespot
# TODO: automatically set sink-inputs based on their name via pactl move-sink-input <sink-input-name> <sink-name>
# TODO: automatically set sink-input-volume of librespot input sink to 100%

import os
import time
import logging
import subprocess
import threading
import json
import socket
import select
import asyncio
from dbus_next.aio import MessageBus
from dbus_next import Message
from dbus_next.constants import BusType

# Load configuration
with open(os.path.join(os.path.dirname(__file__), 'audio_config.json'), 'r') as f:
    PLAYER_CONFIG = json.load(f)

# Set up logging
logger = logging.getLogger('AudioController')
logger.setLevel(logging.INFO)

# Create formatters
file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# File handler
log_file = os.path.expanduser(PLAYER_CONFIG["log_file"].format(name=PLAYER_CONFIG["name"]))
file_handler = logging.FileHandler(log_file)
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)

# Constants
FADE_STEP = 5  # Volume change per step (percentage)
FADE_DELAY = 0.05  # Delay between fade steps (seconds)

# Sound file paths
SWITCH_SOUND = os.path.expanduser(PLAYER_CONFIG["sounds"]["switch"])
VOLUME_UP_SOUND = os.path.expanduser(PLAYER_CONFIG["sounds"]["volume_up"])
VOLUME_DOWN_SOUND = os.path.expanduser(PLAYER_CONFIG["sounds"]["volume_down"])

class AudioController:
    def __init__(self):
        # Load configuration and initialize sources dynamically
        sources_config = PLAYER_CONFIG.get("sources", [])
        
        # Filter to only internal sources with sink property and create lookup dictionaries
        self.sources = {}  # id -> source config
        self.source_ids = []  # list of source IDs
        self.id_to_sink = {}  # id -> sink name mapping
        
        for source_config in sources_config:
            # Skip if source_config is not a dict (defensive programming)
            if not isinstance(source_config, dict):
                logger.warning(f"Skipping invalid source config: {source_config}")
                continue
                
            if (source_config.get("type") == "internal" and 
                "sink" in source_config and "id" in source_config):
                source_id = source_config["id"]
                self.sources[source_id] = source_config
                self.source_ids.append(source_id)
                self.id_to_sink[source_id] = source_config["sink"]
        
        # Initialize with neutral values first
        self.current_source = None
        
        # Track the desired volume level (0-100) for each audio source when it's active.
        # These values persist when switching between sources.
        self.source_volumes = {}
        for source_id, source_config in self.sources.items():
            self.source_volumes[source_id] = source_config.get("starting_volume", 30)
        
        # Track the current actual volume (0-100) of each PulseAudio sink.
        # These values represent the hardware/software volume levels in the audio system.
        # Used during volume fades and audio routing.
        self.sink_volumes = {source_id: 0 for source_id in self.source_ids}
        
        # Simplified monitoring - only track analog input activity
        # No need for per-source state tracking since we only monitor analog input hardware
        self.auto_switching_enabled = False
        self.monitoring_thread = None
        self.monitoring_stop_event = threading.Event()
        
        # Separate librespot event handling thread
        self.librespot_thread = None
        self.librespot_stop_event = threading.Event()
        
        # Spotifyd DBUS monitoring
        self.spotifyd_thread = None
        self.spotifyd_stop_event = threading.Event()
        self.spotifyd_loop = None
        
        # Read current state from config if available
        self._load_state()
        
        # Librespot event handling
        self.librespot_socket = None
        self.librespot_socket_path = '/home/user/fauxnos-librespot.sock'
        self.librespot_event_file = '/home/user/fauxnos-librespot-event.json'
        self._setup_librespot_listener()
        
        # Always mute all sinks on startup to ensure clean state
        self._mute_all_sinks()
        
        # If no previous state was loaded or source is still None, set default source
        if self.current_source is None:
            # Use first available source as default
            default_source = self.source_ids[0] if self.source_ids else None
            if default_source:
                logger.info(f"No previous state found, setting default source to {default_source}")
                self.switch_source(default_source)
        else:
            logger.info(f"AudioController initialized with source: {self.current_source}")
            # Now switch to the loaded current source to properly set volumes
            self.switch_source(self.current_source)
            
        # Start librespot monitoring automatically (separate from auto-switching)
        self.start_librespot_monitoring()
        
        # Start spotifyd DBUS monitoring
        self.start_spotifyd_monitoring()
        
        # Start auto-switching for analog monitoring
        self.start_auto_switching()

    def _load_state(self):
        """Load previous state from config file if available"""
        try:
            # This would read from a state file, but is simplified for this example
            # In a real implementation, you'd save/load state from a config file
            pass
        except Exception as e:
            logger.error(f"Error loading state: {e}")

    def _save_state(self):
        """Save current state to config file"""
        try:
            # This would write to a state file, but is simplified for this example
            pass
        except Exception as e:
            logger.error(f"Error saving state: {e}")

    def _setup_librespot_listener(self):
        """Set up Unix socket to receive librespot events"""
        try:
            # Remove existing socket file if it exists
            if os.path.exists(self.librespot_socket_path):
                logger.debug(f"Removing existing socket file: {self.librespot_socket_path}")
                os.unlink(self.librespot_socket_path)
            
            # Create Unix socket
            self.librespot_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            
            # Set socket options for better reliability
            self.librespot_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            self.librespot_socket.bind(self.librespot_socket_path)
            self.librespot_socket.listen(5)  # Increased backlog from 1 to 5
            self.librespot_socket.setblocking(False)  # Non-blocking
            
            # Set permissions on socket file
            os.chmod(self.librespot_socket_path, 0o666)
            
            logger.info(f"🎵 Librespot event listener ready at {self.librespot_socket_path}")
        except Exception as e:
            logger.error(f"Failed to setup librespot listener: {e}")
            self.librespot_socket = None

    def _handle_librespot_event(self, event_data):
        """Handle incoming librespot events"""
        event = event_data.get('event')
        
        if event == 'playing':
            logger.info("🎵 Librespot started playing - switching to Spotify")
            # Find spotify source in available sources
            spotify_sources = [sid for sid in self.source_ids if 'spotify' in sid.lower() or 'libre' in sid.lower()]
            
            if spotify_sources:
                self.switch_source(spotify_sources[0])
            else:
                logger.warning("No Spotify source found in configuration")
                
        elif event == 'paused':
            logger.info("⏸️  Librespot paused")
            
        elif event == 'stopped':
            logger.info("⏹️  Librespot stopped")
            
        elif event == 'track_changed':
            track_name = event_data.get('track_name', 'Unknown')
            artist = event_data.get('artist', 'Unknown')
            logger.info(f"🎵 Now playing: {track_name} by {artist}")
            
            # Ensure we're on the right source
            spotify_sources = [sid for sid in self.source_ids if 'spotify' in sid.lower() or 'libre' in sid.lower()]
            if spotify_sources and self.current_source != spotify_sources[0]:
                self.switch_source(spotify_sources[0])
                
        elif event == 'volume_changed':
            volume = event_data.get('volume')
            if volume and self.current_source:
                # Check if current source is Spotify-related
                if 'spotify' in self.current_source.lower() or 'libre' in self.current_source.lower():
                    try:
                        self.set_volume(int(volume))
                    except ValueError:
                        logger.warning(f"Invalid volume value from librespot: {volume}")

    def _check_librespot_events(self):
        """Check for incoming librespot events (non-blocking)"""
        if not self.librespot_socket:
            return
            
        try:
            # Check for socket connections
            ready, _, _ = select.select([self.librespot_socket], [], [], 0)
            if ready:
                conn, _ = self.librespot_socket.accept()
                data = conn.recv(1024).decode().strip()
                conn.close()
                
                if data:
                    event_data = json.loads(data)
                    self._handle_librespot_event(event_data)
                    
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing librespot event JSON: {e}")
        except Exception as e:
            logger.debug(f"Socket check error: {e}")

    def _play_sound(self, sound_file):
        """Play notification sound in a non-blocking way"""
        def play_sound_thread():
            try:
                subprocess.run(["aplay", "-D", "pulse:systemsink", sound_file], 
                            stdout=subprocess.DEVNULL, 
                            stderr=subprocess.DEVNULL)
            except Exception as e:
                logger.error(f"Error playing sound {sound_file}: {e}")
        
        # Start the sound in a daemon thread so it doesn't block program exit
        thread = threading.Thread(target=play_sound_thread, daemon=True)
        thread.start()

    def _set_sink_volume(self, sink, volume):
        """Set volume for the specified sink"""
        try:
            subprocess.run(["pactl", "set-sink-volume", sink, f"{volume}%"], 
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL)
        except Exception as e:
            logger.error(f"Error setting {sink} volume to {volume}: {e}")

    def _mute_all_sinks(self):
        """Mute all configured sinks to 0 volume"""
        logger.info("Muting all sinks on startup")
        for source_id in self.source_ids:
            sink_name = self.id_to_sink[source_id]
            self._set_sink_volume(sink_name, 0)
            self.sink_volumes[source_id] = 0
        logger.info("All sinks muted")


    def _fade_volume(self, sink, start_vol, end_vol):
        #disable fade temporarily
        #self._set_sink_volume(sink, end_vol)
        #return end_vol

        """Fade volume from start to end value"""
        # Ensure we have valid integers for volumes
        if start_vol is None:
            logger.warning(f"Starting volume for {sink} was None, using 0")
            start_vol = 0
            
        if end_vol is None:
            logger.warning(f"Ending volume for {sink} was None, using 0")
            end_vol = 0
            
        # Ensure volumes are integers
        start_vol = int(start_vol)
        end_vol = int(end_vol)
        
        steps = abs(end_vol - start_vol) // FADE_STEP
        if steps == 0:
            return end_vol
            
        step_size = FADE_STEP if end_vol > start_vol else -FADE_STEP
        current_vol = start_vol
        
        for _ in range(steps):
            current_vol += step_size
            self._set_sink_volume(sink, current_vol)
            time.sleep(FADE_DELAY)
            
        # Ensure we reach the exact target volume
        self._set_sink_volume(sink, end_vol)
        
        logger.info(f"Faded {sink} volume from {start_vol} to {end_vol}")
        return end_vol

    def _is_analog_input_active(self):
        """Check if analog input has active audio by sampling the audio stream"""
        try:
            # Monitor the actual analog INPUT source, not the sink output
            # This detects input regardless of which sink is currently active
            input_source = "alsa_input.platform-soc_sound.stereo-fallback"
            
            logger.debug(f"Sampling audio from {input_source} to detect activity")
            
            # Use parec to capture a brief, low-quality sample and check for data
            # --rate 1000: Very low sample rate for quick detection
            # timeout 2: Maximum 2 seconds to detect audio
            # fgrep -qm 1 .: Look for any non-null data (audio present)
            
            cmd = [
                "timeout", "2",
                "sh", "-c", 
                f"parec --rate=1000 -d '{input_source}' 2>/dev/null | LC_ALL=C fgrep -qm 1 ."
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=3  # Python timeout as backup
            )
            
            # fgrep returns 0 if data found (audio playing), 1 if no data (silence)
            if result.returncode == 0:
                logger.debug(f"Audio data detected on {input_source}")
                return True
            elif result.returncode == 1:
                logger.debug(f"No audio data detected on {input_source}")
                return False
            elif result.returncode == 124:  # timeout command exit code
                logger.debug(f"Timeout waiting for audio data on {input_source} - assuming silence")
                return False
            else:
                logger.warning(f"Unexpected return code {result.returncode} from audio detection")
                return False
                
        except subprocess.TimeoutExpired:
            logger.warning(f"Python timeout checking analog input activity - assuming silence")
            return False
        except FileNotFoundError:
            logger.error(f"parec command not found - install pulseaudio-utils")
            return False
        except Exception as e:
            logger.error(f"Error checking analog input activity: {e}")
            return False

    def _auto_source_control(self):
        """Simplified automatic source control - only checks analog input"""
        if not self.auto_switching_enabled:
            return
            
        try:
            # Check if analog input is active
            analog_active = self._is_analog_input_active()
            
            # Track previous state for edge detection
            previous_analog_state = getattr(self, '_previous_analog_active', False)
            self._previous_analog_active = analog_active
            
            logger.debug(f"Analog input: {'active' if analog_active else 'inactive'}")
            
            # Only switch to analog if:
            # 1. Analog input just became active (edge detection)
            # 2. OR analog is active and we're not already on analog
            if analog_active and (self.current_source != "analog" or not previous_analog_state):
                if self.current_source != "analog":
                    logger.info(f"Analog input detected - switching from {self.current_source} to analog")
                    self.switch_source("analog")
                else:
                    logger.debug("Analog input active and already on analog source")
            
            # Optional: Switch away from analog when input stops
            # (Comment out if you want to stay on analog even when input stops)
            # elif not analog_active and self.current_source == "analog":
            #     # Switch to default source (first available)
            #     default_source = self.source_ids[0] if self.source_ids else None
            #     if default_source and default_source != "analog":
            #         logger.info(f"Analog input stopped - switching to {default_source}")
            #         self.switch_source(default_source)
                
        except Exception as e:
            logger.error(f"Error in automatic source control: {e}")

    def _monitoring_loop(self):
        """Continuous monitoring loop for automatic source control (analog input only)"""
        logger.info("Started automatic source monitoring")
        
        while not self.monitoring_stop_event.is_set():
            try:
                self._auto_source_control()
                # Wait for 2 seconds or until stop event is set
                self.monitoring_stop_event.wait(2.0)
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                # Brief sleep on error to prevent rapid error loops
                time.sleep(1.0)
                
        logger.info("Stopped automatic source monitoring")

    def _librespot_monitoring_loop(self):
        """Continuous monitoring loop for librespot events"""
        logger.info("🎵 Started librespot event monitoring")
        
        while not self.librespot_stop_event.is_set():
            try:
                self._check_librespot_events()
                # Wait for 0.5 seconds or until stop event is set (faster response)
                self.librespot_stop_event.wait(0.5)
            except Exception as e:
                logger.error(f"Error in librespot monitoring loop: {e}")
                # Brief sleep on error to prevent rapid error loops
                time.sleep(1.0)
                
        logger.info("🎵 Stopped librespot event monitoring")

    def start_librespot_monitoring(self):
        """Start librespot event monitoring (independent of auto-switching)"""
        if self.librespot_thread and self.librespot_thread.is_alive():
            logger.info("Librespot monitoring is already running")
            return
            
        # Setup librespot socket
        self._setup_librespot_listener()
        
        self.librespot_stop_event.clear()
        self.librespot_thread = threading.Thread(target=self._librespot_monitoring_loop, daemon=True)
        self.librespot_thread.start()
        logger.info("Started librespot event monitoring")

    def stop_librespot_monitoring(self):
        """Stop librespot event monitoring"""
        if not self.librespot_thread or not self.librespot_thread.is_alive():
            logger.info("Librespot monitoring is not running")
            return
            
        self.librespot_stop_event.set()
        
        if self.librespot_thread.is_alive():
            self.librespot_thread.join(timeout=5.0)
            
        # Clean up librespot socket
        if self.librespot_socket:
            try:
                self.librespot_socket.close()
                if os.path.exists(self.librespot_socket_path):
                    os.unlink(self.librespot_socket_path)
            except Exception as e:
                logger.error(f"Error cleaning up librespot socket: {e}")
            finally:
                self.librespot_socket = None
            
        logger.info("Stopped librespot event monitoring")

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
        logger.info("🎵 Started spotifyd DBUS monitoring")
        
        try:
            bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            
            mpris_name = await self._find_spotifyd_name(bus)
            logger.info(f"Found spotifyd on D-Bus as: {mpris_name}")

            introspection = await bus.introspect(
                mpris_name,
                '/org/mpris/MediaPlayer2'
            )
            proxy = bus.get_proxy_object(mpris_name, '/org/mpris/MediaPlayer2', introspection)
            props = proxy.get_interface('org.freedesktop.DBus.Properties')

            def on_props_changed(interface, changed, invalidated):
                logger.debug(f"DBUS Event - Interface: {interface}")
                for prop, value in changed.items():
                    if prop == 'PlaybackStatus':
                        status = value.value
                        logger.info(f"🎵 Spotifyd PlaybackStatus: {status}")
                        
                        # Auto-switch to spotify when spotifyd goes from paused to playing
                        if status == 'Playing':
                            spotify_sources = [sid for sid in self.source_ids if 'spotify' in sid.lower()]
                            if spotify_sources:
                                logger.info("🎵 Spotifyd started playing - switching to Spotify")
                                # Use thread-safe call to switch source
                                threading.Thread(
                                    target=self.switch_source, 
                                    args=(spotify_sources[0],), 
                                    daemon=True
                                ).start()
                            else:
                                logger.warning("No Spotify source found in configuration")
                    elif prop == 'Metadata':
                        metadata = value.value
                        if 'xesam:title' in metadata and 'xesam:artist' in metadata:
                            title = metadata['xesam:title'].value
                            artists = metadata['xesam:artist'].value
                            logger.info(f"🎵 Now playing: {title} by {', '.join(artists)}")
                        
            props.on_properties_changed(on_props_changed)
            logger.info("🎵 Listening for spotifyd events...")
            
            # Keep the async loop running
            while not self.spotifyd_stop_event.is_set():
                await asyncio.sleep(0.5)
                
        except Exception as e:
            logger.error(f"Error in spotifyd monitoring: {e}")
        finally:
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

    def start_spotifyd_monitoring(self):
        """Start spotifyd DBUS monitoring"""
        if self.spotifyd_thread and self.spotifyd_thread.is_alive():
            logger.info("Spotifyd monitoring is already running")
            return
            
        self.spotifyd_stop_event.clear()
        self.spotifyd_thread = threading.Thread(target=self._run_spotifyd_loop, daemon=True)
        self.spotifyd_thread.start()
        logger.info("Started spotifyd DBUS monitoring")

    def stop_spotifyd_monitoring(self):
        """Stop spotifyd DBUS monitoring"""
        if not self.spotifyd_thread or not self.spotifyd_thread.is_alive():
            logger.info("Spotifyd monitoring is not running")
            return
            
        self.spotifyd_stop_event.set()
        
        if self.spotifyd_loop:
            self.spotifyd_loop.call_soon_threadsafe(self.spotifyd_loop.stop)
        
        if self.spotifyd_thread.is_alive():
            self.spotifyd_thread.join(timeout=5.0)
            
        logger.info("Stopped spotifyd DBUS monitoring")

    def start_auto_switching(self):
        """Start automatic source switching (analog input monitoring only)"""
        if self.auto_switching_enabled:
            logger.info("Automatic switching is already enabled")
            return
            
        self.auto_switching_enabled = True
        self.monitoring_stop_event.clear()
        self.monitoring_thread = threading.Thread(target=self._monitoring_loop, daemon=True)
        self.monitoring_thread.start()
        logger.info("Started automatic source switching")

    def stop_auto_switching(self):
        """Stop automatic source switching (analog input monitoring only)"""
        if not self.auto_switching_enabled:
            logger.info("Automatic switching is already disabled")
            return
            
        self.auto_switching_enabled = False
        self.monitoring_stop_event.set()
        
        if self.monitoring_thread and self.monitoring_thread.is_alive():
            self.monitoring_thread.join(timeout=5.0)
            
        logger.info("Stopped automatic source switching")

    def switch_source(self, source):
        """Switch audio source with smooth transitions"""
        new_source = source.lower()
        
        # Validate source exists in config
        if new_source not in self.source_ids:
            logger.error(f"Invalid source: {new_source}. Available sources: {self.source_ids}")
            return
        
        if self.current_source is not None:

            if new_source == self.current_source:
                logger.info(f"Already using source {new_source}")
                return  
                            
            # Play notification sound for source switch
            self._play_sound(SWITCH_SOUND)

        logger.info(f"Switching to {new_source}")
        
        # Fade out all other sinks first, then fade in the selected sink
        for source_id in self.source_ids:
            if source_id != new_source:
                # Fade out other sources
                sink_name = self.id_to_sink[source_id]
                self.sink_volumes[source_id] = self._fade_volume(
                    sink_name, self.sink_volumes[source_id], 0
                )
        
        # Fade in the selected source to its stored volume level
        target_volume = self.source_volumes[new_source]
        selected_sink = self.id_to_sink[new_source]
        self.sink_volumes[new_source] = self._fade_volume(
            selected_sink, self.sink_volumes[new_source], target_volume
        )
            
        self.current_source = new_source
        self._save_state()
        logger.info(f"Source switched to {self.current_source}")

    def set_volume(self, volume):
        """Set volume for active source"""
        try:
            volume = int(volume)
            if volume < 0 or volume > 100:
                logger.error(f"Invalid volume level: {volume}")
                return
                
            if self.current_source and self.current_source in self.source_ids:
                sink_name = self.id_to_sink[self.current_source]
                self._set_sink_volume(sink_name, volume)
                self.source_volumes[self.current_source] = volume
                self.sink_volumes[self.current_source] = volume
                source_display = self.sources[self.current_source].get("label", self.current_source)
                logger.info(f"Set {source_display} volume to {volume}")
            else:
                logger.error("No active source to set volume for")
                
            self._save_state()
        except ValueError:
            logger.error(f"Invalid volume value: {volume}")

    def adjust_volume(self, increment):
        """Adjust volume up or down for active source"""
        try:
            increment = int(increment)
            
            if self.current_source and self.current_source in self.source_ids:
                current_volume = self.source_volumes[self.current_source]
                new_volume = max(0, min(100, current_volume + increment))
                sink_name = self.id_to_sink[self.current_source]
                self._set_sink_volume(sink_name, new_volume)
                self.source_volumes[self.current_source] = new_volume
                self.sink_volumes[self.current_source] = new_volume
                source_display = self.sources[self.current_source].get("label", self.current_source)
                logger.info(f"Adjusted {source_display} volume to {new_volume}")
            else:
                logger.error("No active source to adjust volume for")
                return
                
            # Play appropriate sound based on direction
            if increment > 0:
                self._play_sound(VOLUME_UP_SOUND)
            else:
                self._play_sound(VOLUME_DOWN_SOUND)
                
            self._save_state()
        except ValueError:
            logger.error(f"Invalid increment value: {increment}")

    def _get_spotifyd_player_name(self):
        """Get the spotifyd player name from playerctl"""
        try:
            result = subprocess.run(
                ["playerctl", "-l"], 
                capture_output=True, 
                text=True, 
                timeout=5
            )
            if result.returncode == 0:
                players = result.stdout.strip().split('\n')
                spotifyd_players = [p for p in players if p.startswith('spotifyd')]
                if spotifyd_players:
                    return spotifyd_players[0]
            return None
        except Exception as e:
            logger.error(f"Error getting spotifyd player name: {e}")
            return None

    def spotify_play_pause(self):
        """Toggle play/pause for spotifyd using playerctl"""
        player = self._get_spotifyd_player_name()
        if not player:
            logger.error("No spotifyd player found")
            return False
            
        try:
            subprocess.run(
                ["playerctl", "-p", player, "play-pause"], 
                check=True, 
                capture_output=True, 
                timeout=5
            )
            logger.info("🎵 Toggled Spotify play/pause")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Error toggling Spotify play/pause: {e}")
            return False
        except Exception as e:
            logger.error(f"Error with playerctl command: {e}")
            return False

    def spotify_play(self):
        """Start playback for spotifyd using playerctl"""
        player = self._get_spotifyd_player_name()
        if not player:
            logger.error("No spotifyd player found")
            return False
            
        try:
            subprocess.run(
                ["playerctl", "-p", player, "play"], 
                check=True, 
                capture_output=True, 
                timeout=5
            )
            logger.info("▶️ Started Spotify playback")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Error starting Spotify playback: {e}")
            return False
        except Exception as e:
            logger.error(f"Error with playerctl command: {e}")
            return False

    def spotify_pause(self):
        """Pause playback for spotifyd using playerctl"""
        player = self._get_spotifyd_player_name()
        if not player:
            logger.error("No spotifyd player found")
            return False
            
        try:
            subprocess.run(
                ["playerctl", "-p", player, "pause"], 
                check=True, 
                capture_output=True, 
                timeout=5
            )
            logger.info("⏸️ Paused Spotify playback")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Error pausing Spotify playback: {e}")
            return False
        except Exception as e:
            logger.error(f"Error with playerctl command: {e}")
            return False

    def spotify_next(self):
        """Skip to next track for spotifyd using playerctl"""
        player = self._get_spotifyd_player_name()
        if not player:
            logger.error("No spotifyd player found")
            return False
            
        try:
            subprocess.run(
                ["playerctl", "-p", player, "next"], 
                check=True, 
                capture_output=True, 
                timeout=5
            )
            logger.info("⏭️ Skipped to next track")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Error skipping to next track: {e}")
            return False
        except Exception as e:
            logger.error(f"Error with playerctl command: {e}")
            return False

    def spotify_previous(self):
        """Skip to previous track for spotifyd using playerctl"""
        player = self._get_spotifyd_player_name()
        if not player:
            logger.error("No spotifyd player found")
            return False
            
        try:
            subprocess.run(
                ["playerctl", "-p", player, "previous"], 
                check=True, 
                capture_output=True, 
                timeout=5
            )
            logger.info("⏮️ Skipped to previous track")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Error skipping to previous track: {e}")
            return False
        except Exception as e:
            logger.error(f"Error with playerctl command: {e}")
            return False

    def spotify_set_volume(self, volume):
        """Set volume for spotifyd using gdbus (bypassing playerctl)"""
        try:
            # Get spotifyd PID
            result = subprocess.run(
                ["pidof", "spotifyd"], 
                capture_output=True, 
                text=True, 
                timeout=5
            )
            if result.returncode != 0:
                logger.error("No spotifyd process found")
                return False
                
            spotifyd_pid = result.stdout.strip()
            if not spotifyd_pid:
                logger.error("Could not get spotifyd PID")
                return False
            
            # Convert 0-100 to 0.0-1.0 for D-Bus
            volume_float = max(0.0, min(1.0, float(volume) / 100.0))
            
            # Use gdbus to set volume directly via D-Bus
            subprocess.run([
                "gdbus", "call", "--system",
                "--dest", f"org.mpris.MediaPlayer2.spotifyd.instance{spotifyd_pid}",
                "--object-path", "/org/mpris/MediaPlayer2",
                "--method", "org.freedesktop.DBus.Properties.Set",
                "org.mpris.MediaPlayer2.Player",
                "Volume",
                f"<double {volume_float}>"
            ], check=True, capture_output=True, timeout=5)
            
            logger.info(f"🔊 Set Spotify volume to {volume}%")
            return True
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Error setting Spotify volume via gdbus: {e}")
            return False
        except Exception as e:
            logger.error(f"Error with gdbus command: {e}")
            return False

def parse_command(command_str):
    """Parse a command string into command and arguments"""
    parts = command_str.strip().split()
    if not parts:
        return None, None
        
    command = parts[0].lower()
    args = parts[1:]
    
    return command, args

def main():
    controller = AudioController()
    logger.info("Audio Controller started. Type 'help' for available commands.")
    
    while True:
        try:
            command_str = input("> ").strip()
            if not command_str:
                continue
                
            command, args = parse_command(command_str)
            
            if command == 'help':
                print("\nAvailable commands:")
                source_list = "|".join(controller.source_ids)
                print(f"  source [{source_list}] - Switch audio source")
                print("  volume [0-100]         - Set volume level")
                print("  adjust [+/-N]          - Adjust volume by N")
                print("  auto [on|off]          - Enable/disable automatic switching")
                print("  status                 - Show current state")
                print("  quit                   - Exit program")
                print("  help                   - Show this help")
                print("\nSpotify controls:")
                print("  spotify play           - Start Spotify playback")
                print("  spotify pause          - Pause Spotify playback")
                print("  spotify toggle         - Toggle play/pause")
                print("  spotify next           - Skip to next track")
                print("  spotify prev           - Skip to previous track")
                print("  spotify volume [0-100] - Set Spotify volume")
                
            elif command == 'source':
                if not args or args[0] not in controller.source_ids:
                    source_list = "', '".join(controller.source_ids)
                    print(f"Error: source must be one of: '{source_list}'")
                    continue
                controller.switch_source(args[0])
                
            elif command == 'volume':
                if not args:
                    print("Error: volume level required")
                    continue
                try:
                    level = int(args[0])
                    controller.set_volume(level)
                except ValueError:
                    print("Error: volume must be a number between 0 and 100")
                    
            elif command == 'adjust':
                if not args:
                    print("Error: volume adjustment required")
                    continue
                try:
                    increment = int(args[0])
                    controller.adjust_volume(increment)
                except ValueError:
                    print("Error: adjustment must be a number")
                    
            elif command == 'auto':
                if not args or args[0] not in ['on', 'off']:
                    print("Error: auto must be 'on' or 'off'")
                    continue
                if args[0] == 'on':
                    controller.start_auto_switching()
                    print("Automatic source switching enabled")
                else:
                    controller.stop_auto_switching()
                    print("Automatic source switching disabled")
                    
            elif command == 'status':
                print(f"\nCurrent state:")
                if controller.current_source is None:
                    print(f"  Source: Not set")
                else:
                    source_display = controller.sources[controller.current_source].get("label", controller.current_source)
                    print(f"  Source: {source_display} ({controller.current_source})")
                    
                for source_id in controller.source_ids:
                    source_display = controller.sources[source_id].get("label", source_id)
                    volume = controller.source_volumes[source_id]
                    sink_volume = controller.sink_volumes[source_id]
                    sink_name = controller.id_to_sink[source_id]
                    print(f"  {source_display} volume: {volume}% (sink {sink_name}: {sink_volume}%)")
                    
                print(f"  Auto-switching: {'enabled' if controller.auto_switching_enabled else 'disabled'}")
                
            elif command == 'spotify':
                if not args:
                    print("Error: spotify command requires an action")
                    print("Available actions: play, pause, toggle, next, prev, volume")
                    continue
                    
                spotify_action = args[0].lower()
                
                if spotify_action == 'play':
                    if controller.spotify_play():
                        print("Started Spotify playback")
                    else:
                        print("Failed to start Spotify playback")
                        
                elif spotify_action == 'pause':
                    if controller.spotify_pause():
                        print("Paused Spotify playback")
                    else:
                        print("Failed to pause Spotify playback")
                        
                elif spotify_action == 'toggle':
                    if controller.spotify_play_pause():
                        print("Toggled Spotify play/pause")
                    else:
                        print("Failed to toggle Spotify play/pause")
                        
                elif spotify_action == 'next':
                    if controller.spotify_next():
                        print("Skipped to next track")
                    else:
                        print("Failed to skip to next track")
                        
                elif spotify_action in ['prev', 'previous']:
                    if controller.spotify_previous():
                        print("Skipped to previous track")
                    else:
                        print("Failed to skip to previous track")
                        
                elif spotify_action == 'volume':
                    if len(args) < 2:
                        print("Error: spotify volume requires a level (0-100)")
                        continue
                    try:
                        volume = int(args[1])
                        if controller.spotify_set_volume(volume):
                            print(f"Set Spotify volume to {volume}%")
                        else:
                            print("Failed to set Spotify volume")
                    except ValueError:
                        print("Error: volume must be a number between 0 and 100")
                        
                else:
                    print(f"Unknown spotify action: {spotify_action}")
                    print("Available actions: play, pause, toggle, next, prev, volume")
                    
            elif command == 'quit':
                controller.stop_auto_switching()  # Clean shutdown
                controller.stop_librespot_monitoring()  # Clean shutdown
                controller.stop_spotifyd_monitoring()  # Clean shutdown
                logger.info("Shutting down Audio Controller")
                break
                
            else:
                print(f"Unknown command: {command}")
                print("Type 'help' for available commands")
                
        except KeyboardInterrupt:
            print("\nShutting down...")
            controller.stop_auto_switching()  # Clean shutdown
            controller.stop_librespot_monitoring()  # Clean shutdown
            controller.stop_spotifyd_monitoring()  # Clean shutdown
            break
        except Exception as e:
            logger.error(f"Error processing command: {e}")
            print(f"Error: {e}")

if __name__ == "__main__":
    main()