# Fauxnos Architecture Documentation

## Overview

Fauxnos is a DIY multiroom audio system using go-librespot + snapcast architecture. Each client device gets its own dedicated go-librespot instance running on the server, with audio streamed to clients via snapcast.

## System Architecture

### Server Device
- Runs multiple go-librespot instances (one per client)
- Runs snapcast server with sources for each client
- Runs MQTT broker and fauxnos-server for coordination
- Manages all FIFO pipes for audio streaming

### Client Devices
- Runs snapclient to receive audio from server
- Runs fauxnos-client for local control and MQTT communication
- Handles analog input via PulseAudio (optional)
- Integrates volume monitoring (vollisten functionality)

## Naming Convention

### Client IDs
- Format: `fauxnosXXX` (e.g., `fauxnos001`, `fauxnos002`)
- Used as hostname and device identifier throughout system
- Network accessible as `fauxnos001.local`

### Display Names
- User-friendly names (e.g., "Kitchen", "Living Room")
- Used in Spotify device names and UI displays
- Stored alongside client ID in configuration

### Generated Component Names
- **go-librespot config**: `~/.config/go-librespot/fauxnos001/config.yml`
- **go-librespot service**: `go-librespot-fauxnos001.service`
- **FIFO pipe**: `/tmp/snapfifo/spotify_fauxnos001`
- **Snapcast source**: "Kitchen Spotify" (display name + "Spotify")

## Configuration Management

### Server Configuration (`/pi/src/server_config.json`)
```json
{
  "server": {
    "snapcast": {
      "host": "localhost",
      "port": 1705
    },
    "mqtt": {
      "broker_host": "localhost",
      "broker_port": 1883
    },
    "paths": {
      "fifo_base": "/tmp/snapfifo",
      "go_librespot_config_base": "~/.config/go-librespot"
    }
  },
  "clients": [
    {
      "id": "fauxnos001",
      "name": "Kitchen",
      "mac": "aa:bb:cc:dd:ee:01",
      "go_librespot": {
        "zeroconf_port": 49001,
        "server_port": 3601
      }
    },
    {
      "id": "fauxnos002",
      "name": "Living Room",
      "mac": "aa:bb:cc:dd:ee:02",
      "go_librespot": {
        "zeroconf_port": 49002,
        "server_port": 3602
      }
    }
  ]
}
```

### Client Configuration (`/pi/src/fauxnos-client/config.json`)
```json
{
    "client_id": "fauxnos001",
    "name": "kitchen",
    "display_name": "Kitchen",
    "mac": "aa:bb:cc:dd:ee:01",
    "server_config_url": "http://fauxnos-server.local:8080/api/config/fauxnos001",
    "go_librespot_monitor_url": "http://fauxnos-server.local:3601/player/volume",
    "sounds": {
        "switch": "~/src/sounds/source_switch.wav",
        "volume_up": "~/src/sounds/volume_up.wav",
        "volume_down": "~/src/sounds/volume_down.wav"
    },
    "sources": [
        {
            "id": "snapcast",
            "label": "Multiroom",
            "type": "internal",
            "sink": "snapsink",
            "starting_volume": 50,
            "volume_controller": "snapcast"
        },
        {
            "id": "analog",
            "label": "Analog In",
            "type": "internal",
            "sink": "analogsink",
            "starting_volume": 30,
            "volume_controller": "self"
        },
        {
            "id": "alexa",
            "label": "Alexa",
            "type": "external",
            "control_api": "https://webhook.site/example",
            "control_payload": {
                "source": "alexa"
            }
        }
    ],
    "log_file": "~/logs/audio_controller_{client_id}.log",
    "mqtt": {
        "broker_host": "fauxnos-server.local",
        "broker_port": 1883
    }
}
```

## Generated Configurations

### go-librespot Config (`~/.config/go-librespot/fauxnos001/config.yml`)
```yaml
device_name: "Kitchen"
initial_volume: 50
external_volume: true
device_type: speaker
audio_backend: pipe
audio_output_pipe: /tmp/snapfifo/spotify_fauxnos001
bitrate: 320
zeroconf_port: 49001
server:
  enabled: true
  address: 0.0.0.0
  port: 3601
```

### snapserver.conf (sources section)
```ini
source = pipe:///tmp/snapfifo/spotify_fauxnos001?name=Kitchen Spotify
source = pipe:///tmp/snapfifo/spotify_fauxnos002?name=Living Room Spotify
```

