# Fauxnos PulseAudio Configuration

This configuration sets up a multi-sink audio system with equalization for Fauxnos.

## Installation

1. Copy `default.pa` to `~/.config/pulse/`
2. Restart PulseAudio:
   ```bash
   systemctl --user daemon-reload
   systemctl --user restart pulseaudio
   ```

## Configuration

### Audio Sinks
- `spotifysink`: Spotifyd output
- `systemsink`: System sounds
- `analogsink`: Analog audio input
- `snapsink`: Snapcast output (default)

All audio is equalized using LADSPA and routed to `snapsink` by default.