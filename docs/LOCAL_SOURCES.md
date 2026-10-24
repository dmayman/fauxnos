# Local sources: Noise and Library

Two sources that play **on the device itself**, rather than arriving over
snapcast like Spotify does:

- **Noise**: endless white, pink or brown noise, generated on the device.
- **Library**: MP3s (or any audio URL) played by the device's own MPD,
  streamed over HTTP from the server's library folder.

They exist for room routines. For example, bedtime is soft light plus a
song, and then it drifts into sleep, which is lights off and noise all
night. Home Assistant or a wall panel drives them; the iOS app and web UI
show them as ordinary sources.

Every device can play both, but the apps list them only for rooms you add
them to. To add one, open the room's device panel in the web UI, click
**+** next to **Sources**, and choose **Noise** or **Library**. The row's
remove button takes it off again. The MQTT commands work on any updated
device either way.

## Why local, not snapcast

Overnight noise must not drop out. Through snapcast it would depend on the
server Pi, snapserver and Wi-Fi all staying up until morning, so one server
update or one Wi-Fi blip would stop it. Generated on the device, noise
depends only on that device staying powered.

It is the same shape AirPlay already has: a local producer writes into its
own PulseAudio null sink, which loops into `eq_sink`. The source manager
mutes and unmutes that sink like any other. Nothing about grouping,
`home_source` or the snapcast reconcile code changes.

The trade-off is that neither source is multiroom, the same as AirPlay and
Analog. The server already refuses a non-Spotify source for a group with
more than one member.

## How each one works

| | Noise | Library |
|---|---|---|
| Producer | `fauxnos-noise.service` → `scripts/noise-generator.sh` (sox → pacat) | `fauxnos-mpd.service` (MPD, `~/.config/mpd/fauxnos.conf`) |
| PA sink | `noisesink` | `librarysink` |
| Runs | only while the source is active (`on_enter_command` starts it, `on_leave_command` stops it) | always (so HA's MPD integration can reach `:6600`) |
| Depends on network | no | yes, it streams from the server |
| Volume | `volume_controller: self` (the PA sink) | `volume_controller: self` (the PA sink) |

**Noise settings** are power, colour, and two cuts. Change them from the
noise card in the web UI, or with the `noise` MQTT command (later in this
doc). They're stored in `~/.config/fauxnos/noise.env` on the device:

| Variable | Values | Default |
|---|---|---|
| `FAUXNOS_NOISE_ON` | `1` or `0` | `1` |
| `FAUXNOS_NOISE_COLOR` | `white`, `pink`, or `brown` | `brown` |
| `FAUXNOS_NOISE_LOW_CUT` | `0` (off) or 20–2000 Hz, a high-pass | `0` |
| `FAUXNOS_NOISE_HIGH_CUT` | `0` (off) or 200–20000 Hz, a low-pass | `0` |

- Each colour has a fixed gain so all three sit at about the same level
  (around 0.1 RMS) with headroom. Raw sox noise clips at full scale, and
  the colours differ by about 8 dB. The cuts are 2-pole Butterworth
  filters after the gain, so they can only lower the level.
- Power off keeps Noise as the selected source but silent: the service
  stays up and sleeps instead of generating. Selecting Noise again (from
  the UI or a routine) turns it back on.
- A change restarts the generator if it's playing, which is a gap of
  about a second. The UI sends cut changes when you let go of a handle.

**What keeps noise playing:**

- The generator is its own systemd unit with `Restart=always` and no start
  limit. If PulseAudio restarts, pacat dies, the pipeline exits, and systemd
  restarts it a second later.
- Restarting the fauxnos daemon (a crash or an update) does not touch the
  generator. On startup the daemon no longer mutes the sink of the source
  it is about to restore, so there is no gap.
- If the generator is somehow dead, re-selecting Noise brings it back:
  `on_enter_command` re-runs on every route re-assertion, and
  `systemctl --user start` is a no-op when it is already running.
- What still interrupts it: rebooting the device, which includes an update
  that changed `default.pa`. Avoid running updates overnight.

**Library files** live on the server in `~/fauxnos-library/`. Override this
with `server.paths.library_dir` in `server_config.json`. Subfolders are
fine. Manage it from **Library** at the top of the web UI:

- Upload MP3 or M4A files by dropping them on the panel, or from **Add**.
- **Add → From YouTube** looks up a link and imports its audio as M4A,
  with the thumbnail as cover art. Needs `yt-dlp` and Deno on the server
  (install.sh installs both); most videos fail without Deno.
- **Add → From Spotify** reads a song's title, artist, length and cover
  from Spotify's public embed page, and imports the audio of the YouTube
  video closest in length (shown before you import), tagged with
  Spotify's details. Spotify's own audio is DRM-protected and isn't used.
- Browse by song, artist, album or playlist. Click a song to play it, with
  the rest of the list after it, in a room you pick.
- Edit a song's title, artist and album (written into the file's tags),
  make and rename playlists, and delete songs.

