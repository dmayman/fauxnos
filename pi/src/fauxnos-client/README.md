# Fauxnos Client

Client-side audio source management and multiroom audio system for Fauxnos.

## Overview

The Fauxnos client manages local audio sources with intelligent volume routing:

- **Internal sources**: PulseAudio-based sources (Spotify via Snapcast, analog input)
- **External sources**: Downstream-controlled sources (Alexa, vinyl, aux)
- **Smart volume control**: Routes volume control to PA sinks or Snapcast based on config
- **State persistence**: Remembers current source and volumes across restarts
- **Smooth transitions**: Fades volume when switching sources
- **Modular architecture**: Clean separation of concerns with dedicated modules

## 💾 Pi OS Setup

### 1. Flash Raspberry Pi OS Lite (32-bit)

1. **Download Raspberry Pi Imager**: https://www.raspberrypi.com/software/
2. **Insert SD card** into your computer
3. **Open Pi Imager** and configure:
   - **OS**: Choose "Raspberry Pi OS Lite (32-bit)"
   - **Storage**: Select your SD card
   - **Settings** (gear icon):
     - ✅ Enable SSH (use password authentication)
     - ✅ Set username/password (default: `pi` / `raspberry`)
     - ✅ Configure WiFi (SSID and password)
     - ✅ Set locale settings (timezone, keyboard layout)
4. **Write** the image to SD card
5. **Insert SD card** into Pi and boot
6. **Find Pi IP address** (check router admin or use network scanner)
7. **SSH into Pi**: `ssh pi@192.168.x.x`

## 🚀 One-Command Installation

After SSH'ing into your **fresh Pi OS Lite** installation, run this single command:

```bash
curl -sSL https://raw.githubusercontent.com/dmayman/fauxnos/main/pi/src/fauxnos-client/install.sh | bash
```

This will:
- ✅ Install all system dependencies
- ✅ Configure audio and network settings
- ✅ Download the complete client system
- ✅ Auto-discover and register with fauxnos-server
- ✅ Deploy and start all services
- ✅ Reboot into fully operational state

## 📋 Manual Installation Steps

If you prefer step-by-step installation:

### 1. System Preparation
```bash
# Download and run Pi setup
curl -sSL https://raw.githubusercontent.com/dmayman/fauxnos/main/pi/src/fauxnos-client/pi-setup.sh | sudo bash

# Or with options
sudo bash pi-setup.sh --skip-updates --verbose
```

### 2. Client Installation
```bash
# After system reboot, install client
cd ~/src
curl -sSL https://raw.githubusercontent.com/dmayman/fauxnos/main/pi/src/fauxnos-client/install.sh | bash
```

### 3. Manual Registration (if needed)
```bash
cd ~/src/fauxnos-client
python3 setup-client.py --setup
```

## 🧪 Development & Testing

### Testing on Development Machine

```bash
# Test the setup process without making changes
python3 setup-client.py --setup --dry-run

# Test with mock server responses
python3 setup-client.py --setup --test --verbose
```

### Testing Pi Setup Scripts

```bash
# Test system setup without changes
sudo bash pi-setup.sh --dry-run --verbose

# Quick test setup (skip updates and reboot)
sudo bash pi-setup.sh --skip-updates --skip-reboot
```

## Architecture

### System Design

This client system implements a **client-owned configuration model** where:

- **Client downloads complete system** from GitHub (config, sounds, templates)
- **Client fills in local info** (MAC address, display name from user input)
- **Client registers with server** for server-side multiroom management
- **Server returns connection info** (ports, URLs) to complete client setup
- **Client owns its source configuration** - server only handles grouping

### Module Structure

```
fauxnos-client/
├── fauxnos_client.py              # Main CLI application
├── setup-client.py                # Registration and initial setup
├── client_config.yaml.template    # Config template
├── requirements.txt               # Python dependencies
└── modules/
    ├── config_manager.py          # YAML config loading
    ├── logger.py                  # Logging setup
    ├── pulse_controller.py        # PulseAudio control
    ├── snapcast_controller.py     # Snapcast JSON-RPC
    ├── state_manager.py           # State persistence
    └── source_manager.py          # Source switching logic
```

### Volume Control Logic

The `volume_controller` setting determines how volume is controlled:

**`volume_controller: self`**
- Volume controlled via PulseAudio sink
- Sink volume varies from 0-100%
- Use for sources where PA is the final volume control

