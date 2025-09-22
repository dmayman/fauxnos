# Fauxnos Pi Setup Guide

A comprehensive guide for setting up a DIY multiroom audio system using Raspberry Pi, inspired by Sonos.

## Hardware Requirements

- Raspberry Pi Zero 2 W
- HiFiBerry DAC+ (PCM5102A-based DAC)
- Good quality SD card (16GB+ recommended)
- Power supply
- Audio cables/speakers

## System Overview

The Fauxnos system on each client includes:
- **Spotifyd**: For Spotify Connect with DBUS integration for bidirectional event handling
- **Pulse Audio**: For audio routing
- **Shairport-sync (COMING SOON!)**: For AirPlay support
- **Software volume controls**: Independent control for each audio source

The Fauxnos system on the server includes:
- **Snapcast**: For multiroom audio synchronization
  - **Librespot_dm**: Modified librespot for external volume control
  - **Shairport-sync**: Airplay receiver
- **MQTT**: For remote control integration
- **Homebridge plugin**: For HomeKit integration

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


## Phase 2: Configure Pulse Audio Pipeline

### 1. Create Pulse Audio Configuration

1. Follow instructions in `config/pulseaudio` for complete pulseaudio configuration

2. Verify configuration:
   ```bash
   pulseaudio --check
   ```

### 2. Test Audio Pipeline

pactl list short | grep -i sink

## Phase 3: Librespot Installation

### 1. Clone and Build Modified Librespot

1. Clone the patched repository:
   ```bash
   git clone https://github.com/dmayman/librespot_dm.git
   cd librespot_dm
   git checkout dev  # if needed
   ```

2. Install librespot
   ```bash
   sudo cp target/release/librespot /usr/local/bin/librespot
   sudo chmod +x /usr/local/bin/librespot

   ```

### 2. Test Librespot

1. Run librespot:
   ```bash
   librespot --name "PiTest"
   ```

2. Test with Spotify:
   - Open Spotify app
   - Go to Devices
   - Select "PiSpot"
   - Verify audio plays and Spotify volume slider doesn't affect hardware volume

## Phase 4: Audio Stack Components


---

## [optional]Netatalk (for file sharing)
sudo apt-get install netatalk

edit this config file
sudo nano /etc/netatalk/afp.conf
`[Homes]
basedir regex = /Home`

Then on the mac
afp://fauxnos1.local

------

# Install pulseaudio
sudo apt-get update
sudo apt-get install pulseaudio

------

# Install go-librespot



-------

# Install snapclient

wget https://github.com/badaix/snapcast/releases/download/v0.31.0/snapclient_0.31.0-1_armhf_bookworm.deb

### Install the package
sudo dpkg -i snapclient_0.31.0-1_armhf_bookworm.deb

### If there are still dependency issues, fix them with
sudo apt-get -f install



# Install snapserver (server only)

wget https://github.com/badaix/snapcast/releases/download/v0.31.0/snapserver_0.31.0-1_armhf_bookworm.deb

# Install the package
sudo dpkg -i snapserver_0.31.0-1_armhf_bookworm.deb

# If there are still dependency issues, fix them with
sudo apt-get -f install


--------

# Install spotifyd
Download spotifyd-linux-armv7-full.tar.gz from here https://github.com/Spotifyd/spotifyd/releases
Unzip it and move the spotifyd binary to /usr/local/bin
sudo chmod +x /usr/local/bin/spotifyd
TODO: create a spotifyd.service file to run as a daemon

### Make sure you’ve also got dbus-send, grep, cut, tr, column installed
sudo apt install dbus-user-session bsdmainutils

### install dbus
sudo apt install dbus-x11

### install playerctl
sudo apt update
sudo apt install playerctl

## Install dbus next python lib
pip3 install dbus-next --break-system-packages

## Install gdbus
sudo apt install libglib2.0-bin

### install paho mqtt
pip3 install paho-mqtt --break-system-packages

### install pulsectl
pip install pulsectl --break-system-packages

### enable user linger so user services start on their own
sudo loginctl enable-linger $USER

---
# Server installation

### install mosquitto

# Install mosquitto MQTT broker
sudo apt update
sudo apt install mosquitto mosquitto-clients

# Start the mosquitto service
sudo systemctl start mosquitto

# Enable it to start on boot
sudo systemctl enable mosquitto

# Check if it's running
sudo systemctl status mosquitto


# Fauxnos Services 
systemctl enable ~/services/fauxnosClient.service --user --now
systemctl enable ~/services/fauxnosServer.service --user --now


### FYI for Homebridge had to install nss-mdns to get mDNS working

sudo apt-get install libnss-mdns

NEXT STEPS:
- Homebridge plugin has proper mDNS support now
- It's loading up properly with logs, but is not discovering any devices. No MQTT logs on fauxnos-server, so it's probably not connecting properly. 