## Service Architecture

### Server Device Services

#### Single Instance:
- **snapserver.service** - Snapcast server with all client sources
- **fauxnos-server.service** - MQTT server and coordination
- **mosquitto.service** - MQTT broker

#### Per-Client (N instances):
- **go-librespot-fauxnos001.service** - Dedicated go-librespot instance
- **go-librespot-fauxnos002.service** - etc.

### Client Device Services

#### Single Instance:
- **snapclient.service** - Snapcast client for audio reception
- **fauxnos-client.service** - Local control, MQTT, and volume monitoring

## Audio Pipeline

### Server Side
1. **Spotify Connect** → go-librespot instance → FIFO pipe
2. **FIFO pipe** → snapcast source → snapcast server
3. **snapcast server** → network → snapclient

### Client Side
1. **snapclient** → PulseAudio snapsink → hardware output
2. **Analog input** → PulseAudio analogsink → hardware output (optional)
3. **System sounds** → PulseAudio systemsink → hardware output

### PulseAudio Configuration (Client)
- **snapsink** - Receives snapcast audio
- **analogsink** - Handles analog input loopback
- **systemsink** - For notification sounds (volume changes, source switches)

## Volume Control

### Spotify Volume Monitoring
- go-librespot exposes volume via HTTP API (`/player/volume`)
- fauxnos-client polls this endpoint and mirrors volume to snapclient
- Preserves Spotify app volume control while managing local hardware

### Group Volume Control
Uses existing `set_group_volume_direct()` algorithm from snapcast_controller.py:
- Calculates proportional scaling to preserve relative volume differences
- Applied to snapcast groups for multiroom volume control

## Client Onboarding Workflow

### Step 1: Base Pi Setup
```bash
curl -sSL https://raw.githubusercontent.com/user/fauxnos/main/scripts/pi-setup.sh | bash
```
- System updates and dependency installation
- Audio hardware configuration
- User account setup with proper permissions
- Temporary hostname assignment

### Step 2: Device Registration
```bash
sudo fauxnos-client --setup
```
1. **mDNS discovery** - Find fauxnos-server.local
2. **Registration** - POST MAC address to `/api/clients/register`
3. **Server response** - Assigned client_id and configuration
4. **Client configuration** - Apply hostname, services, restart

### Step 3: Server Auto-Configuration
When client registers:
1. Generate new client ID (fauxnos001, fauxnos002, etc.)
2. Prompt for friendly name ("Kitchen", "Living Room")
3. Add to server_config.json
4. Deploy server infrastructure (go-librespot, snapserver sources)
5. Return client-specific configuration

## ConfigManager

### Deployment Strategy
- **Atomic deployment** - All configs generated and validated before applying
- **Service orchestration** - Proper start/stop order for dependent services
- **Rollback capability** - Restore previous working configuration on failure

### Command Interface
```bash
# Server deployment
fauxnos-config deploy-server

# Add new client
fauxnos-config add-client --name "Kitchen" --mac "aa:bb:cc:dd:ee:01"

# Client-side setup
fauxnos-client --setup
```

## Multiroom Functionality

### Individual Playback
- Each client has dedicated go-librespot instance
- Appears as separate device in Spotify
- Independent volume and playback control

### Group Playback
- Move snapclients to same snapcast group
- All clients in group receive same audio stream
- Group volume control maintains relative levels
- Can dynamically add/remove clients from groups

## Network Architecture

### Device Discovery
- **mDNS/Bonjour** for automatic discovery
- **Predictable hostnames** - fauxnos001.local, fauxnos002.local
- **MQTT topics** - status/clients/fauxnos001/{hello,mode,volume,activity}

### API Endpoints
- **GET /api/config/{client_id}** - Client configuration retrieval
- **POST /api/clients/register** - New client registration
- **GET /api/clients** - List all registered clients
- **PUT /api/clients/{client_id}** - Update client configuration

## Future Integration

### HomeKit/Homebridge
- fauxnos-client provides mDNS discovery for homebridge plugin
- Volume and transport controls via MQTT
- Device grouping and multiroom coordination

### Mobile App
- REST API for client management
- Real-time status via MQTT
- Group volume control using existing algorithms
- Easy client addition/removal/renaming