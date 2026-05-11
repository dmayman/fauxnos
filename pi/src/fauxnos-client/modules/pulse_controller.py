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

    def set_loopback_calibration(self, media_role: str, volume: int) -> bool:
        """
        Set the volume of a module-loopback sink-input by its media.role.

        We use module-loopback sink-inputs as fixed pre-amp ceilings between
        per-source virtual sinks (snapsink, analogsink, …) and alsa_output.
        Each loopback in default.pa is given a unique sink_input_properties
        media.role (e.g. 'fauxnos-snapsink-out'); this method finds the
        sink-input matching that role and sets its volume.

        Args:
            media_role: media.role of the loopback sink-input
                (e.g. 'fauxnos-snapsink-out', 'fauxnos-analogsink-out')
            volume: 0-100 percent

        Returns:
            True if a matching sink-input was found and the volume was set.
        """
        if not (0 <= volume <= 100):
            self.logger.error(f"set_loopback_calibration: volume {volume} out of range")
            return False

        try:
            # Find the sink-input id by scanning `pactl list sink-inputs`.
            # sink-input IDs are not stable across reboots, so we always
            # look up by media.role just before setting.
            result = subprocess.run(
                ["pactl", "list", "sink-inputs"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                self.logger.error(f"pactl list sink-inputs failed: {result.stderr}")
                return False

            # Walk the output: the role line, when found, belongs to the
            # most recently seen "Sink Input #N" header.
            current_id = None
            target_id = None
            role_line = f'media.role = "{media_role}"'
            for raw in result.stdout.splitlines():
                line = raw.strip()
                if line.startswith("Sink Input #"):
                    current_id = line.split("#", 1)[1].strip()
                elif role_line in line and current_id is not None:
                    target_id = current_id
                    break

            if target_id is None:
                self.logger.warning(
                    f"set_loopback_calibration: no sink-input found with media.role={media_role}"
                )
                return False

            cmd = ["pactl", "set-sink-input-volume", target_id, f"{volume}%"]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if r.returncode != 0:
                self.logger.error(f"set-sink-input-volume failed: {r.stderr}")
                return False

            self.logger.info(
                f"Calibration set: media.role={media_role} → {volume}% (sink-input #{target_id})"
            )
            return True
        except Exception as e:
            self.logger.error(f"set_loopback_calibration error: {e}")
            return False

    def play_sound(
        self,
        file_path,
        sink_name: str = 'systemsink',
        volume_pct: int = 100,
    ) -> bool:
        """
        Play a WAV file on a PA sink, non-blocking.

        Args:
            file_path: Path to a .wav (16-bit PCM is most reliable). Either
                a pathlib.Path or a str.
            sink_name: Sink to play onto. Defaults to 'systemsink' — the
                fauxnos convention for UI/feedback sounds.
            volume_pct: Playback attenuation 0-100. Maps to paplay's
                --volume arg (0-65536, where 65536 is "normal" / unchanged).
                Lets callers scale individual playbacks independently of
                the sink's own volume — useful for the IR remote feedback
                where we want per-notch sounds quieter than music.

        Returns:
            True if paplay was successfully spawned (we don't wait for
            completion — fire-and-forget so rapid IR presses can overlap).
            False if the file doesn't exist or paplay couldn't launch.
        """
        from pathlib import Path
        p = Path(file_path)
        if not p.is_file():
            self.logger.debug(f"play_sound: missing file {p}")
            return False
        vol = max(0, min(100, int(volume_pct)))
        # paplay --volume scale: 65536 = unchanged. Linear scaling here
        # is fine for short feedback clicks; "perceptual" curves matter
        # more for sustained music playback.
        paplay_vol = int(round(vol * 65536 / 100))
        # --latency-msec=50 shrinks PA's playback buffer for this stream
        # so the WAV starts hitting the DAC ~tens-of-ms after spawn
        # instead of paplay's default several-hundred-ms latency. Matters
        # for IR feedback where the tone is the user's primary "I heard
        # your press" signal.
        cmd = ['paplay', '--device', sink_name, '--latency-msec=50',
               f'--volume={paplay_vol}', str(p)]
        try:
            subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True
        except FileNotFoundError:
            self.logger.warning("play_sound: paplay not on PATH")
            return False
        except Exception as e:
            self.logger.warning(f"play_sound: spawn failed for {p}: {e}")
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
