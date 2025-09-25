# Fauxnos Client Testing Guide

## Testing on Raspberry Pi

The client onboarding system is designed to be tested on actual Pi hardware. Here's how to test the complete flow:

### Prerequisites on Pi

1. **Install Python dependencies**:
```bash
pip3 install requests --break-system-packages
```

2. **Ensure server is running**:
```bash
# On server machine
cd /path/to/fauxnos/pi/src/fauxnos-server
python3 api_server.py --test --verbose
```

### Testing the Client Registration Flow

#### 1. Test Mode (Safe)
```bash
cd ~/src/fauxnos-client
python3 setup-client.py --setup --test --verbose
```
- Uses mock data and localhost server
- Skips system modifications (hostname, services)
- Safe to run multiple times

#### 2. Dry Run Mode
```bash
python3 setup-client.py --setup --dry-run --verbose
```
- Shows exactly what would happen
- No actual changes made
- Good for debugging

#### 3. Full Registration (Production)
```bash
python3 setup-client.py --setup
```
- Discovers fauxnos-server.local
- Registers with real MAC address
- Downloads actual config
- Changes hostname and deploys services
- Reboots system

### Expected Flow

1. **Discovery**: Finds fauxnos-server.local via mDNS
2. **Registration**: POSTs MAC to `/api/clients/register`
3. **Server prompts**: For client display name
4. **Config download**: GETs full config from `/api/config/{client_id}`
5. **Local deployment**: Applies hostname, services, PulseAudio config
6. **Reboot**: System restarts with new identity

### Server API Testing

Test server endpoints directly:

```bash
# Check server status
curl http://fauxnos-server.local:8080/api/status

# List clients
curl http://fauxnos-server.local:8080/api/clients

# Get specific client config
curl http://fauxnos-server.local:8080/api/config/fauxnos001
```

### Troubleshooting

#### mDNS Discovery Issues
```bash
# Test mDNS resolution
avahi-resolve -n fauxnos-server.local

# Alternative: use direct IP
# Edit setup-client.py to set server_hostname = "192.168.1.100"
```

#### Service Deployment Issues
```bash
# Check service status
systemctl --user status snapclient-fauxnos001
systemctl --user status fauxnos-client-fauxnos001

# View service logs
journalctl --user -u snapclient-fauxnos001 -f
```

#### PulseAudio Issues
```bash
# Check sinks
pactl list sinks short

# Test audio
speaker-test -t wav -c 2
```

### Files Created During Setup

- `~/src/fauxnos-client/config.json` - Downloaded client config
- `/etc/systemd/system/snapclient-{client_id}.service` - Snapclient service
- `/etc/systemd/system/fauxnos-client-{client_id}.service` - Main client service
- `~/.config/pulse/default.pa` - PulseAudio configuration

### Reset for Re-testing

To reset a Pi for re-testing:

```bash
# Remove services
sudo systemctl stop snapclient-* fauxnos-client-*
sudo systemctl disable snapclient-* fauxnos-client-*
sudo rm /etc/systemd/system/snapclient-*.service
sudo rm /etc/systemd/system/fauxnos-client-*.service

# Reset hostname to temporary
sudo hostnamectl set-hostname fauxnos-temp-$(cat /sys/class/net/*/address | head -1 | sed 's/://g' | tail -c 5)

# Remove config
rm ~/src/fauxnos-client/config.json

# Reboot
sudo reboot
```