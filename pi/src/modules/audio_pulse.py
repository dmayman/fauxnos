#!/usr/bin/env python3
"""
PulseAudio Volume Control
------------------------
Handles PulseAudio sink volume management and fade operations.
"""

import time
import logging
import subprocess
from modules.audio_config import FADE_STEP, FADE_DELAY

logger = logging.getLogger('AudioController')

class PulseAudioController:
    def __init__(self):
        pass

    def set_sink_volume(self, sink, volume):
        """Set volume for the specified sink"""
        try:
            subprocess.run(["pactl", "set-sink-volume", sink, f"{volume}%"], 
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL)
        except Exception as e:
            logger.error(f"Error setting {sink} volume to {volume}: {e}")

    def mute_all_sinks(self, sink_mapping):
        """Mute all configured sinks to 0 volume"""
        logger.info("Muting all sinks on startup")
        sink_volumes = {}
        for source_id, sink_name in sink_mapping.items():
            self.set_sink_volume(sink_name, 0)
            sink_volumes[source_id] = 0
        logger.info("All sinks muted")
        return sink_volumes

    def fade_volume(self, sink, start_vol, end_vol):
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
            self.set_sink_volume(sink, current_vol)
            time.sleep(FADE_DELAY)
            
        # Ensure we reach the exact target volume
        self.set_sink_volume(sink, end_vol)
        
        logger.info(f"Faded {sink} volume from {start_vol} to {end_vol}")
        return end_vol

    def set_all_sink_inputs_volume(self, volume=100):
        """Set volume for all sink-inputs to specified level (default 100%)"""
        try:
            # Get list of sink-inputs
            result = subprocess.run(
                ["pactl", "list", "short", "sink-inputs"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                logger.error(f"Failed to get sink-inputs: {result.stderr}")
                return
            
            sink_inputs = result.stdout.strip().split('\n')
            if not sink_inputs or sink_inputs == ['']:
                logger.info("No sink-inputs found")
                return
            
            logger.info(f"Setting all sink-inputs to {volume}% volume")
            
            for line in sink_inputs:
                if line.strip():
                    # Parse sink-input ID (first column)
                    parts = line.split('\t')
                    if len(parts) > 0:
                        sink_input_id = parts[0]
                        try:
                            subprocess.run(
                                ["pactl", "set-sink-input-volume", sink_input_id, f"{volume}%"],
                                check=True,
                                capture_output=True,
                                timeout=5
                            )
                            logger.debug(f"Set sink-input {sink_input_id} volume to {volume}%")
                        except subprocess.CalledProcessError as e:
                            logger.warning(f"Failed to set volume for sink-input {sink_input_id}: {e}")
                        except Exception as e:
                            logger.error(f"Error setting volume for sink-input {sink_input_id}: {e}")
            
            logger.info(f"Completed setting all sink-inputs to {volume}% volume")
            
        except subprocess.TimeoutExpired:
            logger.error("Timeout while getting sink-inputs list")
        except Exception as e:
            logger.error(f"Error setting sink-inputs volume: {e}")

    def sync_systemsink_volume(self, source_volume):
        """Sync systemsink volume with linear scaling between 10% and 40%"""
        try:
            # Linear scaling: 0% source -> 10% system, 100% source -> 40% system
            # Formula: system_volume = 10 + (source_volume * 30 / 100)
            system_volume = 10 + (source_volume * 30 / 100)
            system_volume = int(round(system_volume))
            
            self.set_sink_volume("systemsink", system_volume)
            logger.debug(f"Synced systemsink volume to {system_volume}% (source: {source_volume}%)")
        except Exception as e:
            logger.error(f"Error syncing systemsink volume: {e}")