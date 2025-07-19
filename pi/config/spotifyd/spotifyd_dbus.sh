# /etc/profile.d/spotifyd_dbus.sh
if [ -r "$XDG_RUNTIME_DIR/spotifyd_dbus.env" ]; then
  source "$XDG_RUNTIME_DIR/spotifyd_dbus.env"
  export DBUS_SESSION_BUS_ADDRESS
fi