#!/usr/bin/env python3
"""
Audio Source Control and Mixer
------------------------------
This script manages audio source switching between analogsink, snapsink, and libresink,
with smooth volume transitions and appropriate notification sounds.
"""

import os
import time
import logging
import subprocess
import threading
import json

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
        self.sources = PLAYER_CONFIG.get("sources", {})
        self.source_names = list(self.sources.keys())
        
        # Initialize with neutral values first
        self.current_source = None
        
        # Track the desired volume level (0-100) for each audio source when it's active.
        # These values persist when switching between sources.
        self.source_volumes = {}
        for source_name, source_config in self.sources.items():
            self.source_volumes[source_name] = source_config.get("starting_volume", 20)
        
        # Track the current actual volume (0-100) of each PulseAudio sink.
        # These values represent the hardware/software volume levels in the audio system.
        # Used during volume fades and audio routing.
        self.sink_volumes = {source_name: 0 for source_name in self.source_names}
        
        # Audio monitoring state (excluding snapsink by default)
        self.monitored_sources = [name for name in self.source_names if name != "snapsink"]
        self.source_silent_states = {name: False for name in self.monitored_sources}
        self.auto_switching_enabled = False
        self.monitoring_thread = None
        self.monitoring_stop_event = threading.Event()
        
        # Read current state from config if available
        self._load_state()
        
        # Always mute all sinks on startup to ensure clean state
        self._mute_all_sinks()
        
        # If no previous state was loaded or source is still None, set default source
        if self.current_source is None:
            # Use first available source as default
            default_source = self.source_names[0] if self.source_names else None
            if default_source:
                logger.info(f"No previous state found, setting default source to {default_source}")
                self.switch_source(default_source)
        else:
            logger.info(f"AudioController initialized with source: {self.current_source}")
            # Now switch to the loaded current source to properly set volumes
            self.switch_source(self.current_source)

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
        for source_name in self.source_names:
            self._set_sink_volume(source_name, 0)
            self.sink_volumes[source_name] = 0
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

    def _is_sink_playing_audio(self, sink_name):
        """Check if a sink is currently playing audio using pactl"""
        try:
            # Get sink info from pactl
            result = subprocess.run(
                ["pactl", "list", "sinks"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode != 0:
                logger.error(f"Failed to get sink info: {result.stderr}")
                return False
                
            output = result.stdout
            
            # Find the specific sink section
            sink_found = False
            for line in output.split('\n'):
                if f"Name: {sink_name}" in line:
                    sink_found = True
                    continue
                    
                if sink_found and line.strip().startswith("State:"):
                    state = line.split(":", 1)[1].strip()
                    # Check if sink is in RUNNING state (actively playing audio)
                    is_playing = state == "RUNNING"
                    logger.debug(f"Sink {sink_name} state: {state}, playing: {is_playing}")
                    return is_playing
                    
                # If we hit another sink, stop looking
                if sink_found and line.strip().startswith("Sink #"):
                    break
                    
            logger.warning(f"Sink {sink_name} not found in pactl output")
            return False
            
        except subprocess.TimeoutExpired:
            logger.error(f"Timeout checking audio state for {sink_name}")
            return False
        except Exception as e:
            logger.error(f"Error checking audio state for {sink_name}: {e}")
            return False

    def _auto_source_control(self):
        """Automatic source control with silence state tracking"""
        if not self.auto_switching_enabled:
            return
            
        try:
            # Check audio state for monitored sources
            current_states = {}
            previous_states = {}
            
            for source_name in self.monitored_sources:
                current_states[source_name] = self._is_sink_playing_audio(source_name)
                previous_states[source_name] = not self.source_silent_states[source_name]
                self.source_silent_states[source_name] = not current_states[source_name]
            
            # Log current audio states
            state_info = ", ".join([
                f"{name}: {'playing' if current_states[name] else 'silent'}"
                for name in self.monitored_sources
            ])
            logger.debug(f"Audio states - {state_info}")
            
            # Only switch if a source has gone from silent to playing
            # and the current source is silent
            should_switch = False
            new_source = None
            
            for source_name in self.monitored_sources:
                if source_name == self.current_source:
                    continue
                    
                # Check if this source started playing and current source is silent
                if (not previous_states[source_name] and current_states[source_name] and
                    self.current_source in self.source_silent_states and
                    self.source_silent_states[self.current_source]):
                    should_switch = True
                    new_source = source_name
                    break
                    
                # Also switch if current source is silent and another is playing
                elif (self.current_source in self.source_silent_states and
                      self.source_silent_states[self.current_source] and
                      current_states[source_name]):
                    should_switch = True
                    new_source = source_name
                    break
            
            if should_switch and new_source:
                logger.info(f"Auto-switching from {self.current_source} to {new_source}")
                self.switch_source(new_source)
                
        except Exception as e:
            logger.error(f"Error in automatic source control: {e}")

    def _monitoring_loop(self):
        """Continuous monitoring loop for automatic source control"""
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

    def start_auto_switching(self):
        """Start automatic source switching"""
        if self.auto_switching_enabled:
            logger.info("Automatic switching is already enabled")
            return
            
        self.auto_switching_enabled = True
        self.monitoring_stop_event.clear()
        self.monitoring_thread = threading.Thread(target=self._monitoring_loop, daemon=True)
        self.monitoring_thread.start()
        logger.info("Started automatic source switching")

    def stop_auto_switching(self):
        """Stop automatic source switching"""
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
        if new_source not in self.source_names:
            logger.error(f"Invalid source: {new_source}. Available sources: {self.source_names}")
            return
        
        if self.current_source is not None:
            # Play notification sound for source switch
            self._play_sound(SWITCH_SOUND)

            if new_source == self.current_source:
                logger.info(f"Already using source {new_source}")
                return  
                            
        logger.info(f"Switching to {new_source}")
        
        # Fade out all other sinks first, then fade in the selected sink
        for source_name in self.source_names:
            if source_name != new_source:
                # Fade out other sources
                self.sink_volumes[source_name] = self._fade_volume(
                    source_name, self.sink_volumes[source_name], 0
                )
        
        # Fade in the selected source to its stored volume level
        target_volume = self.source_volumes[new_source]
        self.sink_volumes[new_source] = self._fade_volume(
            new_source, self.sink_volumes[new_source], target_volume
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
                
            if self.current_source and self.current_source in self.source_names:
                self._set_sink_volume(self.current_source, volume)
                self.source_volumes[self.current_source] = volume
                self.sink_volumes[self.current_source] = volume
                source_display = self.sources[self.current_source].get("display_name", self.current_source)
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
            
            if self.current_source and self.current_source in self.source_names:
                current_volume = self.source_volumes[self.current_source]
                new_volume = max(0, min(100, current_volume + increment))
                self._set_sink_volume(self.current_source, new_volume)
                self.source_volumes[self.current_source] = new_volume
                self.sink_volumes[self.current_source] = new_volume
                source_display = self.sources[self.current_source].get("display_name", self.current_source)
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
                source_list = "|".join(controller.source_names)
                print(f"  source [{source_list}] - Switch audio source")
                print("  volume [0-100]         - Set volume level")
                print("  adjust [+/-N]          - Adjust volume by N")
                print("  auto [on|off]          - Enable/disable automatic switching")
                print("  status                 - Show current state")
                print("  quit                   - Exit program")
                print("  help                   - Show this help")
                
            elif command == 'source':
                if not args or args[0] not in controller.source_names:
                    source_list = "', '".join(controller.source_names)
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
                    source_display = controller.sources[controller.current_source].get("display_name", controller.current_source)
                    print(f"  Source: {source_display} ({controller.current_source})")
                    
                for source_name in controller.source_names:
                    source_display = controller.sources[source_name].get("display_name", source_name)
                    volume = controller.source_volumes[source_name]
                    sink_volume = controller.sink_volumes[source_name]
                    print(f"  {source_display} volume: {volume}% (sink volume: {sink_volume}%)")
                    
                print(f"  Auto-switching: {'enabled' if controller.auto_switching_enabled else 'disabled'}")
                if controller.auto_switching_enabled:
                    for source_name in controller.monitored_sources:
                        source_display = controller.sources[source_name].get("display_name", source_name)
                        silent = controller.source_silent_states[source_name]
                        print(f"  {source_display} silent: {silent}")
                
            elif command == 'quit':
                controller.stop_auto_switching()  # Clean shutdown
                logger.info("Shutting down Audio Controller")
                break
                
            else:
                print(f"Unknown command: {command}")
                print("Type 'help' for available commands")
                
        except KeyboardInterrupt:
            print("\nShutting down...")
            controller.stop_auto_switching()  # Clean shutdown
            break
        except Exception as e:
            logger.error(f"Error processing command: {e}")
            print(f"Error: {e}")

if __name__ == "__main__":
    main()