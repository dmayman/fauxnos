#!/usr/bin/env python3
"""
Audio Source Control and Mixer
------------------------------
This script manages audio source switching between analogsink and snapsink,
with smooth volume transitions and appropriate notification sounds.
"""

# TODO: automatically set sink-inputs based on their name via pactl move-sink-input <sink-input-name> <sink-name>

import logging
from modules.audio_config import load_config, setup_logging, play_sound, get_sound_paths
from modules.audio_pulse import PulseAudioController
from modules.spotify_monitor import SpotifyMonitor, SpotifyController
from modules.analog_monitor import AnalogMonitor

# Load configuration
PLAYER_CONFIG = load_config()

# Set up logging
logger = setup_logging(PLAYER_CONFIG)

# Sound file paths
sound_paths = get_sound_paths(PLAYER_CONFIG)

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
        
        # Initialize audio control modules
        self.pulse_controller = PulseAudioController()
        self.spotify_controller = SpotifyController()
        self.spotify_monitor = SpotifyMonitor(self._handle_spotify_switch)
        self.analog_monitor = AnalogMonitor(self.switch_source, self._get_current_source)
        
        # Read current state from config if available
        self._load_state()
        
        # Always mute all sinks on startup to ensure clean state
        self.sink_volumes = self.pulse_controller.mute_all_sinks(self.id_to_sink)
        
        # Set all sink-inputs volume on startup
        self.pulse_controller.set_all_sink_inputs_volume(75)
        
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
            
        # Start monitoring
        self.spotify_monitor.start_monitoring()
        self.analog_monitor.start_monitoring()

    def _get_current_source(self):
        """Get current source for callbacks"""
        return self.current_source
    
    def _handle_spotify_switch(self, _):
        """Handle spotify source switching from monitor"""
        spotify_sources = [sid for sid in self.source_ids if 'spotify' in sid.lower()]
        if spotify_sources:
            target_spotify_source = spotify_sources[0]
            # Only switch if not already on a Spotify source
            if self.current_source != target_spotify_source:
                logger.info("🎵 Spotifyd started playing - switching to Spotify")
                self.switch_source(target_spotify_source)
            else:
                logger.debug("🎵 Spotifyd playing but already on Spotify source")
        else:
            logger.warning("No Spotify source found in configuration")
    
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






    # Monitoring control methods
    def start_auto_switching(self):
        return self.analog_monitor.start_monitoring()
    
    def stop_auto_switching(self):
        return self.analog_monitor.stop_monitoring()
    
    def stop_spotifyd_monitoring(self):
        return self.spotify_monitor.stop_monitoring()
    
    @property
    def auto_switching_enabled(self):
        return self.analog_monitor.is_enabled()

    def switch_source(self, source):
        """Switch audio source with smooth transitions"""
        new_source = source.lower()
        
        # Validate source exists in config
        if new_source not in self.source_ids:
            logger.error(f"Invalid source: {new_source}. Available sources: {self.source_ids}")
            return
        
        # Check if already on this source (prevent bouncing)
        if new_source == self.current_source:
            logger.debug(f"Already using source {new_source}, skipping switch")
            return
        
        if self.current_source is not None:
            # Play notification sound for source switch
            play_sound(sound_paths['switch'])

        logger.info(f"Switching to {new_source}")
        
        # Fade out all other sinks first, then fade in the selected sink
        for source_id in self.source_ids:
            if source_id != new_source:
                # Fade out other sources
                sink_name = self.id_to_sink[source_id]
                self.sink_volumes[source_id] = self.pulse_controller.fade_volume(
                    sink_name, self.sink_volumes[source_id], 0
                )
        
        # Fade in the selected source to its stored volume level
        target_volume = self.source_volumes[new_source]
        selected_sink = self.id_to_sink[new_source]
        self.sink_volumes[new_source] = self.pulse_controller.fade_volume(
            selected_sink, self.sink_volumes[new_source], target_volume
        )
        
        # Sync systemsink volume to match active source
        self.pulse_controller.sync_systemsink_volume(target_volume)
            
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
                self.pulse_controller.set_sink_volume(sink_name, volume)
                self.source_volumes[self.current_source] = volume
                self.sink_volumes[self.current_source] = volume
                
                # Sync systemsink volume to match active source
                self.pulse_controller.sync_systemsink_volume(volume)
                
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
                self.pulse_controller.set_sink_volume(sink_name, new_volume)
                self.source_volumes[self.current_source] = new_volume
                self.sink_volumes[self.current_source] = new_volume
                
                # Sync systemsink volume to match active source
                self.pulse_controller.sync_systemsink_volume(new_volume)
                
                source_display = self.sources[self.current_source].get("label", self.current_source)
                logger.info(f"Adjusted {source_display} volume to {new_volume}")
            else:
                logger.error("No active source to adjust volume for")
                return
                
            # Play appropriate sound based on direction
            if increment > 0:
                play_sound(sound_paths['volume_up'])
            else:
                play_sound(sound_paths['volume_down'])
                
            self._save_state()
        except ValueError:
            logger.error(f"Invalid increment value: {increment}")

    # Spotify control methods - delegate to SpotifyController
    def spotify_play_pause(self):
        return self.spotify_controller.play_pause()
    
    def spotify_play(self):
        return self.spotify_controller.play()
    
    def spotify_pause(self):
        return self.spotify_controller.pause()
    
    def spotify_next(self):
        return self.spotify_controller.next()
    
    def spotify_previous(self):
        return self.spotify_controller.previous()
    
    def spotify_set_volume(self, volume):
        return self.spotify_controller.set_volume(volume)

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
                controller.stop_auto_switching()
                controller.stop_spotifyd_monitoring()
                logger.info("Shutting down Audio Controller")
                break
                
            else:
                print(f"Unknown command: {command}")
                print("Type 'help' for available commands")
                
        except KeyboardInterrupt:
            print("\nShutting down...")
            controller.stop_auto_switching()
            controller.stop_spotifyd_monitoring()
            break
        except Exception as e:
            logger.error(f"Error processing command: {e}")
            print(f"Error: {e}")

if __name__ == "__main__":
    main()