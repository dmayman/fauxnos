# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Fauxnos is a DIY multiroom audio system inspired by Sonos, designed to run on Raspberry Pi devices. It combines modified open-source audio software with custom control interfaces to create a seamless multiroom audio experience.

## Key Commands

### Running the Audio Controller
```bash
# Navigate to the Pi source directory
cd pi/src

# Run the main audio controller (interactive mode)
python fauxnos-client.py

# Run with background logging
python fauxnos-client.py > /dev/null 2>&1 &
```

### Building Librespot (Modified)
```bash
cd librespot
cargo build --release --features with-pipe
```

# Test hardware audio output
speaker-test -t wav -c 2

# List audio devices
aplay -l

# Test individual volume controls
amixer set softvol_librespot 80%
amixer set softvol_snapcast 80%
amixer set softvol_analog 80%
amixer set softvol_system 80%
```

### Installing Dependencies
```bash
# Python dependencies
pip3 install dbus-next --break-system-packages

# System dependencies for Raspberry Pi
sudo apt install build-essential git libasound2 libasound2-dev libssl-dev libpulse-dev cmake libclang-dev
sudo apt install playerctl dbus-x11 libglib2.0-bin
```

## Architecture Overview

### Core Components

**Python Audio Controller** (`pi/src/fauxnos-client.py`)
- Central orchestrator for audio source management
- Handles PulseAudio routing, volume control, and source switching
- Provides interactive CLI interface for control
- Modular design with separate components in `modules/`

**Modified Librespot** (`librespot/`)
- Custom Rust fork with external volume control
- Bypasses Spotify's volume control for hardware integration
- Provides DBUS integration for state monitoring

**Audio Pipeline**
- PulseAudio virtual sinks: `spotifysink`, `snapsink`, `analogsink`, `systemsink`
- ALSA configuration with software volume controls
- Hardware output via HiFiBerry DAC+

### Module Structure

- `modules/audio_config.py` - Configuration loading and logging setup
- `modules/audio_pulse.py` - PulseAudio control and volume management
- `modules/spotify_monitor.py` - Spotify DBUS monitoring and playerctl integration
- `modules/analog_monitor.py` - Analog input detection and auto-switching

### Configuration System

**Device Configuration** (`pi/src/config.json`)
- Audio source definitions (internal vs external)
- Volume settings and external control APIs
- Sound file paths for UI feedback
- MQTT/webhook integration endpoints

**Audio Sources**
- **Internal**: Direct PulseAudio routing (Spotify, Multiroom/Snapcast, Analog)
- **External**: API-controlled sources (Alexa, Vinyl, Aux)

## Development Patterns

### Audio Source Switching
- Configuration-driven source definitions
- Smooth volume fade transitions between sources
- Automatic switching based on audio detection (analog input) and Spotify playback events
- Per-source volume memory and external control integration

### DBUS Event Handling
- Spotify state monitoring via DBUS properties interface
- Proper handler registration/deregistration to prevent duplicate events
- Thread-safe callback mechanisms for source switching

### Volume Control Architecture
- Linear volume scaling for system sink (10-40% range mapped from source 0-100%)
- Independent volume controls per audio source
- Hardware volume control bypass for Spotify integration

### Error Handling
- Robust retry logic for Spotify connection monitoring
- Graceful handling of audio hardware disconnections
- Subprocess reliability using `os.system()` instead of `subprocess` module

## Important Implementation Notes

### Spotify Integration
- Uses modified librespot with external volume control flag
- DBUS monitoring for playback state changes
- playerctl for transport controls (play/pause/next/previous)
- gdbus for direct volume control bypassing playerctl limitations

### PulseAudio Configuration
- Virtual sinks route to hardware via module-loopback
- Use `sink=` parameter for loopback modules, not `sink_master=`
- Software volume control due to HiFiBerry DAC Lite limitations

### Threading and Async
- Spotify monitoring runs in dedicated thread with asyncio event loop
- Analog monitoring uses threading for non-blocking audio detection
- Source switching callbacks are thread-safe

### Audio Detection
- Analog input monitoring via `parec` subprocess
- Threshold-based silence detection for automatic source switching
- Debounced switching to prevent rapid oscillation

## Platform Support

### Current Implementation
- **Raspberry Pi Zero 2 W**: Primary target platform
- **HiFiBerry DAC+**: Audio output hardware
- **Python 3**: Core control logic
- **Rust**: Modified librespot for Spotify integration

### Future Platforms
- iOS app (Swift/SwiftUI project exists)
- Web interface (React-based)
- HomeKit integration (Homebridge plugin template)

## MQTT Protocol

The system defines an MQTT protocol for remote control:
- Device status topics: `status/clients/<deviceId>/{hello,mode,volume,activity}`
- Control topics: `set/clients/<deviceId>/{volume,mode}` and `get/clients/<deviceId>/{volume,status,activity}`
- Supports device capabilities announcement and centralized control

## Testing and Debugging

### Audio Pipeline Testing
Test each component of the audio pipeline individually:
1. Hardware detection (`aplay -l`)
2. Audio output (`speaker-test -t wav -c 2`)
3. Individual source volume controls
4. PulseAudio sink routing

### Common Issues
- **Duplicate DBUS events**: Ensure proper handler deregistration in spotify_monitor.py
- **Volume scaling**: Verify systemsink linear scaling (10-40% range)
- **Source switching bouncing**: Check debouncing logic in analog input detection
- **Import errors**: Use absolute imports (`from modules.module_name`) not relative imports

## Dependencies and Installation

Follow `INSTALLATION.md` for complete Raspberry Pi setup. Key dependencies:
- Python: `dbus-next` library for DBUS integration
- System: `playerctl`, `pulseaudio`, `alsa-utils`
- Rust toolchain for librespot compilation
- Optional: `snapcast` for multiroom audio synchronization