#!/usr/bin/env python3
"""
Analog Input Monitoring
-----------------------
Handles automatic audio source switching based on analog input activity.
"""

import time
import threading
import logging
import subprocess

logger = logging.getLogger('AudioController')

class AnalogMonitor:
    def __init__(self, source_switch_callback, current_source_callback):
        self.source_switch_callback = source_switch_callback
        self.current_source_callback = current_source_callback
        self.auto_switching_enabled = False
        self.monitoring_thread = None
        self.monitoring_stop_event = threading.Event()
        self._previous_analog_active = False

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
            previous_analog_state = self._previous_analog_active
            self._previous_analog_active = analog_active
            
            logger.debug(f"Analog input: {'active' if analog_active else 'inactive'}")
            
            current_source = self.current_source_callback()
            
            # Only switch to analog if:
            # 1. Analog input just became active (edge detection)
            # 2. OR analog is active and we're not already on analog
            if analog_active and (current_source != "analog" or not previous_analog_state):
                if current_source != "analog":
                    logger.info(f"Analog input detected - switching from {current_source} to analog")
                    self.source_switch_callback("analog")
                else:
                    logger.debug("Analog input active and already on analog source")
            
            # Optional: Switch away from analog when input stops
            # (Comment out if you want to stay on analog even when input stops)
            # elif not analog_active and current_source == "analog":
            #     # Switch to default source (first available)
            #     default_source = self.source_ids[0] if self.source_ids else None
            #     if default_source and default_source != "analog":
            #         logger.info(f"Analog input stopped - switching to {default_source}")
            #         self.source_switch_callback(default_source)
                
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

    def start_monitoring(self):
        """Start automatic source switching (analog input monitoring only)"""
        if self.auto_switching_enabled:
            logger.info("Automatic switching is already enabled")
            return
            
        self.auto_switching_enabled = True
        self.monitoring_stop_event.clear()
        self.monitoring_thread = threading.Thread(target=self._monitoring_loop, daemon=True)
        self.monitoring_thread.start()
        logger.info("Started automatic source switching")

    def stop_monitoring(self):
        """Stop automatic source switching (analog input monitoring only)"""
        if not self.auto_switching_enabled:
            logger.info("Automatic switching is already disabled")
            return
            
        self.auto_switching_enabled = False
        self.monitoring_stop_event.set()
        
        if self.monitoring_thread and self.monitoring_thread.is_alive():
            self.monitoring_thread.join(timeout=5.0)
            
        logger.info("Stopped automatic source switching")

    def is_enabled(self):
        """Check if automatic switching is enabled"""
        return self.auto_switching_enabled