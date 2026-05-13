#!/bin/sh
#
# shairport-sync sessioncontrol hook — claim the airplay source.
#
# Wired to BOTH `run_this_before_entering_active_state` (iOS picks
# fauxnos as the AirPlay target) and `run_this_before_play_begins`
# (audio is about to start). Either firing publishes a mode-switch
# MQTT command; the source_manager no-ops on duplicates, so firing
# both is safe — the first one switches, the second is idempotent.
#
# We use the same MQTT topic the web-UI source picker uses
# (`set/clients/<device_id>/mode`) so every downstream listener
# (server's external-switch API caller, web UI mode tracker, snapcast
# stream switcher) sees the change the same way a button press would
# produce it.
#
# wait_for_completion=no in the shairport config means audio start
# is not delayed by this script. The publish is normally <100ms anyway.
#
# Mirrors the Spotify auto-switch in fauxnos_client.py:_on_spotify_playing.
#
# The literal placeholder __FAUXNOS_MQTT_HOST__ is substituted at install
# time by setup-client.py setup_shairport() with the MQTT broker host
# from client_config.yaml (`mqtt.broker_host`, typically `fauxnos000.local`).
# Hardcoding `localhost` here was wrong: mosquitto only runs on the server,
# so every non-server client hit "Connection refused" and the auto-switch
# silently no-op'd — exactly the bug that left fauxnos001 playing Spotify
# and AirPlay simultaneously after the 2026-05-12 install.
set -e
DEVICE_ID="$(/bin/hostname)"
exec /usr/bin/mosquitto_pub -h __FAUXNOS_MQTT_HOST__ \
    -t "set/clients/${DEVICE_ID}/mode" \
    -m airplay
