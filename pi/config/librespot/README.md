# Fauxnos Librespot Configuration

This configuration sets up Librespot as a Spotify Connect endpoint for Fauxnos, piping audio to PulseAudio. Uses a custom version of Librespot with additional features.

## Installation

1. Install build dependencies:
   ```bash
   sudo apt update
   sudo apt install -y build-essential pkg-config libasound2-dev
   ```

2. Clone and copy librespot_dm:
   ```bash
   git clone https://github.com/dmayman/librespot_dm.git
   cd librespot_dm
   sudo cp target/release/librespot /usr/local/bin/librespot
   ```

3. Copy the service file and enable it:
   ```bash
   sudo cp librespot.service 
   systemctl --user daemon-reload
   systemctl --user enable --now librespot
   ```

## Configuration

### Service Settings
- **Name**: Fauxnos1 (visible in Spotify app)
- **Audio Quality**: 320kbps
- **Output**: Pipe to `/tmp/librespot_pipe`
- **Auto-restart**: On failure

### Audio Routing
- Audio is piped to PulseAudio's `libresink`
- Volume control is managed by the Fauxnos audio controller

## Verification

Check the service status with:
```bash
systemctl status librespot
```

Look for the device named "Fauxnos1" in your Spotify Connect devices list.

## Troubleshooting

View logs with:
```bash
journalctl --user -u librespot -f
```