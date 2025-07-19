#!/bin/bash

echo "$DBUS_SESSION_BUS_ADDRESS" > /tmp/spotifyd_bus
echo "To use spotifyd's session bus, run 'export DBUS_SESSION_BUS_ADDRESS=$(cat /tmp/spotifyd_bus)'"
spotifyd --no-daemon --use-mpris
