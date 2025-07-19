#!/usr/bin/env python3
"""
Librespot D-Bus Controller
--------------------------
Controls librespot via D-Bus MPRIS interface for play/pause, volume, etc.

Dependencies:
- pydbus: sudo apt install python3-pydbus
- gi (PyGObject): sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0

Usage:
python3 librespot-controller.py play_pause
python3 librespot-controller.py set_volume 50
python3 librespot-controller.py get_volume
python3 librespot-controller.py get_playback_status
"""

import sys

# Check for required dependencies
try:
    from pydbus import SessionBus
    import gi
    gi.require_version('GLib', '2.0')
    from gi.repository import GLib
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install with:")
    print("  sudo apt install python3-pydbus")
    print("  sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0")
    sys.exit(1)

PLAYER_SERVICE = "org.mpris.MediaPlayer2.librespot"  # Adjust if your librespot has a different D-Bus name

def get_librespot_player():
    """Attempts to get the D-Bus player object for librespot."""
    try:
        bus = SessionBus()
        return bus.get(PLAYER_SERVICE, "/org/mpris/MediaPlayer2")
    except GLib.Error as e:
        print(f"Error connecting to D-Bus player: {e}", file=sys.stderr)
        print("Make sure librespot is running and D-Bus is enabled.", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return None

def control_librespot(command, value=None):
    """Sends commands to librespot via D-Bus."""
    player = get_librespot_player()
    if not player:
        print("Librespot D-Bus player not found.", file=sys.stderr)
        return False

    try:
        if command == "play_pause":
            player.PlayPause()
            print("Librespot: Play/Pause toggled.")
        elif command == "set_volume":
            if value is not None:
                mpris_volume = float(value) / 100.0
                player.Volume = max(0.0, min(1.0, mpris_volume))
                print(f"Librespot: Volume set to {value}%.")
        elif command == "get_volume":
            current_volume = player.Volume * 100.0
            return int(current_volume)
        elif command == "get_playback_status":
            return player.PlaybackStatus
        else:
            print(f"Unknown librespot command: {command}", file=sys.stderr)
            return False
        return True
    except GLib.Error as e:
        print(f"Error controlling librespot via D-Bus: {e}", file=sys.stderr)
        return False

def list_available_players():
    """List all available MPRIS players on D-Bus."""
    try:
        bus = SessionBus()
        # Get all D-Bus services
        dbus_obj = bus.get("org.freedesktop.DBus")
        services = dbus_obj.ListNames()
        
        # Filter for MPRIS players
        mpris_players = [s for s in services if s.startswith("org.mpris.MediaPlayer2.")]
        
        if mpris_players:
            print("Available MPRIS players:")
            for player in mpris_players:
                print(f"  - {player}")
        else:
            print("No MPRIS players found.")
        
        return mpris_players
    except Exception as e:
        print(f"Error listing players: {e}")
        return []

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 librespot-controller.py [command] [args]")
        print("\nCommands:")
        print("  play_pause                - Toggle play/pause")
        print("  set_volume <0-100>        - Set volume percentage")
        print("  get_volume               - Get current volume")
        print("  get_playback_status      - Get playback status")
        print("  list_players             - List available MPRIS players")
        sys.exit(1)

    command = sys.argv[1]

    if command == "list_players":
        list_available_players()
    elif command == "play_pause":
        control_librespot("play_pause")
    elif command == "set_volume":
        if len(sys.argv) < 3:
            print("Usage: python3 librespot-controller.py set_volume <percentage>")
            sys.exit(1)
        try:
            volume = int(sys.argv[2])
            if volume < 0 or volume > 100:
                print("Volume must be between 0 and 100.")
                sys.exit(1)
            control_librespot("set_volume", volume)
        except ValueError:
            print("Volume must be an integer.")
            sys.exit(1)
    elif command == "get_volume":
        current_vol = control_librespot("get_volume")
        if current_vol is not None:
            print(f"Current volume: {current_vol}%")
    elif command == "get_playback_status":
        status = control_librespot("get_playback_status")
        if status is not None:
            print(f"Playback status: {status}")
    else:
        print(f"Unknown command: {command}")
        print("Run with no arguments to see available commands.")
        sys.exit(1)