# Fauxnos Volume Architecture

The single most important invariant in fauxnos audio:

> **Each source has exactly one volume attenuation stage.**

Multi-stage attenuation (PA × snapcast × hardware × …) multiplies, gets confusing, and produces volume sliders that don't match what the speakers actually do. We hardcode the architecture so this can't happen accidentally.

## Per-source attenuation table

| Source       | Attenuator         | Other stages held at | Configured via                      |
|--------------|--------------------|----------------------|-------------------------------------|
| **Spotify**  | snapcast client    | PA snapsink @ 100%, go-librespot has `external_volume:true` (it reports, doesn't apply) | `volume_controller: snapcast` |
| **AirPlay**  | snapcast client    | PA snapsink @ 100%, shairport-sync configured to forward (not apply) | `volume_controller: snapcast` |
| **Analog In**| PA `analogsink`    | PA loopback `analog_input → analogsink` runs at 100% | `volume_controller: self` |

The `volume_controller` field on each `source` in `client_config.yaml` is the **only** place this is encoded. Everything else (source_manager, mqtt_client, the UI) reads from there.

## Audio pipeline (with attenuation point marked)

```
SPOTIFY
─────────────────────────────────────────────────────────────────────────────
Spotify app
   │  (sets desired volume → libspot protocol)
   ▼
go-librespot (external_volume:true → DOES NOT attenuate, just reports volume)
   │
   ▼ FIFO /tmp/snapfifo/spotify_fauxnos<NNN>
snapserver
   │
   ▼
snapclient (software mixer)  ◄── *** ATTENUATES HERE *** (group volume)
   │
   ▼
PA snapsink @ 100%          (forced by source_manager when this is active)
   │
   ▼ PA loopback @ default (100%)
alsa_output → HiFiBerry DAC → speaker


AIRPLAY (similar)
─────────────────────────────────────────────────────────────────────────────
iOS / macOS device
   │  (AirPlay volume in iOS sends to shairport)
   ▼
shairport-sync (configured to forward, not apply, the Apple-side volume)
   │
   ▼ FIFO /tmp/snapfifo/airplay_fauxnos<NNN>
snapserver
   │
   ▼
snapclient (software mixer) ◄── *** ATTENUATES HERE ***
   │
   ▼
PA snapsink @ 100%
   │
   ▼ PA loopback @ 100%
alsa_output → HiFiBerry DAC → speaker


ANALOG IN
─────────────────────────────────────────────────────────────────────────────
RCA / 3.5mm jack → ADC half of HiFiBerry DAC+ADC
   │
   ▼ alsa_input (no volume control)
PA loopback (alsa_input → analogsink) @ default (100%, no attenuation)
   │
   ▼
PA analogsink              ◄── *** ATTENUATES HERE ***
   │
   ▼ PA loopback @ 100%
alsa_output → HiFiBerry DAC → speaker
```

The `snapcast client volume` and `PA analogsink volume` are the only knobs that ever move. **Every other stage stays at unity gain.**

## What the UI slider represents

The fauxnos UI volume slider always shows the **effective volume of the currently active source** — i.e. the value of whichever single attenuator is in use:

- Active source = Spotify or AirPlay → slider = snapcast client volume (0–100%)
- Active source = Analog In → slider = PA `analogsink` volume (0–100%)

Switching sources should always show the volume associated with the new active source's attenuator. Each source remembers its own last-known volume in `~/.config/fauxnos/client_state.json` (`source_volumes` map).

## Bidirectional sync — who is the source of truth?

The attenuator (snapcast client OR PA sink) is always the source of truth for the *current* volume. Other endpoints (Spotify app, fauxnos UI, MQTT) all reflect that single value.

### Spotify ⇄ snapcast (Spotify source only)

| Direction | Path | Status |
|---|---|---|
| Spotify app → snapcast | go-librespot WS event `/events` → server-side `VolumeManager` → snapcast `Client.SetVolume` | ✅ working |
| snapcast → Spotify app | snapcast `Client.OnVolumeChanged` → push back to go-librespot | 🟡 **Accepted drift, deferred.** When the user moves the fauxnos UI slider while Spotify is playing, the *audio* volume changes correctly (UI → snapcast), but the Spotify app's own slider stays where it was — it'll re-sync on the next Spotify-side change. We're choosing not to fight this for now; revisit if it becomes annoying. |

### Fauxnos UI ⇄ snapcast / PA

| Direction | Path | Status |
|---|---|---|
| UI slider → attenuator | UI publishes `set/clients/<id>/volume` MQTT → fauxnos_client `source_manager.set_volume` → snapcast or PA depending on active source's `volume_controller` | ✅ subscribe path works (PA controller works, snapcast lookup currently broken — see TODOs) |
| attenuator → UI slider | snapcast/PA volume change → fauxnos_client publishes `status/clients/<id>/volume` MQTT → UI updates slider | ❌ TODO — `source_manager.set_volume` doesn't currently call `mqtt_client.update_volume` after applying |

## Subtle correctness rules

1. **Switching sources does not normalize the new source's attenuator to the old source's value.** Each source restores its own last-known volume from state. (This is why `snapcast client volume = 59` while `analogsink = 0%` is currently fine — you've just got Spotify selected at 59 and analog hasn't been used.)

2. **PA sinks for snapcast-controlled sources MUST be forced to 100% on source switch**, not just "left alone." If the previous source set the sink to 30% and the new source uses `volume_controller: snapcast`, leaving the PA sink at 30% would create a hidden second stage. `source_manager._set_source_volume` does this correctly today.

3. **snapcast volume changes don't propagate when a non-snapcast source is active.** If you're playing Analog and someone external changes the snapcast group volume (e.g. another snapcast UI, `snapctl`), it has no audible effect, and the fauxnos UI slider — which is bound to the *active* source's attenuator — should not move. Only when Spotify/AirPlay is the active source should snapcast-side changes surface.

## Known TODOs

### In scope (active, this round)

- `source_manager.set_volume` should call `mqtt_client.update_volume` after a successful change so the UI MQTT subscription gets immediate feedback
- snapcast client lookup currently uses MAC; should use hostID (which is always `fauxnos<NNN>`) to avoid eth0 vs wlan0 MAC mismatches when a Pi's primary interface differs from what install.sh recorded
- Server-side `VolumeManager` should publish `status/clients/<id>/volume` MQTT after applying a snapcast change, so a Spotify-app volume change reaches the UI in real time

### Deferred — Spotify-first scope

- **All AirPlay volume work** is paused until the Spotify path is solid end-to-end. AirPlay sources are configured (`volume_controller: snapcast`) and audio plays, but per-instance shairport behavior, AirPlay → snapcast bridging, and AirPlay → UI status are not validated.
- **Snapcast → Spotify back-channel** (UI changes → Spotify app slider updates). Functionally the volume *sound* is controllable from both interfaces; only Spotify's visual slider drifts. Acceptable.

### Future hardening

- Single source-of-truth for `status/clients/<id>/*`: have `fauxnos_client.py` subscribe to snapcast JSON-RPC notifications for its own client and republish. Eliminates the multiple-publishers approach (UI handler + VolumeManager) we're using now.
