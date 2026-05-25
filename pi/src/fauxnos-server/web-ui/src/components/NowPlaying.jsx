import { useEffect, useRef, useState } from 'react'
import { Play, Pause, SkipBack, SkipForward, Music, AudioLines, Plug, Cast } from 'lucide-react'
import { sendPlayback } from '../api'

/**
 * Default per-source glyph for the "album art" slot when no track
 * metadata is available (analog/aux/custom sources, or spotify with
 * no active session).
 */
function SourceGlyph({ sourceId, size = 56 }) {
  const Icon =
    sourceId === 'spotify' ? Music :
    sourceId === 'airplay' ? Cast :
    sourceId === 'analog'  ? AudioLines :
    Plug
  return <Icon size={size} aria-hidden />
}

function fmtTime(ms) {
  if (!Number.isFinite(ms) || ms < 0) ms = 0
  const total = Math.floor(ms / 1000)
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}

/**
 * Interpolate playback position client-side so the progress bar moves
 * smoothly between server events. Re-bases on every `playback` change.
 *
 * Critically uses `playback.updated_at` (the server's stamp at the time
 * the event was generated) as the time origin — NOT Date.now() at the
 * moment we received the message. A retained MQTT message published 30s
 * before the UI loaded should start the bar at `position_ms + 30s`, not
 * at `position_ms`.
 *
 * Assumes server + browser clocks are roughly NTP-synced. If they're
 * skewed, the bar will be off by the skew (constant offset, not
 * cumulative).
 */
function useInterpolatedPosition(playback) {
  const computeNow = () => {
    if (!playback) return 0
    if (!playback.is_playing) return playback.position_ms ?? 0
    const t0 = playback.updated_at ?? Date.now()
    return Math.max(0, (playback.position_ms ?? 0) + (Date.now() - t0))
  }
  const [pos, setPos] = useState(computeNow)

  useEffect(() => {
    setPos(computeNow())
    if (!playback?.is_playing) return undefined
    const id = setInterval(() => setPos(computeNow()), 250)
    return () => clearInterval(id)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playback?.position_ms, playback?.updated_at, playback?.is_playing])

  return pos
}

/**
 * Now-playing strip rendered inside a group card.
 *
 * `clientId` is the home_client_id of the group (the device that owns
 * the spotify session). `sourceId` is the currently active source
 * (decides which fallback glyph to show when no metadata).
 *
 * - With metadata: art + title/artist + progress bar + transport controls.
 * - Without:       big source glyph + source label, no controls.
 */
export default function NowPlaying({ clientId, sourceId, track, playback }) {
  const hasMeta = !!track && (track.title || track.artist)
  const isPlaying = !!playback?.is_playing
  const duration = track?.duration_ms || 0
  const livePos = useInterpolatedPosition(playback)
  const clampedPos = Math.max(0, Math.min(livePos, duration || livePos))
  const pct = duration > 0 ? (clampedPos / duration) * 100 : 0

  // Optimistic flip on click — the real state lands via MQTT within
  // a few hundred ms. snapcast's audio buffer means audio always lags
  // the UI; the controls should reflect intent immediately.
  const [pendingPlaying, setPendingPlaying] = useState(null)
  useEffect(() => { setPendingPlaying(null) }, [playback?.updated_at])
  const displayedPlaying = pendingPlaying ?? isPlaying

  const onPlayPause = async () => {
    if (!clientId) return
    setPendingPlaying(!displayedPlaying)
    try {
      await sendPlayback(clientId, 'playpause')
    } catch {
      setPendingPlaying(null)
    }
  }
  const onNext = async () => {
    if (!clientId) return
    try { await sendPlayback(clientId, 'next') } catch { /* ignore */ }
  }
  const onPrev = async () => {
    if (!clientId) return
    try { await sendPlayback(clientId, 'prev') } catch { /* ignore */ }
  }
  const onSeek = async (e) => {
    if (!clientId || !duration) return
    const target = Math.round((parseFloat(e.target.value) / 100) * duration)
    try { await sendPlayback(clientId, 'seek', { position_ms: target }) } catch { /* ignore */ }
  }

  const hasControls = sourceId === 'spotify'

  return (
    <div className="fx-now-playing">
      <div className="fx-np-art">
        {hasMeta && track.art_url ? (
          <img src={track.art_url} alt="" loading="lazy" />
        ) : (
          <SourceGlyph sourceId={sourceId} />
        )}
      </div>

      <div className="fx-np-body">
        <div className="fx-np-text">
          <div className="fx-np-title" title={hasMeta ? track.title : sourceId}>
            {hasMeta ? track.title : (sourceId || '—')}
          </div>
          <div className="fx-np-sub" title={hasMeta ? `${track.artist} — ${track.album}` : ''}>
            {hasMeta
              ? [track.artist, track.album].filter(Boolean).join(' — ')
              : ' '}
          </div>
        </div>

        {hasControls && hasMeta && (
          <>
            <div className="fx-np-progress">
              <span className="fx-np-time fx-num">{fmtTime(clampedPos)}</span>
              <div className="fx-np-progress-track">
                <div className="fx-np-progress-fill" style={{ width: `${pct}%` }} />
                <input
                  type="range"
                  min={0}
                  max={100}
                  step={0.1}
                  value={pct}
                  className="fx-np-progress-input"
                  aria-label="Seek"
                  onChange={onSeek}
                />
              </div>
              <span className="fx-np-time fx-num">{fmtTime(duration)}</span>
            </div>

            <div className="fx-np-controls">
              <button
                type="button"
                className="fx-icon-btn"
                onClick={onPrev}
                title="Previous"
                aria-label="Previous"
              >
                <SkipBack size={16} />
              </button>
              <button
                type="button"
                className="fx-icon-btn fx-np-play"
                onClick={onPlayPause}
                title={displayedPlaying ? 'Pause' : 'Play'}
                aria-label={displayedPlaying ? 'Pause' : 'Play'}
              >
                {displayedPlaying ? <Pause size={18} /> : <Play size={18} />}
              </button>
              <button
                type="button"
                className="fx-icon-btn"
                onClick={onNext}
                title="Next"
                aria-label="Next"
              >
                <SkipForward size={16} />
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