**`volume_controller: snapcast`**
- PA sink kept at 100%
- Volume controlled via Snapcast JSON-RPC
- Use for Spotify/multiroom sources where snapcast controls volume upstream

### State Persistence

Client state is saved to `~/.config/fauxnos/client_state.json`:
```json
{
  "current_source": "spotify",
  "source_volumes": {
    "spotify": 50,
    "analog": 30,
    "alexa": 40
  }
}
```

State is restored on restart, so the client remembers your last source and all source volumes.

## Configuration

Edit `~/.config/fauxnos/client_config.yaml` to configure your device:

### Device Section
```yaml
device:
  name: kitchen              # Unique device identifier
  mac: "00:00:00:00:00:00"   # MAC address
  display_name: Kitchen      # Display name
```

### Source Examples

**Internal Source (PA Sink Control):**
```yaml
- id: analog
  label: Analog Input
  type: internal
  sink: analogsink           # PulseAudio sink name
  starting_volume: 30
  volume_controller: self    # Use PA sink for volume
```

**Internal Source (Snapcast Control):**
```yaml
- id: spotify
  label: Spotify
  type: internal
  sink: snapsink
  starting_volume: 50
  volume_controller: snapcast  # PA sink at 100%, control via snapcast
  external_switch:
    enabled: true
    url: https://webhook.site/xxx
    payload: {source: fauxnos}
```

**External Source:**
```yaml
- id: alexa
  label: Alexa
  type: external
  control_url: https://webhook.site/xxx
  control_payload: {source: alexa}
```

## Usage

### Interactive Mode

```bash
python3 fauxnos_client.py
```

Available commands:
- `source <id>` - Switch to source (e.g., `source spotify`)
- `volume <0-100>` - Set volume for active source
- `status` - Show current source and volumes
- `list-sources` - List all configured sources
- `help` - Show help message
- `quit` - Exit

### Daemon Mode

```bash
python3 fauxnos_client.py --daemon
```

Runs in background without interactive CLI. Use SIGTERM or SIGINT to stop.

### Custom Config File

```bash
python3 fauxnos_client.py --config /path/to/config.yaml
```

## Files

- `client_config.yaml.template` - Configuration template
- `setup-client.py` - Registration and initial setup
- `fauxnos_client.py` - Main source management daemon
- `sounds/` - Audio feedback files (source switch, volume)
- `configs/` - Template files (PulseAudio, systemd services)
- Generated systemd services:
  - `snapclient-{client_id}.service`
  - `fauxnos-client-{client_id}.service`

## Test Modes

### `--dry-run`
Shows what would be done without making any changes. Safe to run anywhere.

### `--test`
Uses mock data and skips system-modifying commands (sudo, systemctl, etc). Safe for development.

### Production Mode
Makes actual system changes. Only run on target Raspberry Pi.

## Troubleshooting

### Config file not found
```
Error: Config file not found: ~/.config/fauxnos/client_config.yaml
```
**Solution:** Run `python3 setup-client.py --setup` to create config file

### Snapcast connection failed
```
ERROR - SnapcastController - Connection refused to snapcast at localhost:1705
```
**Solution:** Ensure snapcast server is running on fauxnos000. This is expected if testing locally without snapserver.

### Sink not found
```
ERROR - PulseAudioController - Failed to set snapsink volume
```
**Solution:** Check sink exists: `pactl list sinks short`

### Volume not changing
- Check `volume_controller` setting in config
- Verify snapcast client MAC matches device MAC
- Check logs: `tail -f ~/logs/fauxnos-client.log`

## Logs

Logs are written to `~/logs/fauxnos-client.log` by default (configurable in YAML).

Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL

## Testing Individual Modules

Each module can be tested standalone:

```bash
# Test config manager
python3 modules/config_manager.py ~/.config/fauxnos/client_config.yaml

# Test PulseAudio controller
python3 modules/pulse_controller.py list
python3 modules/pulse_controller.py volume --sink snapsink --volume 50

# Test snapcast controller
python3 modules/snapcast_controller.py test
python3 modules/snapcast_controller.py volume --volume 75

# Test state manager
python3 modules/state_manager.py save --source spotify --volumes '{"spotify": 50}'
python3 modules/state_manager.py load

# Test source manager
python3 modules/source_manager.py ~/.config/fauxnos/client_config.yaml
```