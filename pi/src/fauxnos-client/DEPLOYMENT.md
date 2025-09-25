# Fauxnos Client - Complete Deployment Guide

## 🎯 End-to-End Pi Deployment Strategy

This system provides a **zero-touch deployment** solution for Fauxnos clients, taking you from fresh Pi OS to fully operational multiroom audio client.

### Deployment Flow

```
Fresh Pi OS → One curl command → Fully operational Fauxnos client
```

## 📱 Headless Pi OS Setup

### 1. Flash Pi OS Image

1. **Download Raspberry Pi Imager**: https://www.raspberrypi.com/software/
2. **Flash Pi OS Lite** (headless recommended)
3. **Before ejecting**, configure the boot partition:

### 2. Enable SSH (Required)

Create `ssh` file in boot partition:
```bash
# On the flashed SD card boot partition
touch ssh
```

### 3. Configure WiFi (If using WiFi)

Create `wpa_supplicant.conf` in boot partition:
```bash
# wpa_supplicant.conf
country=US
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1

network={
    ssid="YourWiFiNetwork"
    psk="YourWiFiPassword"
}
```

### 4. Boot Pi and SSH In

1. **Insert SD card and boot Pi**
2. **Find Pi IP address** (check router or use network scanner)
3. **SSH into Pi**:
   ```bash
   ssh pi@192.168.1.xxx
   # Default password: raspberry (change this!)
   ```

## 🚀 Client Installation

### Option 1: One-Command Install (Recommended)

Run this single command on the Pi:
```bash
curl -sSL https://raw.githubusercontent.com/dmayman/fauxnos/main/pi/src/fauxnos-client/install.sh | bash
```

**What this does:**
1. ✅ Updates Pi OS and installs all dependencies
2. ✅ Configures audio system (PulseAudio, ALSA, snapclient)
3. ✅ Sets up network discovery (Avahi/mDNS)
4. ✅ Downloads complete fauxnos-client system
5. ✅ Discovers fauxnos-server automatically
6. ✅ Registers client and gets configuration
7. ✅ Deploys systemd services
8. ✅ Configures hostname and networking
9. ✅ Reboots into operational state

### Option 2: Step-by-Step Install

If you want more control:

```bash
# Step 1: System preparation
curl -sSL https://raw.githubusercontent.com/dmayman/fauxnos/main/pi/src/fauxnos-client/pi-setup.sh | sudo bash

# Step 2: After reboot, install client
curl -sSL https://raw.githubusercontent.com/dmayman/fauxnos/main/pi/src/fauxnos-client/install.sh | bash
```

## 🔧 Server Requirements

Before deploying clients, ensure your server is running:

```bash
# On server machine
cd /path/to/fauxnos/pi/src/fauxnos-server
python3 api_server.py --verbose
```

The server must be discoverable as `fauxnos-server.local` on the network.

## 📊 Installation Process

### What Happens During Installation

1. **Prerequisites Check**
   - Verifies Pi hardware
   - Checks internet connectivity
   - Validates user permissions

2. **System Dependencies**
   ```bash
   # Audio system
   snapclient pulseaudio pulseaudio-utils alsa-utils

   # Network discovery
   avahi-daemon avahi-utils

   # Development tools
   python3 python3-pip python3-requests git jq curl
   ```

3. **System Configuration**
   - Audio permissions (audio, pulse-access groups)
   - Temporary hostname (fauxnos-temp-XXXXX)
   - Service enablement (avahi, ssh)
   - Audio system setup

4. **Client Registration**
   - mDNS discovery of fauxnos-server.local
   - MAC address extraction as device ID
   - POST registration to `/api/clients/register`
   - Interactive server prompts for device name
   - Download full configuration from `/api/config/{client_id}`

5. **Service Deployment**
   ```bash
   # Services created:
   /etc/systemd/system/snapclient-{client_id}.service
   /etc/systemd/system/fauxnos-client-{client_id}.service

   # Config files:
   ~/src/fauxnos-client/config.json
   ~/.config/pulse/default.pa
   ```

6. **Final Configuration**
   - Hostname change (fauxnos-temp-XXXXX → fauxnos001)
   - Service enablement and startup
   - System reboot

## ✅ Validation & Troubleshooting

### Post-Installation Checks

After installation, verify everything is working:

```bash
# Check hostname
hostname  # Should be fauxnosXXX

# Check services
systemctl --user status snapclient-* fauxnos-client-*

# Check audio
pactl list sinks short
speaker-test -t wav -c 2

# Check network discovery
avahi-browse -t _http._tcp
```

### Common Issues & Solutions

#### 1. Server Discovery Fails
```bash
# Test mDNS resolution
avahi-resolve -n fauxnos-server.local

# Alternative: edit server hostname in setup-client.py
# Change: self.server_hostname = "192.168.1.100"
```

#### 2. Audio Issues
```bash
# Check audio groups
groups $USER  # Should include: audio pulse-access

# Restart PulseAudio
pulseaudio -k
pulseaudio --start

# Check ALSA devices
aplay -l
```

#### 3. Service Issues
```bash
# View service logs
journalctl --user -u fauxnos-client-* -f
journalctl --user -u snapclient-* -f

# Restart services
systemctl --user restart snapclient-*
systemctl --user restart fauxnos-client-*
```

## 🔄 Client Management

### Adding More Clients

Simply repeat the installation process on new Pi devices. Each will:
- Get assigned a unique client_id (fauxnos001, fauxnos002, etc.)
- Appear in Spotify as separate playback devices
- Be manageable through the server API

### Removing Clients

```bash
# On server
curl -X DELETE http://fauxnos-server.local:8080/api/clients/fauxnos001

# On client (to reset)
sudo systemctl stop snapclient-* fauxnos-client-*
sudo systemctl disable snapclient-* fauxnos-client-*
sudo rm /etc/systemd/system/snapclient-*.service
sudo rm /etc/systemd/system/fauxnos-client-*.service
rm ~/src/fauxnos-client/config.json
```

### Updating Clients

```bash
cd ~/src/fauxnos-client
curl -sSL https://raw.githubusercontent.com/dmayman/fauxnos/main/pi/src/fauxnos-client/install.sh | bash
```

## 🎵 Expected Results

After successful deployment:

1. **Spotify Integration**
   - Device appears in Spotify app
   - Named with your chosen display name
   - Independent volume and playback control

2. **Multiroom Capability**
   - Can be grouped with other Fauxnos clients
   - Synchronized playback across rooms
   - Individual and group volume control

3. **System Services**
   - Auto-start on boot
   - Automatic failure recovery
   - Logging for debugging

The entire process from fresh Pi OS to operational client takes about 10-15 minutes depending on internet speed and Pi model.