8/12/2025
- Spotify broke the api so librespot, spotifyd, go-librespot all aren't working
- go-librespot has a fix but am waiting on them to include it in a release so i dont have to build it from source https://github.com/devgianlu/go-librespot/releases/tag/v0.3.2
-   


9/20/2025
- Fully changed course because most other paths just don't work.
- Now using go-librespot and snapcast exclusively. For every client, there is a server-side go-librespot instance and snapcast fifo stream.
- On snapserver, there's one group per client, and each group defaults to the designated fifo stream. Example:
    - go-librespot instance "FauxnosGo_Stream1" is set to pipe to "spotifystream1" fifo.
    - snapserver source "Spotify1" uses "spotifystream1" fifo.
    - snapclient "fauxnos1" is added to group 0 that defaults to "Spotify1" source, but that can be changed. I think I'd only ever change the source of a group to either the default, or Analog In (need to explore this next).
    - Obviously need to rename all of these
- In Spotify, all go-librespot instances are visible. Snapclients just tune into them through the group they are in.
- To achieve multi-room, snapclients' can be moved to different groups. So you'd move fauxnos1 to fauxnos2's group, both would get Spotify2.
    - UX would be: Start playing to a room, add another room to that room. As long as we keep track of which group defaults to which client, the app can visualize this easily
- Volume control for each client is possible. Go-librespot announces the volume set by the Spotify app, but does not change any volume. /experiments/snapcast/vollisten.py is a proof of concept that shows we can listen to go-librespot's volume events and change snapclient volumes.
- We can use the existing algo in snapcast_controller.py to control group volumes by sending a volume event to each client in the group.

NEXT UP:
- Pulseaudio is still required for Analog In because it needs to be as fast as possible. We'll use the same config, but we only need two PA sources (snapcast and analog in).

9/22/2025
- Built complete ConfigManager system for server-side deployment automation
- Server now generates and manages ALL configurations from single source of truth:
  * go-librespot configs per client (~/.config/go-librespot/fauxnos001/config.yml)
  * systemd user services for all go-librespot instances
  * FIFO setup script and service for audio pipes
  * Complete snapserver.conf with auto-generated sources
  * User snapserver service (no more sudo needed!)
- Atomic deployment system - stages, validates, deploys, and starts all services
- Port management: fauxnos001 gets 49001/3601, fauxnos002 gets 49002/3602, etc.
- Client rename capability: `python config_manager.py rename-client fauxnos003 --name "Bedroom"`
- All services run as user services with proper dependencies
- Successfully tested: all go-librespot instances active and discoverable in Spotify


9/25/2025
- Completed full client onboarding pipeline from fresh Pi OS to operational Fauxnos client
- Built one-command bootstrap installer: `curl -sSL install.sh | bash`
- Implemented complete client registration system via MAC address and mDNS discovery
- Created template-based configuration management with external files for maintainability
- Migrated to user services architecture for easier permission management
- Deployed and tested HiFiBerry DAC+ configuration with proper PulseAudio setup
- Successfully tested complete audio pipeline: ALSA → HiFiBerry → PulseAudio → Snapcast
- Established architectural distinction between "speaker grouping" (snapcast groups) and "source selection" (audio content)
- Created REST API server with client registration, config distribution, and management endpoints
- Implemented systematic debugging approach for audio stack troubleshooting
- Built robust client setup script with dry-run and test modes for development

9/26/2025
- Implemented client-owned configuration architecture - clients download and manage their own YAML configs
- Created unified fauxnos-server.py interface with subcommands (run, add-client, deploy-server, cleanup, assign-groups, status)
- Organized all modules into /modules folder for clean structure
- Added home group and source tracking to server config (home_group, home_source fields)
- Built comprehensive group management system via snapcast JSON-RPC API
- Simplified server registration to exchange basic info only (no more rich config download)
- Created infrastructure cleanup tool to sync reality with server config as source of truth
- Started implementing event-driven group assignment (server startup + new client registration)

CURRENT STATE: Complete end-to-end deployment system operational. Client-owned config architecture implemented. Server infrastructure organized and unified. Ready to complete event-driven group management and test full system.

MASTER TODO - System Status:

SERVER INFRASTRUCTURE (COMPLETE):
✅ Unified fauxnos-server.py interface with subcommands
✅ ConfigManager with add/remove/rename client functionality
✅ Atomic deployment system with template-based configuration
✅ User service architecture (no sudo needed)
✅ Auto-generated snapserver.conf with all client sources
✅ REST API server for client registration
✅ Infrastructure cleanup tool (server config as source of truth)
✅ Home group and source tracking system
✅ Clean module organization (/modules folder)

CLIENT INFRASTRUCTURE (COMPLETE):
✅ One-command bootstrap installer with HiFiBerry DAC+ configuration
✅ Client-owned YAML configuration system
✅ Client registration with MAC address and mDNS discovery
✅ User systemd services deployment (snapclient, fauxnos-client)
✅ Proven PulseAudio configuration (snapsink, analogsink, systemsink)
✅ Complete onboarding workflow (fresh Pi to operational)

