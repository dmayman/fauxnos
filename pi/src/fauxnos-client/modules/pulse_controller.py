#!/usr/bin/env python3
"""
PulseAudio Controller

Handles all PulseAudio sink operations including volume control and fading
"""

import logging
import subprocess
import time
from typing import Optional


class PulseAudioController:
    """Controls PulseAudio sinks via pactl commands"""

    # Volume fading parameters
    FADE_STEP = 5  # Volume change per step (%)
    FADE_DELAY = 0.05  # Delay between steps (seconds)

    def __init__(self):
        """Initialize PulseAudio controller"""
        self.logger = logging.getLogger(__name__)

    def set_sink_volume(self, sink_name: str, volume: int) -> bool:
        """
        Set PulseAudio sink volume

        Args:
            sink_name: Name of the sink (e.g., 'snapsink', 'analogsink')
            volume: Volume level (0-100)

        Returns:
            True if successful, False otherwise
        """
        # Clamp volume to valid range
        volume = max(0, min(100, volume))

        try:
            # pactl uses percentage format
            cmd = f"pactl set-sink-volume {sink_name} {volume}%"
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                self.logger.debug(f"Set {sink_name} volume to {volume}%")
                return True
            else:
                self.logger.error(f"Failed to set {sink_name} volume: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            self.logger.error(f"Timeout setting {sink_name} volume")
            return False
        except Exception as e:
            self.logger.error(f"Error setting {sink_name} volume: {e}")
            return False

    def get_sink_volume(self, sink_name: str) -> Optional[int]:
        """
        Get current sink volume

        Args:
            sink_name: Name of the sink

        Returns:
            Volume level (0-100) or None if error
        """
        try:
            # Get sink info and parse volume
            cmd = f"pactl get-sink-volume {sink_name}"
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                # Parse output like "Volume: front-left: 32768 /  50% / -18.06 dB"
                output = result.stdout.strip()
                if '%' in output:
                    # Extract percentage
                    parts = output.split('%')[0].split('/')
                    if len(parts) >= 2:
                        volume_str = parts[-1].strip()
                        return int(volume_str)

                self.logger.warning(f"Could not parse volume from: {output}")
                return None
            else:
                self.logger.error(f"Failed to get {sink_name} volume: {result.stderr}")
                return None

        except Exception as e:
            self.logger.error(f"Error getting {sink_name} volume: {e}")
            return None

    def mute_sink(self, sink_name: str) -> bool:
        """
        Mute a sink (set volume to 0)

        Args:
            sink_name: Name of the sink

        Returns:
            True if successful
        """
        return self.set_sink_volume(sink_name, 0)

    def fade_volume(self, sink_name: str, from_volume: int, to_volume: int) -> int:
        """
        Smoothly fade sink volume from one level to another

        Args:
            sink_name: Name of the sink
            from_volume: Starting volume (0-100)
            to_volume: Target volume (0-100)

        Returns:
            Final volume level reached
        """
        # Clamp volumes
        from_volume = max(0, min(100, from_volume))
        to_volume = max(0, min(100, to_volume))

        if from_volume == to_volume:
            return from_volume

        self.logger.debug(f"Fading {sink_name}: {from_volume}% → {to_volume}%")

        # Determine direction and step
        if to_volume > from_volume:
            step = self.FADE_STEP
        else:
            step = -self.FADE_STEP

        current = from_volume

        # Fade volume step by step
        while True:
            # Check if we've reached or passed the target
            if step > 0 and current >= to_volume:
                break
            if step < 0 and current <= to_volume:
                break

            # Take a step
            current += step
            current = max(0, min(100, current))  # Clamp

            # Set volume
            self.set_sink_volume(sink_name, current)

            # Wait before next step
            time.sleep(self.FADE_DELAY)

        # Ensure we end exactly at target
        self.set_sink_volume(sink_name, to_volume)

        self.logger.debug(f"Fade complete: {sink_name} at {to_volume}%")
        return to_volume

    def sink_exists(self, sink_name: str) -> bool:
        """
        Check if a sink exists

        Args:
            sink_name: Name of the sink

        Returns:
            True if sink exists, False otherwise
        """
        try:
            cmd = "pactl list sinks short"
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                # Check if sink name appears in output
                return sink_name in result.stdout
            else:
                self.logger.warning(f"Could not list sinks: {result.stderr}")
                return False

        except Exception as e:
            self.logger.error(f"Error checking if {sink_name} exists: {e}")
            return False

    def list_sinks(self) -> list:
        """
        List all available PulseAudio sinks

        Returns:
            List of sink names
        """
        try:
            cmd = "pactl list sinks short"
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                sinks = []
                for line in result.stdout.strip().split('\n'):
                    if line:
                        # Format: "ID    NAME    DRIVER    SAMPLE_SPEC    STATE"
                        parts = line.split()
                        if len(parts) >= 2:
                            sinks.append(parts[1])
                return sinks
            else:
                self.logger.error(f"Failed to list sinks: {result.stderr}")
                return []

        except Exception as e:
            self.logger.error(f"Error listing sinks: {e}")
            return []


# Standalone testing
if __name__ == '__main__':
    import argparse

    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    parser = argparse.ArgumentParser(description='Test PulseAudio controller')
    parser.add_argument('command', choices=['list', 'volume', 'fade', 'mute'])
    parser.add_argument('--sink', help='Sink name')
    parser.add_argument('--volume', type=int, help='Volume level (0-100)')
    parser.add_argument('--from-volume', type=int, help='Start volume for fade')
    parser.add_argument('--to-volume', type=int, help='End volume for fade')

    args = parser.parse_args()

    controller = PulseAudioController()

    if args.command == 'list':
        print("Available sinks:")
        for sink in controller.list_sinks():
            print(f"  - {sink}")

    elif args.command == 'volume':
        if not args.sink or args.volume is None:
            print("Error: --sink and --volume required")
        else:
            if controller.set_sink_volume(args.sink, args.volume):
                print(f"Set {args.sink} to {args.volume}%")
            else:
                print(f"Failed to set volume")

    elif args.command == 'fade':
        if not args.sink or args.from_volume is None or args.to_volume is None:
            print("Error: --sink, --from-volume, and --to-volume required")
        else:
            final = controller.fade_volume(args.sink, args.from_volume, args.to_volume)
            print(f"Faded {args.sink} to {final}%")

    elif args.command == 'mute':
        if not args.sink:
            print("Error: --sink required")
        else:
            if controller.mute_sink(args.sink):
                print(f"Muted {args.sink}")
            else:
                print(f"Failed to mute {args.sink}")
