create a system service for spotifyd
systemctl --user enable ~/spotifyd.service

replace spotify.service symlink with actual file in ~/.config/systemd/user/

save spotifyd.conf to ~/.config/spotifyd/spotifyd.conf
put spotify.conf.sys to /usr/share/dbus-1/system.d/spotifyd.conf (rename it)

start it
systemctl --user daemon-reload
systemctl --user start spotifyd