`modules/library.py` keeps an index in `.fauxnos/` inside the library
folder: tags and duration read with mutagen (without it, titles are file
names), cover art, and playlists. A file copied in by hand shows up on the
next listing.

| Endpoint | Does |
|---|---|
| `GET /library/<path>` | Serves a file, with Range requests |
| `GET /library-art/<id>.<ext>` | A song's cover art |
| `GET /api/library` | Songs, playlists, free space, import jobs |
| `POST /api/library/upload` | Upload (multipart `file`, MP3 or M4A) |
| `PATCH`/`DELETE /api/library/tracks/<id>` | Edit title/artist/album, or delete |
| `POST /api/library/playlists`, `PATCH`/`DELETE …/<id>` | Playlists |
| `POST /api/library/youtube/preview`, `POST /api/library/youtube` | YouTube look-up and import |
| `POST /api/library/spotify/preview` | Spotify song details and its YouTube match |
| `POST /api/library/play` | `{client_id, track_ids}`: play on a room |

## Commands (MQTT, on the fauxnos broker)

**Noise settings**, any subset; the device republishes the stored settings
retained on `status/clients/<id>/noise`, and rejects out-of-range values:

```
set/clients/<id>/noise  {"on": false}
set/clients/<id>/noise  {"color": "pink", "low_cut": 80, "high_cut": 6000}
```

**Switch source**, optionally crossfading:

```
set/clients/<id>/mode   "noise"                                 # instant (what the UIs send)
set/clients/<id>/mode   {"source": "noise", "fade_ms": 60000}   # crossfade over 60 s
```

**Play from the library.** This queues the items on the device's MPD,
starts playback into the still-muted sink, then switches to `library`:

```
set/clients/<id>/library/play  {"item": "lullabies/twinkle.mp3"}
set/clients/<id>/library/play  {"items": ["a.mp3", "b.mp3"], "loop": true, "fade_ms": 5000}
set/clients/<id>/library/stop  ""
set/clients/<id>/library/stop  {"fade_ms": 60000}
```

- `item`/`items` are paths under the library folder, or full URLs (internet
  radio works too).
- `loop: true` repeats a single item on its own, or several items as a
  playlist.
- `fade_ms` on `play` fades the music in. From another source it's a
  crossfade (below). If the room is already on Library, which is where a
  faded `stop` leaves it, the library sink starts silent and ramps up.
- `fade_ms` on `stop` fades the music to silence, then stops MPD. See
  [Fading to silence](#fading-to-silence). An empty payload stops at once.

**Play by name (Home Assistant).** The server keeps the library index on
`status/library/index` (retained: every song's `id`, `path`, `title`,
`artist`, `album`, `duration_ms`, and every playlist), republished whenever
it changes. To play, publish to the server, which resolves the names:

```
set/library/play  {"room": "Office", "playlist": "Bedtime", "loop": true}
set/library/play  {"room": "fauxnos003", "tracks": ["Twinkle Twinkle", "Hush Little Baby"], "fade_ms": 3000}
```

- `room` is a client id or room name. `tracks` are ids, paths or titles
  (case-insensitive); `playlist` is a name or id.
- Unknown rooms, playlists or songs are logged on the server and ignored.

**Library transport and now-playing.** Each device reports its player,
retained, on `status/clients/<id>/library` (`state`, `path`, `elapsed_ms`,
`duration_ms`, …), and takes:

```
set/clients/<id>/library/toggle  ""      # play/pause
set/clients/<id>/library/next    ""
set/clients/<id>/library/prev    ""
```

### Crossfades

`fade_ms` works between any two internal sources on different sinks, for
example Library → Noise, Spotify → Noise or AirPlay → Library. Anything
else switches instantly.

- The switch returns at once. The status topic shows the new source
  straight away, and a background thread ramps the two sinks on a fixed
  schedule, so a 60 s fade takes 60 s.
- The outgoing source's leave hooks (pause Spotify, stop MPD, stop the noise
  generator) run when the fade ends, not when it starts.
