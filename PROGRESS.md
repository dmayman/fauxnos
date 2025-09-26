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

MASTER TODO - System Operational Status:

SERVER SIDE (COMPLETE):
✅ ConfigManager with add/remove/rename client functionality
✅ Atomic deployment system with template-based configuration
✅ User service architecture (no sudo needed for service management)
✅ Auto-generated snapserver.conf with all client sources
✅ FIFO management and go-librespot service coordination
✅ Port assignment and conflict resolution
✅ REST API server for client registration and config distribution
✅ Complete server infrastructure tested and operational

CLIENT SIDE (COMPLETE):
✅ One-command bootstrap installer with HiFiBerry DAC+ configuration
✅ Client registration system with MAC address and mDNS discovery
✅ Template-based configuration system with external files
✅ User systemd services deployment (snapclient, fauxnos-client)
✅ Proven PulseAudio configuration (snapsink, analogsink, systemsink)
✅ Complete client onboarding workflow from fresh Pi to operational

INTEGRATION & FEATURES (IN PROGRESS):
✅ Client-to-server registration flow (MAC address -> assigned client ID)
🔲 Group management via snapcast JSON-RPC API (multiroom functionality)
🔲 Volume synchronization (go-librespot volume -> snapclient volume)
🔲 Group volume control using existing proportional scaling algorithm
🔲 MQTT protocol implementation for device coordination
🔲 Source controller for internal/external source management
🔲 Auto-home-assignment (new clients join correct groups and sources)
🔲 Server-side group/source binding maintenance
🔲 Analog input switching and auto-detection (client-side)

NEXT PRIORITIES:
🔲 Source controller implementation (handle internal vs external sources)
🔲 Speaker grouping management via snapcast JSON-RPC API
🔲 Volume monitoring and synchronization (go-librespot -> snapclient)
🔲 Auto-home-assignment system for new clients
🔲 Group volume control with proportional scaling

APPS & INTERFACES (FUTURE):
🔲 Enhanced REST API for group control and source management
🔲 HomeKit/Homebridge plugin integration
🔲 Mobile app for client management and multiroom control
🔲 Web interface for system administration
🔲 MQTT protocol for real-time device coordination

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

CURRENT STATE: Complete end-to-end deployment system operational. Server and client infrastructure complete. Audio pipeline proven working. Ready for source controller and multiroom management features.