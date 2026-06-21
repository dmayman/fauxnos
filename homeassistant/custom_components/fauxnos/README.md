# Fauxnos — Home Assistant integration

A custom Home Assistant integration that surfaces each Fauxnos room as a
`media_player` entity, so you can:

- Control rooms from **Apple Home** via HA's HomeKit bridge.
- Build **Siri Shortcuts** for volume + source switching.
- Use Fauxnos rooms in **HA automations and scenes**.

## Design — Fauxnos stays the brain

This integration does **not** replace any part of Fauxnos. It is an *additive
satellite consumer*:

- **State in:** it subscribes to the existing retained
  `status/clients/+/{volume,mode,activity,hello}` MQTT topics and mirrors them
  into HA. On connect it publishes `get/clients/all/status` to force a full
  snapshot.
- **Commands out:** volume → `set/clients/<id>/volume` (int 0–100 as string),
  source → `set/clients/<id>/mode` (`<source_id>`). These are the exact topics
  the iOS and web UIs already use.
- It reads device names + per-device source labels from the REST API
  (`GET /api/clients`, `GET /api/clients/<id>/sources`).

The HA entity is a **pure mirror** — it never holds a divergent desired state,
so it can't fight the iOS/web UIs. If HA is down, Fauxnos is unaffected.

Nothing under `ios/`, `pi/src/fauxnos-server/`, or `pi/src/fauxnos-client/`
changes. The MQTT contract is reused as-is.

## Install

1. Copy `custom_components/fauxnos/` into your HA config directory so you have
   `<config>/custom_components/fauxnos/`.
2. Restart Home Assistant.
3. **Settings → Devices & Services → Add Integration → Fauxnos.**
4. Fill in:
   - **Fauxnos server URL** — default `http://fauxnos.local`
   - **MQTT broker host** — default `fauxnos000.local`, port `1883`
   - MQTT username/password — leave blank (the broker has no auth today)

One `media_player.<room>` entity appears per Fauxnos device. Changing volume or
source in the iOS/web UI updates the entity within ~1s, and vice-versa.

> This integration declares `paho-mqtt` as a requirement (unpinned); Home
> Assistant resolves it to the same version its own MQTT integration uses
> (`paho-mqtt==2.1.0` on HA 2026.2), so there's no version conflict.

## Expose to Apple Home / Siri

1. Set up the **HomeKit Bridge** integration (Settings → Devices & Services →
   Add Integration → *HomeKit Bridge*) if you haven't.
2. Include the `media_player.<room>` entities in the bridge. HA maps a
   `media_player` to a **Television accessory** in HomeKit — you get power, an
   **input list** (your Fauxnos sources), and **volume**.
3. Scan the HomeKit pairing QR in the Apple Home app.

### Siri Shortcuts

- **Source:** "Hey Siri, set *Kitchen* to *Spotify*" works via the TV
  accessory's input selection. You can also build a Shortcut: *Home → Control
  <Kitchen> → set input to Spotify.*
- **Volume:** HomeKit TV volume is **relative** (up/down), so absolute "set to
  30%" via Siri is limited. For exact levels, build a Shortcut around the HA
  `media_player.volume_set` service (via the Home Assistant app's Shortcuts
  actions), or use the volume slider in the HA / iOS app.

## Example automation

Mirror the vinyl-table cascade from the HA side — note you usually **don't need
this**, because `fauxnos-server` already fires the Particle call when the mode
changes. This just adds a Siri/scene front door:

```yaml
automation:
  - alias: "Good morning — Kitchen to Spotify"
    trigger:
      - platform: time
        at: "07:00:00"
    action:
      - service: media_player.select_source
        target:
          entity_id: media_player.kitchen
        data:
          source: Spotify
      - service: media_player.volume_set
        target:
          entity_id: media_player.kitchen
        data:
          volume_level: 0.3
```

## Scope / limitations (v1)

- Unit of control is the **device**, not the group (matches the MQTT contract).
- No transport (play/pause/next), EQ, calibration, or IR here — those live in
  the iOS/web UIs.
- Live disconnect detection is best-effort (no broker LWT in the contract):
  availability tracks the HA↔broker link plus whether the device has ever
  reported state.
