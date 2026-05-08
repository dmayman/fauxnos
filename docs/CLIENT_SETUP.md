# New Client Setup

Step-by-step for adding a new fauxnos client (Raspberry Pi). Written for me (David). Assumes 1Password is the source of truth for credentials and that the SSH key for accessing all fauxnos Pis lives in 1Password.

## Prerequisites (one-time)

These should already be set up. Verify before your first new-client install:

- **1Password "fauxnos SSH" item** exists, type *SSH Key*, with a generated Ed25519 keypair. The private key never leaves 1Password.
- **1Password SSH Agent** is enabled: 1Password → Settings → Developer → ✅ "Use the SSH agent".
- `~/.ssh/config` on the Mac contains:
  ```
  Host *
    IdentityAgent "~/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
  ```
- The 1Password public key is already in `~/.ssh/authorized_keys` on every existing fauxnos Pi (server + clients). Test: `ssh user@fauxnos000.local` should prompt Touch ID and connect.
- **Raspberry Pi Imager** installed: <https://www.raspberrypi.com/software/>

## Per-client materials

- Raspberry Pi (Zero 2 W has been the standard target)
- HiFiBerry DAC (DAC+ for clients, DAC+ADC for server)
- Quality SD card (8 GB+; A1/A2 rated saves you headaches)
- USB power supply
- The next free client number — check the server: `ssh user@fauxnos000.local "ls ~/.config/go-librespot/"`. If `fauxnos001` and `fauxnos002` exist, your next is `fauxnos003`.
- A display name for where it'll live (e.g. *Bedroom*, *Office*).

## Step 1 — Pi Imager configuration

1. Insert SD card. Open **Raspberry Pi Imager**.
2. **Choose Device**: the model of Pi you're flashing.
3. **Choose OS**: must be **Raspberry Pi OS Lite (64-bit) — Bookworm**. **Do not pick Desktop.**
   - Path in Imager: **Raspberry Pi OS (other) → Raspberry Pi OS Lite (64-bit)**.
   - Verify the description on the right says ***"Debian Bookworm"*** before clicking — Imager's default selection often jumps to the latest release (currently Trixie) or to Desktop, which we don't want.
   - **Why Lite, not Desktop**: a Pi 3B+ has 1GB of RAM. Desktop edition spends ~400MB on LXDE, lightdm, Plymouth, and various GUI services we never use, leaving fauxnos's audio stack (snapserver + go-librespot + snapclient + Flask + PulseAudio + mosquitto) hugging the OOM ceiling. We've crashed Pis this way already; don't repeat history.
   - **Why Bookworm, not Trixie**: the zero-touch `firstrun.sh` mechanism relies on `raspberrypi-firstboot.service`, which Trixie replaces with cloud-init and breaks.
   - **Why 64-bit, not 32-bit**: matches modern packages and matches our snapcast/go-librespot binary preferences. Pi 3B+/Zero 2 W/4/5 are all 64-bit capable. (32-bit also works — `install.sh` handles both archs — but 64 is the default we test against.)
4. **Choose Storage**: the SD card.
5. Click **Next** → **Edit Settings** when asked to apply OS customization.

### General tab

| Field | Value |
|---|---|
| **Set hostname** | ✅ `fauxnosNNN` (e.g. `fauxnos003`) — must match the chosen client number |
| **Set username and password** | ✅ Username **`user`** (lowercase, exactly — fauxnos scripts hardcode this). Password: generate a strong random one in 1Password (see Step 2). |
| **Configure wireless LAN** | ✅ SSID + password + country |
| **Set locale settings** | ✅ Time zone + keyboard layout |

### Services tab

- ✅ **Enable SSH**
- Select **"Allow public-key authentication only"**
- In the authorized-keys field, click **PASTE**:
  - Open the *fauxnos SSH* item in 1Password
  - Copy the **public key** (starts with `ssh-ed25519 AAAA…`)
  - Paste into the Imager field — should be a single line
  - **Sanity check**: it must start with `ssh-ed25519` (or `ssh-rsa`). If you see `-----BEGIN OPENSSH PRIVATE KEY-----`, you copied the wrong field — stop and recopy.

### Options tab

- ✅ Eject media when finished — handy.

Click **Save**, accept the prompt to apply customization, confirm overwrite. Wait for the write + verify to complete.

## Step 2 — Save the credentials in 1Password

Before pulling the SD card, create the per-Pi 1Password item so future-you can find it:

- **New Item → Server** (or copy a previous fauxnos client item)
- Title: `fauxnosNNN (Display Name)` — e.g. `fauxnos003 (Bedroom)`
- Username: `user`
- Password: the one you generated and pasted into Imager
- Add fields:
  - `hostname`: `fauxnosNNN.local`
  - `mac`: *(fill in after first boot — see next step set)*
  - `display_name`: e.g. `Bedroom`
  - `client_number`: `NNN`

The SSH key itself stays in the shared *fauxnos SSH* item, not duplicated per Pi. The password here is just a fallback for console / sudo / recovery — day-to-day SSH uses the key.

## Step 3 — TODO: zero-touch onboarding

*(To be filled in next session.)*

Outline of what comes next:

1. Pull `firstrun.sh` from the server: `curl -o firstrun.sh "http://fauxnos000.local:8080/api/install/firstrun.sh?display_name=Bedroom"`
2. Drop it onto the SD card's `/boot/firmware/` partition (the FAT32 boot volume that mounts on macOS as `/Volumes/bootfs`).
3. Eject SD card cleanly, insert into Pi, power on.
4. First boot runs `firstrun.sh` via `raspberrypi-firstboot.service`, which curls `client.sh` from the fauxnos server and self-registers as `fauxnosNNN`.
5. Verify in the web UI (`http://fauxnos000.local:8080`) that the new client appears.
6. Capture the MAC address and update the 1Password item.

## Troubleshooting

*(To be filled in as issues come up.)*
