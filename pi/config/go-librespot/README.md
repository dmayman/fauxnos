## Installation

1. Place config.yml in ~/.config/go-librespot/config.yml
2. Place setup-fifo.sh in ~/.config/go-librespot/setup-fifo.sh and make executable:
   ```bash
   chmod +x ~/.config/go-librespot/setup-fifo.sh
   ```
3. Install user service:
   ```bash
   cp go-librespot.service ~/.config/systemd/user/
   systemctl --user daemon-reload
   systemctl --user enable go-librespot.service
   systemctl --user start go-librespot.service
   ```
