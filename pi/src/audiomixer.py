#!/usr/bin/env python3
"""
Audio Source Control and Mixer
------------------------------
This script manages audio source switching between Squeezelite and Analog input,
with smooth volume transitions and appropriate notification sounds.
"""

import os
import time
import logging
import argparse
import subprocess
import threading
import json
from enum import Enum

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

class AudioSource(Enum):
    SQUEEZE = "squeeze"
    ANALOG = "analog"

class AudioController:
    def __init__(self):
        # Initialize with neutral values first
        self.current_source = None
        self.squeeze_volume = 100  # Default Squeezelite volume (0-100)
        self.analog_volume = 100   # Default Analog volume (0-100)
        self.squeeze_sink_volume = 0
        self.analog_sink_volume = 0
        
        # Read current state from config if available
        self._load_state()
        
        # If no previous state was loaded or source is still None, set default source
        if self.current_source is None:
            # This will properly set up all sinks and trigger any necessary commands
            logger.info("No previous state found, setting default source to analog")
            self.switch_source(AudioSource.ANALOG.value)
        else:
            logger.info(f"AudioController initialized with source: {self.current_source.value}")
            
            # Ensure sink volumes match the current source
            if self.current_source == AudioSource.ANALOG:
                self._set_sink_volume("analogsink", 100)
                self._set_sink_volume("squeezesink", 0)
            else:
                self._set_sink_volume("squeezesink", 100)
                self._set_sink_volume("analogsink", 0)

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
        """Play notification sound"""
        try:
            subprocess.run(["aplay", "-D", "pulse:systemsink", sound_file], 
                          stdout=subprocess.DEVNULL, 
                          stderr=subprocess.DEVNULL)
        except Exception as e:
            logger.error(f"Error playing sound {sound_file}: {e}")

    def _set_sink_volume(self, sink, volume):
        """Set volume for the specified sink"""
        try:
            subprocess.run(["pactl", "set-sink-volume", sink, f"{volume}%"], 
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL)
        except Exception as e:
            logger.error(f"Error setting {sink} volume to {volume}: {e}")

    def _send_squeeze_command(self, command, params=None, description=""):
        """Send a command to the Squeezelite player using LMS API
        
        Args:
            command (str or list): The command to send (e.g., "play", "pause")
            params (list, optional): Additional parameters for the command
            description (str, optional): Description for logging
        """
        try:
            player_id = PLAYER_CONFIG.get("mac")
            if not player_id:
                logger.error("No MAC address configured for Squeezelite player")
                return
                
            server_ip = PLAYER_CONFIG["lms_server"]["ip"]
            server_port = PLAYER_CONFIG["lms_server"]["port"]
            
            # Prepare the command list
            cmd_list = command if isinstance(command, list) else [command]
            if params:
                cmd_list.extend(params)
            
            # Create JSON payload
            json_payload = json.dumps({
                "id": 1,
                "method": "slim.request",
                "params": [player_id, cmd_list]
            })
            
            # Create a temporary file for the JSON payload
            with open("/tmp/lms_request.json", "w") as f:
                f.write(json_payload)
            
            # Using curl with POST method
            cmd = [
                "curl", "-s", "-X", "POST", 
                "-H", "Content-Type: application/json",
                "--data", "@/tmp/lms_request.json",
                f"http://{server_ip}:{server_port}/jsonrpc.js"
            ]
            
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # Log the action if description is provided
            if description:
                logger.info(f"{description} for player {PLAYER_CONFIG['name']}")
            
            # Clean up temporary file
            os.remove("/tmp/lms_request.json")
            return True
        except Exception as e:
            logger.error(f"Error sending command to Squeezelite: {e}")
            return False
            
    def _pause_squeeze(self):
        """Pause Squeezelite playback"""
        self._send_squeeze_command("pause", description="Paused Squeezelite playback")

    def _play_squeeze(self):
        """Play Squeezelite playback"""
        self._send_squeeze_command("play", description="Started Squeezelite playback")

    def _set_squeeze_volume(self, volume):
        """Set volume for Squeezelite player"""
        if PLAYER_CONFIG.get("type") != "squeeze" and PLAYER_CONFIG.get("type") is not None:
            logger.error("Attempted to set Squeezelite volume for non-Squeezelite player")
            return
            
        if self._send_squeeze_command("mixer", ["volume", str(volume)], 
                                    description=f"Set Squeezelite volume to {volume}"):
            self.squeeze_volume = volume

    def _fade_volume(self, sink, start_vol, end_vol):
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

    def _parallel_fade(self, fade_params):
        """Execute multiple fades in parallel"""
        threads = []
        results = {}
        
        def fade_worker(sink, start_vol, end_vol):
            results[sink] = self._fade_volume(sink, start_vol, end_vol)
            
        for sink, start_vol, end_vol in fade_params:
            thread = threading.Thread(
                target=fade_worker,
                args=(sink, start_vol, end_vol)
            )
            threads.append(thread)
            thread.start()
            
        # Wait for all fades to complete
        for thread in threads:
            thread.join()
            
        return results

    def switch_source(self, source):
        """Switch audio source with smooth transitions"""
        new_source = AudioSource(source.lower())
        
        if self.current_source is not None:
            # Play notification sound for source switch
            self._play_sound(SWITCH_SOUND)

            if new_source.value == self.current_source.value:
                logger.info(f"Already using source {new_source.value}")
                return  
                            
        if new_source == AudioSource.ANALOG:
            # Switching from Squeeze to Analog
            logger.info("Switching from Squeeze to Analog")
            
            # First fade out Squeeze completely
            self.squeeze_sink_volume = self._fade_volume("squeezesink", self.squeeze_sink_volume, 0)
            
            # Then pause Squeezelite playback (only after fade is complete)
            self._pause_squeeze()
            
            # Finally fade in Analog
            self.analog_sink_volume = self._fade_volume("analogsink", self.analog_sink_volume, 100)
            
        else:  # Switching from Analog to Squeeze
            logger.info("Switching from Analog to Squeeze")
            
            # First fade out Analog
            self.analog_sink_volume = self._fade_volume("analogsink", self.analog_sink_volume, 0)
            
            # Start playback on Squeeze before fading in
            self._play_squeeze()
            
            # Then fade in Squeeze
            self.squeeze_sink_volume = self._fade_volume("squeezesink", self.squeeze_sink_volume, 100)
            
        self.current_source = new_source
        self._save_state()
        logger.info(f"Source switched to {self.current_source.value}")

    def set_volume(self, volume):
        """Set volume for active source"""
        try:
            volume = int(volume)
            if volume < 0 or volume > 100:
                logger.error(f"Invalid volume level: {volume}")
                return
                
            if self.current_source == AudioSource.SQUEEZE:
                self._set_squeeze_volume(volume)
                self.squeeze_volume = volume
                logger.info(f"Set Squeezelite volume to {volume}")
            else:
                self._set_sink_volume("analogsink", volume)
                self.analog_volume = volume
                logger.info(f"Set Analog volume to {volume}")
                
            self._save_state()
        except ValueError:
            logger.error(f"Invalid volume value: {volume}")

    def adjust_volume(self, increment):
        """Adjust volume up or down for active source"""
        try:
            increment = int(increment)
            
            if self.current_source == AudioSource.SQUEEZE:
                new_volume = max(0, min(100, self.squeeze_volume + increment))
                self._set_squeeze_volume(new_volume)
                self.squeeze_volume = new_volume
                logger.info(f"Adjusted Squeezelite volume to {new_volume}")
            else:
                new_volume = max(0, min(100, self.analog_volume + increment))
                self._set_sink_volume("analogsink", new_volume)
                self.analog_volume = new_volume
                logger.info(f"Adjusted Analog volume to {new_volume}")
                
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
                print("  source [squeeze|analog] - Switch audio source")
                print("  volume [0-100]         - Set volume level")
                print("  adjust [+/-N]          - Adjust volume by N")
                print("  status                 - Show current state")
                print("  quit                   - Exit program")
                print("  help                   - Show this help")
                
            elif command == 'source':
                if not args or args[0] not in ['squeeze', 'analog']:
                    print("Error: source must be 'squeeze' or 'analog'")
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
                    
            elif command == 'status':
                print(f"\nCurrent state:")
                if controller.current_source is None:
                    print(f"  Source: Not set")
                else:
                    print(f"  Source: {controller.current_source.value}")
                print(f"  Squeeze volume: {controller.squeeze_volume}%")
                print(f"  Analog volume: {controller.analog_volume}%")
                
            elif command == 'quit':
                logger.info("Shutting down Audio Controller")
                break
                
            else:
                print(f"Unknown command: {command}")
                print("Type 'help' for available commands")
                
        except KeyboardInterrupt:
            print("\nShutting down...")
            break
        except Exception as e:
            logger.error(f"Error processing command: {e}")
            print(f"Error: {e}")

if __name__ == "__main__":
    main()