- A new switch or a volume change mid-fade lands the fade at its end state
  first. Switching back to the source being faded away from skips that
  source's leave hooks.
- Fades are capped at 10 minutes.

### Fading to silence

A crossfade needs a second source to fade to. `library/stop` with
`fade_ms` fades the music out with nothing taking its place:

```
set/clients/<id>/library/stop  {"fade_ms": 60000}
```

- The command returns at once. A background thread ramps `librarysink`
  down over `fade_ms`, on the same thread and schedule as a crossfade.
- At the end MPD stops, and the sink goes back to Library's stored
  volume with nothing playing into it. The room stays on Library,
  silent, and the volume slider never moves. The next `play` starts at
  the normal level, or fades in from silence if it has `fade_ms`.
- It lands like a crossfade does. A switch, a volume change, or a
  `library/play` mid-fade stops MPD at once and then does its own job,
  so a fade can never cut off music started after it.
- A faded `play` mid-fade-out turns around from the level the fade had
  reached. So does a faded `stop` mid-fade-in. Neither jumps to full
  volume first.
- If Library isn't the room's audible source, `stop` with `fade_ms` just
  stops MPD at once, the same as an empty payload.

## A routine, end to end

Bedtime (a song, 10 minutes) drifting into sleep (noise, all night) is two
commands:

```
# 19:30 — bedtime
set/clients/fauxnos003/library/play  {"item": "bedtime/goodnight.mp3", "loop": true, "fade_ms": 3000}
# 19:40 — sleep
set/clients/fauxnos003/mode          {"source": "noise", "fade_ms": 60000}
```

Ending the song with no noise after it is one command too:

```
set/clients/fauxnos003/library/stop  {"fade_ms": 60000}
```

The lights side is Home Assistant's job. Home Assistant reaches these
topics through a mosquitto bridge on its own broker, which relays one
room's `set/…` out and its `status/…` in under a `fauxnos/` prefix. The
bridge config and the office routine that drives it live in the
home-server repo (`stacks/home-automation/`), not here.

## Verifying on a device

The logic is covered by `test_source_fade.py` and
`test_mqtt_local_sources.py`, and the producers were exercised against a
real PulseAudio, sox, MPD and the server's `/library/` route. What only
hardware can show:

1. After the update reboot, `pactl list short sinks` lists `noisesink` and
   `librarysink`. Then check for crackle. There are now six live loopbacks
   on a Zero 2 W (see the comment in `default.pa`).
2. Select Noise in the app. Confirm `systemctl --user status
   fauxnos-noise` is active and you hear noise.
3. Run `systemctl --user restart fauxnos-client-<id>` while noise plays.
   The noise should not stop.
4. Run `pulseaudio -k` while noise plays. It should be back within a few
   seconds.
5. Put an MP3 in `~/fauxnos-library/` on the server, publish
   `library/play`, then publish `mode` with a 30 s fade to noise. You
   should hear a smooth crossfade, and MPD should stop at the end.
6. Play something from the library, then publish `library/stop
   {"fade_ms": 20000}`. The music should fade to silence over 20 s and
   `status/clients/<id>/library` should then read `"state": "stop"`, with
   `status/clients/<id>/volume` unchanged. Then publish `library/play`
   with `"fade_ms": 10000`: it should fade in from silence, not start at
   full volume.
