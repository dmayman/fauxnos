# Fauxnos Pi Setup Guide

A comprehensive guide for setting up a DIY multiroom audio system using Raspberry Pi, inspired by Sonos.

## Hardware Requirements

- Raspberry Pi Zero 2 W
- HiFiBerry DAC+ (PCM5102A-based DAC)
- Good quality SD card (16GB+ recommended)
- Power supply
- Audio cables/speakers

## System Overview

The Fauxnos system includes:
- **Librespot**: Modified for external volume control (Spotify Connect)
- **Snapcast**: For multiroom audio synchronization
- **ALSA**: Advanced Linux Sound Architecture for audio routing
- **Software volume controls**: Independent control for each audio source
- **MQTT**: For remote control integration

## Phase 1: Base System Setup

### 1. Prepare Raspberry Pi OS Lite

1. Flash Raspberry Pi OS Lite using Raspberry Pi Imager with pre-configured WiFi and SSH
2. Create user account 'user' for security (avoiding root access)
3. Boot up and perform initial system updates:
   ```bash
   sudo apt update && sudo apt upgrade -y
   ```
4. Expand filesystem to use full SD card capacity:
   ```bash
   sudo raspi-config --expand-rootfs
   sudo reboot
   ```
5. Enable SFTP access for file management:
   ```bash
   sudo apt install openssh-server
   sudo systemctl enable ssh
   sudo systemctl start ssh
   ```
   FileZilla connection settings:
   - Protocol: SFTP
   - Host: [Pi IP address]
   - Username: user
   - Port: 22

### 2. Install Essential System Packages

```bash
sudo apt install -y build-essential git libasound2 libasound2-dev libssl-dev libpulse-dev cmake libclang-dev
```

### 3. Configure Audio Hardware

1. Check audio hardware detection:
   ```bash
   aplay -l
   ```

2. Test audio output (stereo required for HiFiBerry DAC):
   ```bash
   speaker-test -t wav -c 2
   ```

### 4. Install Rust Development Environment

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source $HOME/.cargo/env
rustup update stable
```

## Phase 2: Configure ALSA Audio Pipeline

### 1. Create ALSA Configuration

1. Create `/etc/asound.conf` (the complete file is available in the project documentation):
   - 4 softvol devices (librespot, snapcast, analog, system)
   - dmix for audio mixing
   - Phantom volume control
   - System-wide EQ

2. Verify configuration:
   ```bash
   aplay -L
   ```

### 2. Test Audio Pipeline

Test the audio configuration before proceeding with application installations.

## Phase 3: Librespot Installation

### 1. Clone and Build Modified Librespot

1. Clone the patched repository:
   ```bash
   git clone https://github.com/dmayman/librespot_dm.git
   cd librespot_dm
   git checkout dev  # if needed
   ```

2. Build the project:
   ```bash
   rm Cargo.lock
   cargo update
   cargo build --release --features with-pipe
   ```

### 2. Test Librespot

1. Run librespot:
   ```bash
   ./target/release/librespot --name "PiSpot"
   ```
   Note: `--backend rodio` is now the default; `--backend alsa` no longer works.

2. Test with Spotify:
   - Open Spotify app
   - Go to Devices
   - Select "PiSpot"
   - Verify audio plays and Spotify volume slider doesn't affect hardware volume

## Phase 4: Audio Stack Components (TODO)

### 1. Snapcast Client
- Installation and configuration pending
- Will provide multiroom audio synchronization

### 2. Analog Input
- Configuration for physical audio input
- Integration with ALSA pipeline

### 3. System Sounds
- Configuration for beeps and notifications
- Independent volume control

### 4. MQTT Control Service
install with sudo apt install python3-paho-mqtt
- Remote control interface
- Volume management
- Source switching

## Current Issues/Notes

1. ALSA configuration with dmix and EQ needs refinement
2. Trade-off: Removed dmix to enable system-wide EQ (only one audio source at a time)
3. Software volume control used due to HiFiBerry DAC Lite hardware limitations

## Testing Tools

### Audio Test Script
```python
# Python script for continuous audio testing
# (To be added based on project requirements)
```

### Volume Control Commands
```bash
# Control individual source volumes
amixer set softvol_librespot 80%
amixer set softvol_snapcast 80%
amixer set softvol_analog 80%
amixer set softvol_system 80%
```

## Troubleshooting

1. **Audio not playing**: Check `aplay -l` and verify HiFiBerry DAC is detected
2. **Permission issues**: Ensure proper ownership of configuration files
3. **No audio mixing**: Current configuration doesn't support simultaneous playback
4. **EQ not working**: Verify audio routing through equalizer in asound.conf

---



Install snapclient

wget https://github.com/badaix/snapcast/releases/download/v0.31.0/snapclient_0.31.0-1_armhf_bookworm.deb

# Install the package
sudo dpkg -i snapclient_0.31.0-1_armhf_bookworm.deb

# If there are still dependency issues, fix them with
sudo apt-get -f install



Install snapserver

wget https://github.com/badaix/snapcast/releases/download/v0.31.0/snapserver_0.31.0-1_armhf_bookworm.deb

# Install the package
sudo dpkg -i snapserver_0.31.0-1_armhf_bookworm.deb

# If there are still dependency issues, fix them with
sudo apt-get -f install


--------

Install spotifyd and sp

### move sp to /usr/local/bin
### Make sure you’ve also got dbus-send, grep, cut, tr, column installed
sudo apt install dbus-user-session bsdmainutils

### install dbus
sudo apt install dbus-x11

### install playerctl
sudo apt update
sudo apt install playerctl

## Install dbus next python lib
pip3 install dbus-next --break-system-packages