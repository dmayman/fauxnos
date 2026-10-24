import { noiseArtUrl } from './noiseArt'

/* ─────────────────────────────────────────────────────────────────────────────
 * Shared now-playing derivations.
 *
 * The card and the page backdrop both need to answer "what is this group
 * playing, and from where" — the MQTT-mode-with-stream-id-fallback dance and
 * the home-client fallback chain live here so the two can't drift.
 * ────────────────────────────────────────────────────────────────────────── */

/* home_client_id can be null when the server hasn't materialized it yet (or
   for groups where snapcast/spotify state is out of sync). Fall back to: the
   single client (single-device groups), the stream-id-encoded home, or the
   first client. Tracks/playback MQTT keys use this id, so a null home means
   the media lockup can never resolve metadata. */
export function homeIdOf(group) {
  return group.home_client_id
    || (group.clients.length === 1 ? group.clients[0]?.id : null)
    || (group.stream_id?.match(/source_(fauxnos\d+)_/)?.[1])
    || group.clients[0]?.id
}

/* The source the group is on right now: the device's reported MQTT mode, or
   the source encoded in its snapcast stream id before it has reported one. */
export function sourceIdOf(group, mqtt, homeClientId = homeIdOf(group)) {
  return mqtt.modes[homeClientId]
    || (group.stream_id ? group.stream_id.replace(/^source_fauxnos\d+_/, '') : null)
}

/* Cover of the first group playing something with art — a Spotify track, the
   generated art of Noise, or a Library track's cover — the art the page
   backdrop renders. null when nothing is playing (iOS
   GroupsListView.backdropArtSource). */
export function backdropArtUrl(groups, mqtt, library) {
  for (const group of groups) {
    const home = homeIdOf(group)
    const track = mqtt.tracks[home]
    const source = sourceIdOf(group, mqtt, home)
    if (source === 'spotify'
        && track?.art_url && (track.title || track.artist)) return track.art_url
    if (source === 'noise') return noiseArtUrl(mqtt.noise?.[home]?.color)
    if (source === 'library') {
      const art = libraryTrackOf(mqtt, home, library)?.art
      if (art) return `/library-art/${art}`
    }
  }
  return null
}

/* The library track a room's player is on, or null (nothing loaded, or a
   URL from outside the library, like a radio stream). */
export function libraryTrackOf(mqtt, clientId, library) {
  const path = mqtt.library?.[clientId]?.path
  return path ? library?.byPath?.get(path) || null : null
}
