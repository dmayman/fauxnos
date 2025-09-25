#!/usr/bin/env python3
"""
PulseAudio Volume Control
------------------------
Handles PulseAudio sink volume management and fade operations.
"""

import time
import logging
import subprocess
import threading
from modules.audio_config import FADE_STEP, FADE_DELAY

logger = logging.getLogger('AudioController')

try:
    from pulsectl import Pulse
    # Try to import event types - they may not exist in older versions
    try:
        from pulsectl import PulseEventType, PulseEventFacility
        HAS_EVENT_TYPES = True
    except ImportError:
        # Use string constants for older versions
        HAS_EVENT_TYPES = False
        logger.info("Using string constants for pulse events (older pulsectl version)")
    
    PULSECTL_AVAILABLE = True
    logger.info("pulsectl library imported successfully")
except ImportError as e:
    PULSECTL_AVAILABLE = False
    HAS_EVENT_TYPES = False
    logger.error(f"Failed to import pulsectl: {e}")
except Exception as e:
    PULSECTL_AVAILABLE = False
    HAS_EVENT_TYPES = False
    logger.error(f"Unexpected error importing pulsectl: {e}")

class PulseAudioController:
    def __init__(self):
        self._event_monitor_thread = None
        self._event_monitor_running = False
        self._snapclient_callback = None
        self._pulse = None

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

    def move_snapclient_to_snapsink(self):
        """Move snapclient sink-input to snapsink if it's not already there"""
        logger.debug("Checking for snapclient sink-inputs to move to snapsink")
        try:
            # Get list of sink-inputs with detailed info
            result = subprocess.run(
                ["pactl", "list", "sink-inputs"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                logger.error(f"Failed to get sink-inputs: {result.stderr}")
                return False
            
            # Parse output to find snapclient sink-input
            current_input_id = None
            current_sink = None
            in_snapclient_section = False
            found_snapclient = False
            moved_any = False
            
            for line in result.stdout.split('\n'):
                line = line.strip()
                
                # Start of a new sink-input section
                if line.startswith('Sink Input #'):
                    # Process previous snapclient if we found one
                    if in_snapclient_section and current_input_id and current_sink:
                        found_snapclient = True
                        if current_sink != 'snapsink':
                            logger.info(f"Moving snapclient from {current_sink} to snapsink")
                            move_result = subprocess.run(
                                ["pactl", "move-sink-input", current_input_id, "snapsink"],
                                capture_output=True,
                                text=True,
                                timeout=5
                            )
                            
                            if move_result.returncode == 0:
                                logger.info(f"Successfully moved snapclient sink-input {current_input_id} to snapsink")
                                moved_any = True
                            else:
                                logger.error(f"Failed to move snapclient: {move_result.stderr}")
                        else:
                            logger.debug(f"snapclient {current_input_id} already on snapsink")
                    
                    # Reset for new sink-input
                    in_snapclient_section = False
                    current_input_id = line.split('#')[1]
                    current_sink = None
                
                # Check if this is snapclient (try multiple possible property names)
                elif ('application.name = "snapclient"' in line or 
                      'application.process.binary = "snapclient"' in line or
                      'media.name = "snapclient"' in line):
                    logger.debug(f"Found snapclient sink-input {current_input_id}")
                    in_snapclient_section = True
                
                # Get current sink (this appears before we know it's snapclient)
                elif line.startswith('Sink:'):
                    sink_info = line.split(':', 1)[1].strip()
                    current_sink = sink_info
            
            # Process the last snapclient if we found one
            if in_snapclient_section and current_input_id and current_sink:
                found_snapclient = True
                if current_sink != 'snapsink':
                    logger.info(f"Moving snapclient from {current_sink} to snapsink")
                    move_result = subprocess.run(
                        ["pactl", "move-sink-input", current_input_id, "snapsink"],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    
                    if move_result.returncode == 0:
                        logger.info(f"Successfully moved snapclient sink-input {current_input_id} to snapsink")
                        moved_any = True
                    else:
                        logger.error(f"Failed to move snapclient: {move_result.stderr}")
                else:
                    logger.debug(f"snapclient {current_input_id} already on snapsink")
            
            if not found_snapclient:
                logger.debug("No snapclient sink-input found")
                
            return found_snapclient
            
        except subprocess.TimeoutExpired:
            logger.error("Timeout while checking sink-inputs for snapclient")
            return False
        except Exception as e:
            logger.error(f"Error moving snapclient to snapsink: {e}")
            return False

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

    def start_event_monitoring(self, snapclient_callback=None):
        """Start monitoring PulseAudio events for sink-input changes"""
        if not PULSECTL_AVAILABLE:
            logger.error("pulsectl library not available, cannot start event monitoring")
            return False
            
        if self._event_monitor_running:
            logger.debug("PulseAudio event monitoring already running")
            return True
            
        self._snapclient_callback = snapclient_callback
        self._event_monitor_running = True
        self._event_monitor_thread = threading.Thread(
            target=self._event_monitor_worker,
            daemon=True,
            name="PulseEventMonitor"
        )
        self._event_monitor_thread.start()
        logger.info("Started PulseAudio event monitoring using pulsectl")
        return True

    def stop_event_monitoring(self):
        """Stop monitoring PulseAudio events"""
        if not self._event_monitor_running:
            return
            
        self._event_monitor_running = False
        
        # Close pulse connection to break out of event_listen()
        if self._pulse:
            try:
                self._pulse.close()
            except:
                pass
            self._pulse = None
            
        if self._event_monitor_thread and self._event_monitor_thread.is_alive():
            self._event_monitor_thread.join(timeout=2)
        logger.info("Stopped PulseAudio event monitoring")

    def _on_pulse_event(self, ev):
        """Handle PulseAudio events"""
        # Check for new sink-input events (handle both old and new pulsectl versions)
        if HAS_EVENT_TYPES:
            # New version with enum types
            is_sink_input_new = (ev.facility == PulseEventFacility.sink_input and 
                                ev.t == PulseEventType.new)
        else:
            # Older version with string constants
            is_sink_input_new = (ev.facility == 'sink_input' and ev.t == 'new')
        
        if is_sink_input_new:
            logger.info(f"New sink-input #{ev.index} added - checking for snapclient")
            
            # Small delay to ensure the sink-input is fully created
            time.sleep(0.1)
            
            # Trigger callback to check for snapclient
            if self._snapclient_callback:
                try:
                    self._snapclient_callback()
                except Exception as e:
                    logger.error(f"Error in snapclient callback: {e}")
            else:
                logger.warning("No snapclient callback registered")

    def _event_monitor_worker(self):
        """Worker thread for monitoring PulseAudio events"""
        logger.info("PulseAudio event monitor started")
        
        try:
            with Pulse('fauxnos-snapclient-monitor') as pulse:
                self._pulse = pulse
                
                # Subscribe to sink-input events only
                pulse.event_mask_set('sink_input')
                pulse.event_callback_set(self._on_pulse_event)
                
                # This blocks until the pulse connection is closed
                pulse.event_listen()
                
        except Exception as e:
            if self._event_monitor_running:
                logger.error(f"Error in PulseAudio event monitor: {e}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
        finally:
            self._pulse = None
            logger.info("PulseAudio event monitor stopped")