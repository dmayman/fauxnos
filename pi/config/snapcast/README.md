# Fauxnos Snapcast Server Configuration

This configuration sets up a multi-room audio server for Fauxnos using Snapcast.

## Installation

1. Copy `snapserver.conf` to `/etc/snapserver.conf`
2. Restart the Snapcast service:
   ```bash
   sudo systemctl restart snapserver
   ```

## Configuration

### Audio Sources
- **AirPlay**: Available as "Multiroom" with Shairport Sync
- **Spotify**: Uses `librespot_dm` with `--ignore-volume` flag, which sends maximum volume from Spotify regardless of the app's volume setting. This enables single-stage attenuation (volume control only through the Snapcast client), preventing potential confusing UX from multiple volume stages.

### Web Interface
- Accessible at `http://<server-ip>:1780`
- Serves the Snapweb interface
- RPC API available on port 1780

### Default Settings
- Buffer: 1000ms latency
- Initial volume: 100%
- Log level: info

## Usage

Connect Snapcast clients to the server using the hostname or IP address. The server will be discoverable via mDNS as "Multiroom".


# Snapclient
add snapclient.service to ~/.config/systemd/user/snapclient.service

run: 
systemctl enable ~/.config/systemd/user/snapclient.service --user
systemctl start snapclient --user
