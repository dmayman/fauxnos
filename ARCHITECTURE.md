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

### Server Configuration (`/pi/src/fauxnos-server/server_config.json`)
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
      },
      "home_group": "group_fauxnos001",
      "home_source": "source_kitchen_spotify"
    }
  ],
  "speaker_groups": [
    {
      "id": "group_fauxnos001",
      "name": "Kitchen Group",
      "default_source": "source_kitchen_spotify",
      "clients": ["fauxnos001"]
    }
  ]
}
```

### Client Configuration (`/pi/src/fauxnos-client/config.json`)
Rich, client-specific configuration downloaded from server during registration:

```json
{
    "client_id": "fauxnos001",
    "name": "1",
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
            "control_payload": {"source": "alexa"}
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

### Server Device Services (User Services)

#### Single Instance:
- **snapserver.service** - Snapcast server with all client sources
- **fauxnos-server.service** - API server and coordination
- **setup-fifo.service** - FIFO pipe management for audio streams
- **mosquitto.service** - MQTT broker (system service)

#### Per-Client (N instances):
- **go-librespot-fauxnos001.service** - Dedicated go-librespot instance
- **go-librespot-fauxnos002.service** - etc.

### Client Device Services (User Services)

#### Template-Based Deployment:
- **snapclient-{CLIENT_ID}.service** - Snapcast client for audio reception
- **fauxnos-client-{CLIENT_ID}.service** - Local control, MQTT, and volume monitoring

#### Service Templates:
Stored in `/pi/src/fauxnos-client/configs/systemd/` and deployed to `~/.config/systemd/user/`

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
Template-based config stored in `/pi/src/fauxnos-client/configs/pulseaudio/default.pa`:
- **HiFiBerry DAC+** - ALSA card with `tsched=0` for low latency
- **snapsink** - Null sink for snapcast audio with loopback to hardware
- **analogsink** - Null sink for analog input with loopback
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

### Step 1: One-Command Bootstrap
```bash
curl -sSL https://raw.githubusercontent.com/dmayman/fauxnos/main/pi/src/fauxnos-client/install.sh | bash
```
Bootstrap script handles:
- System updates and audio dependencies
- HiFiBerry DAC+ overlay configuration (`dtoverlay=hifiberry-dac`)
- Download of all client configuration files and templates
- User account setup with proper permissions

### Step 2: Client Registration and Setup
```bash
python3 ~/src/fauxnos-client/setup-client.py --setup
```
1. **mDNS discovery** - Find fauxnos-server.local using avahi-resolve
2. **MAC address detection** - Primary network interface identification
3. **Server registration** - POST MAC address to `/api/clients/register`
4. **Config download** - Receive client-specific configuration from server
5. **Hostname application** - Change from temporary to permanent hostname
6. **PulseAudio setup** - Deploy proven audio configuration
7. **Service deployment** - Install and start user systemd services
8. **System reboot** - Apply all changes

### Step 3: Server Auto-Configuration
When client registers via API:
1. Check for existing registration by MAC address
2. Generate sequential client ID (fauxnos001, fauxnos002, etc.)
3. Interactive prompt for display name ("Kitchen", "Living Room")
4. Add client to server_config.json
5. Deploy server infrastructure (go-librespot instance, snapserver source)
6. Return registration response with ports and config URL

## ConfigManager (Server-Side)

### Deployment Strategy
- **Atomic deployment** - All configs generated and validated before applying
- **Template-based generation** - External config files for maintainability
- **User service architecture** - No sudo required for service management
- **Service orchestration** - Proper dependency management

### Implementation
- **ConfigManager class** - Handles server_config.json manipulation
- **DeploymentManager class** - Generates and deploys all configurations
- **Template system** - go-librespot configs, systemd services, snapserver.conf
- **Port management** - Sequential port assignment (49001/3601, 49002/3602, etc.)

### Command Interface
```bash
# Add client via Python API
python3 config_manager.py add-client --name "Kitchen" --mac "aa:bb:cc:dd:ee:01"

# Rename existing client
python3 config_manager.py rename-client fauxnos003 --name "Bedroom"

# Deploy server infrastructure
python3 deploy.py deploy-server

# API server for client registration
python3 api_server.py --verbose
```

## Multiroom Functionality

### Speaker Grouping vs Source Selection
**Important architectural distinction:**
- **Speaker Grouping** - Which physical speakers play together (snapcast groups)
- **Source Selection** - What audio content to play (go-librespot instances, analog, etc.)

### Individual Playback
- Each client has dedicated go-librespot instance on server
- Appears as separate device in Spotify ("Kitchen", "Living Room")
- Client defaults to its own group with its own source
- Independent volume and playback control

### Group Playback (Speaker Grouping)
- Move snapclients to same snapcast group via JSON-RPC API
- All clients in group receive same audio stream
- Group volume control maintains relative levels using existing proportional algorithm
- Clients can be dynamically added/removed from groups

### Source Management
- Each client has "home group" and "home source" for auto-assignment
- New clients automatically join their designated group and source
- Server maintains group/source binding consistency
- Source switching affects entire group (all speakers in group change source together)

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
- **DELETE /api/clients/{client_id}** - Remove client configuration
- **GET /api/status** - Server status and client count

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