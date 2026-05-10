# New Client Setup

Adding a new fauxnos client is now driven from the server's web UI ("Add Device" tab). Your job is to flash a Pi and paste two SSH keys; the server SSHes in and runs everything else with a live progress timeline.

## What you need

- A Raspberry Pi (Zero 2 W is the standard target) + HiFiBerry DAC (DAC+ for clients)
- A quality SD card (8 GB+, A1/A2 rated)
- **Raspberry Pi Imager**: <https://www.raspberrypi.com/software/>
- Two SSH public keys ready to paste:
  1. **Your personal key**, the one you already use to SSH into other fauxnos Pis (typically the *fauxnos SSH* item in 1Password, in `ssh-ed25519 AAAA…` form).
  2. **The fauxnos server's install key**, copied from the "Add Device" tab. This is the key the server uses to SSH into the new Pi and run install.sh. It is generated automatically by `install.sh` on the server (`~/.ssh/id_ed25519_fauxnos.pub`) and exposed as a copy button in the wizard.

## Step 1 — Pi Imager

1. Open Pi Imager → **Choose OS** → **Raspberry Pi OS Lite (64-bit, Bookworm)**.
   - Not Trixie. Not Desktop. Description on the right must say *Debian Bookworm*.
2. **Choose Storage** → the SD card.
3. Click **Edit Settings**.

   | Tab | Field | Value |
   |---|---|---|
   | General | Hostname | `fauxnos-client` *(literal — do not pre-pick a number; the server assigns it)* |
   | General | Username/password | `user` (lowercase) + a per-Pi password (save in 1Password) |
   | General | WiFi | SSID + password + country |
   | General | Locale | Time zone + keyboard |
   | Services | SSH | ✅ Enable, **Allow public-key authentication only** |
   | Services | Authorized keys | Paste **both** keys, one per line: your personal key, then the server install key copied from the wizard. |

4. Save → write → eject → insert into Pi → power on.

## Step 2 — Open the wizard

Open the server UI: <http://fauxnos000.local:8080> → **Add Device** tab. Enter a display name (e.g. *Kitchen*) and click **Install on fauxnos-client.local**. Watch the timeline: each step transitions from pending to active to done. The active step shows a pulse and the latest stdout line. If a step stalls (no output for 30 seconds, common on apt installs over WiFi) it flips amber but continues. After the Pi reboots, the final `verify` step polls until the new client comes back online and reports the assigned `fauxnosNNN` ID.

## Troubleshooting

- **Wizard says "Could not resolve fauxnos-client.local"** — the Pi hasn't joined WiFi yet, mDNS hasn't propagated, or the hostname in Imager wasn't set to `fauxnos-client`. Confirm with `ping fauxnos-client.local` from the server and try again.
- **SSH connect fails** — the server install key wasn't pasted, or the wrong line was. The wizard has a copy button; re-flash if needed.
- **Step stays amber for minutes** — check `~/src/fauxnos-server/web-ui` server logs (`journalctl --user -u fauxnos-server`) and click "Show install log" in the timeline.
- **Need to redo** — the wizard has a hard 409 guard against running two installs at once. Cancel the current one, re-flash if you got a partial state, and start again.

## Fallback: zero-touch firstrun.sh

The original `firstrun.sh` flow (`/api/install/firstrun.sh` → drop on the SD card boot partition) still works for headless environments where the server can't SSH the new Pi. It's intentionally not surfaced in the wizard.