MULTIROOM & GROUP MANAGEMENT (IN PROGRESS):
✅ Snapcast JSON-RPC API integration
✅ Event-driven group assignment (server startup trigger)
✅ Event-driven group assignment (new client registration trigger)
✅ Automatic home group detection and persistence
✅ Group restoration on client reconnect
✅ Volume synchronization (go-librespot -> snapclient via WebSocket)
🔲 Group volume control with proportional scaling

SOURCE MANAGEMENT (IN PROGRESS):
✅ Modular source management system (fauxnos_client.py + 6 modules)
✅ Internal source control (PulseAudio-based routing)
✅ External source control (HTTP webhook triggers)
✅ Smart volume routing (PA sink vs snapcast control)
✅ State persistence across restarts
✅ Smooth source transitions with volume fading
✅ Interactive CLI and daemon modes
🔲 Analog input auto-detection (client-side)
🔲 MQTT protocol for device coordination
🔲 Integration with systemd services

APPS & INTERFACES (FUTURE):
🔲 Enhanced REST API for group/source control
🔲 HomeKit/Homebridge plugin integration
🔲 Mobile app for multiroom control
🔲 Web interface for administration


The generated snapclient service should match the one I created, it has some extra pulse audio stuff that's not needed.

10/6/2025
- Fixed group control system to work with Snapcast's dynamic group assignment
- Implemented automatic home group detection and persistence in server_config.json
- Fixed Snapcast API integration issues (correct stream_id parameter and response parsing)
- Updated cleanup command to properly locate and reset snapserver state file (~/.config/snapserver/server.json)
- Fixed source naming to use client IDs consistently (source_fauxnos001_spotify) instead of labels
- Added --hostID parameter to snapclient service template for proper client identification
- Built reset-groups command for testing group auto-detection without reinstalling clients
- Fixed client identification to use Snapcast ID field instead of hostname for proper matching
- Created test_snapcast_api.py debugging tool for direct Snapcast JSON-RPC testing
- Resolved "Invalid params" error by fixing stream reading from API response
- Group management now properly remembers and restores client assignments across reconnects

11/11/2025
- Implemented multiroom group management commands (show-groups, join-group, separate-client)
- Created test_multiroom.py script to prototype and test group control functionality
- Added join_client_to_group() and separate_client() methods to SnapcastGroupManager
- Fixed volume inconsistency issue between clients caused by PulseAudio stream volumes
- Added /etc/asound.conf creation to client setup to route ALSA apps through PulseAudio
- Discovered and fixed snapsink loopback volumes that were saved at 75% by PulseAudio's stream-restore module
- Both clients now have consistent audio routing: snapclient → PulseAudio → snapsink → loopback (100%) → hardware
- Implemented WebSocket-based Spotify volume control with real-time synchronization
- Created VolumeManager module for event-driven volume monitoring from go-librespot
- Volume changes in Spotify app now automatically update snapcast client volumes with <100ms latency
- Added websockets and requests dependencies to requirements.txt
- Integrated VolumeManager into server daemon lifecycle with proper start/stop handling
- Implemented smart client numbering: server device gets fauxnos000 (--is-server-device flag), regular clients start at 001
- Fixed ConfigManager to support dedicated server device ID assignment
- Volume synchronization architecture: go-librespot WebSocket /events → VolumeManager → Snapcast JSON-RPC Client.SetVolume
- Preserved proportional group volume scaling algorithm from archived code for future group volume control

11/12/2025
- Built complete modular client-side source management system (fauxnos_client.py)
- Created 6 specialized modules for clean separation of concerns:
  * config_manager.py - YAML configuration with type-safe dataclasses
  * logger.py - Centralized logging with rotation
  * pulse_controller.py - PulseAudio control via pactl subprocess
  * snapcast_controller.py - Snapcast JSON-RPC client for volume control
  * state_manager.py - Atomic state persistence with JSON
  * source_manager.py - Core source switching with smart volume routing
- Implemented intelligent volume controller routing:
  * volume_controller: self - PA sink controls volume directly (analog input)
  * volume_controller: snapcast - PA at 100%, snapcast controls volume (Spotify/multiroom)
- Added smooth volume fading between sources (5% steps, 50ms delay)
- Implemented state persistence across restarts (current source + all source volumes)
- Created internal vs external source architecture:
  * Internal sources: PulseAudio-based (Spotify, analog input)
  * External sources: HTTP webhook-controlled (Alexa, vinyl, aux)
- Built interactive CLI and daemon modes for fauxnos_client.py
- Successfully deployed and tested on fauxnos001 hardware
- Updated setup-client.py to install Python dependencies (pyyaml, requests)
- Integrated dependency installation into client setup workflow
- Consolidated README.md with complete source management documentation
- Updated requirements.txt with all necessary dependencies