# MQTT Client Protocol

| **Direction**       | **Topic**                            | **Payload Example**                                                                                     | **Purpose**                                                                        |
| ------------------- | ------------------------------------ | ------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| Client → Controller | `status/clients/<deviceId>/hello`    | `{ "id": "livingroom-pi", "name": "Living Room", "capabilities": ["snapcast", "librespot", "analog"] }` | Device announces itself at startup                                                 |
| Client → Controller | `status/clients/<deviceId>/mode`     | `"snapcast"`, `"librespot"`, `"analog"`, `"idle"`                                                       | Reports current active mode                                                        |
| Client → Controller | `status/clients/<deviceId>/volume`   | `42` (0–100)                                                                                            | Reports current volume level                                                       |
| Client → Controller | `status/clients/<deviceId>/activity` | `"playing"` / `"silent"`                                                                                | Reports whether audio is playing                                                   |
| **Prefix**          | **Topic**                            | **Payload Example**                                                                                     | **Purpose**                                                                        |
| `set/`              | `set/clients/<deviceId>/volume`      | `42` (integer 0–100)                                                                                    | Set device volume to a specific percentage                                         |
| `set/`              | `set/clients/<deviceId>/mode`        | `"snapcast"`, `"librespot"`, `"analog"`                                                                 | Switch the device to a new playback mode                                           |
| `get/`              | `get/clients/<deviceId>/volume`      | (empty or `{}`)                                                                                         | Request device to publish its current volume to `status/clients/<deviceId>/volume` |
| `get/`              | `get/clients/<deviceId>/status`      | (empty or `{}`)                                                                                         | Request device to publish its current mode                                         |
| `get/`              | `get/clients/<deviceId>/activity`    | `"playing"` / `"silent"`                                                                                | Request device to report whether audio is playing                                  |

Install DBus

# Services

## Client Components
- fauxnos-client (user)
    - main client software
- spotifyd (user)
    - main stream for individual spotify 
- snapclient (user)
    - streams multiroom audio from snapserver
- pulseaudio (user)
    - audio engine
- dbus (system)
    - playback and volume control for spotifyd

## Server Components
- fauxnos-server (user)
    - main server software
- mosquitto (system)
    - mqtt broker
- snapserver (system)
    - multiroom audio server
- go-librespot (system)
    - streams spotify to snapserver
