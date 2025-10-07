# Fauxnos Client

Complete end-to-end deployment system for Fauxnos multiroom audio clients.

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

This client system implements a **client-owned configuration model** where:

- **Client downloads complete system** from GitHub (config, sounds, templates)
- **Client fills in local info** (MAC address, display name from user input)
- **Client registers with server** for server-side multiroom management
- **Server returns connection info** (ports, URLs) to complete client setup
- **Client owns its source configuration** - server only handles grouping

## Files

- `config.yaml` - Client configuration (filled in during setup)
- `setup-client.py` - Registration and initial setup
- `fauxnos-client.py` - Main client daemon (future)
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

## Next Steps

1. Implement server API endpoints (`/api/clients/register`, `/api/config/{client_id}`)
2. Complete `fauxnos-client.py` with volume monitoring and MQTT
3. Create base `pi-setup.sh` script for dependency installation
4. Test end-to-end flow from fresh Pi OS to working client