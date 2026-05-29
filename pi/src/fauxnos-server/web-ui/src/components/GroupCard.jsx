import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import {
  IconXFilled,
  IconUnlink,
  IconChevronDownFilled,
  IconBrandSpotifyFilled,
  IconBuildingBroadcastTowerFilled,
  IconMicrophoneFilled,
  IconExternalLinkFilled,
  IconHeadphonesFilled,
  IconPlayerPlayFilled,
  IconPlayerPauseFilled,
  IconPlayerTrackPrevFilled,
  IconPlayerTrackNextFilled,
} from '@tabler/icons-react'

/* Drag-handle glyph: two thin parallel bars, matching the Figma kitchen-row
   indicator. Tabler's IconGripVertical is 6 dots and reads as a different
   affordance, so we inline this tiny SVG instead. */
function DragBarsIcon({ size = 10 }) {
  const w = Math.max(4, Math.round(size * 0.6))
  return (
    <svg width={w} height={size} viewBox="0 0 6 10" fill="currentColor" aria-hidden>
      <rect x="0" y="0" width="2" height="10" rx="1" />
      <rect x="4" y="0" width="2" height="10" rx="1" />
    </svg>
  )
}
import VolumeSlider, { VolumeIcon } from './VolumeSlider'
import SourcePopover from './SourcePopover'
import useAlbumArtColor from '../hooks/useAlbumArtColor'
import { useTuning } from '../hooks/useTuning'
import { useTheme } from '../hooks/useTheme'
import { useSliderHover } from '../hooks/useSliderHover'
import { buildArtTokens } from '../lib/artTokens'
import { sendPlayback } from '../api'

/* Volume glyph ramps with the level: mute (X) is reserved for v === 0
   only — at low non-zero volumes we still show a wave, so the mute icon
   reliably signals "muted" (and clicking it = unmute). */
function volIconState(v) {
  if (v === 0) return 'mute'
  if (v < 40) return 'low'
  return 'high'
}

/* ─────────────────────────────────────────────────────────────────────────────
 * Source glyphs — used by both the album-art fallback and the source-trigger.
 * Spotify gets the brand mark; everything else uses semantically-close Tabler
 * solid glyphs until vendor SVGs land in Phase 6.
 * ────────────────────────────────────────────────────────────────────────── */
function SourceIcon({ sourceId, size = 24 }) {
  const Icon =
    sourceId === 'spotify' ? IconBrandSpotifyFilled :
    sourceId === 'airplay' ? IconBuildingBroadcastTowerFilled :
    sourceId === 'analog'  ? IconMicrophoneFilled :
    sourceId ? IconExternalLinkFilled :
    IconHeadphonesFilled
  return <Icon size={size} aria-hidden />
}

/* Drag image: a self-contained V2-pill snapshot of the dragged row, regardless
   of the source card's variant. We don't clone the source card — its layout
   (media region, art tokens, multi-row stack) leaks into the drag image and
   fights setDragImage's bounding box. Instead we synthesize a fresh
   `.fx-group-card-v2.v2-single` shell and drop a stripped row inside, so the
   natural CSS cascade renders it correctly. Lives at document.body off-screen
   and is removed on dragend. */
function buildDeviceDragGhost(row, cardRect) {
  if (!row || !cardRect) return null

  const ghost = document.createElement('div')
  ghost.className = 'fx-device-drag-ghost'
  ghost.style.width = `${cardRect.width}px`

  const card = document.createElement('div')
  card.className = 'fx-group-card-v2 v2-single fx-device-drag-card'
  card.setAttribute('data-has-media', 'false')

  const rows = document.createElement('div')
  rows.className = 'fx-group-rows'

  const clone = row.cloneNode(true)
  clone.classList.remove('with-source', 'is-drag-placeholder')
  clone.querySelectorAll(
    '.fx-row-drag, .fx-group-member-x, .fx-source-trigger, .fx-group-row-name-subtitle'
  ).forEach((n) => n.remove())

  rows.appendChild(clone)
  card.appendChild(rows)
  ghost.appendChild(card)
  document.body.appendChild(ghost)
  return ghost
}

function cleanupDeviceDragGhost() {
  document.querySelectorAll('.fx-device-drag-ghost').forEach(node => node.remove())
}

/* ─────────────────────────────────────────────────────────────────────────────
 * Helpers ported from the now-removed NowPlaying.jsx — interpolate playback
 * position client-side and format ms as m:ss.
 * ────────────────────────────────────────────────────────────────────────── */
function fmtTime(ms) {
  if (!Number.isFinite(ms) || ms < 0) ms = 0
  const total = Math.floor(ms / 1000)
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}

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

/* ─────────────────────────────────────────────────────────────────────────────
 * SourceTrigger — single button (current source icon + chevron) that opens
 * a SourcePopover listing every available source with the active one
 * checked and non-spotify locked in multi-room. Anchored top-right of the
 * outer card for V1/V3, inline in the row for V2/V4.
 * ────────────────────────────────────────────────────────────────────────── */
function SourceTrigger({ sources, currentSourceId, isMulti, groupId, homeClientId, onSwitchSource, onUngroupAll, onConfigure, anchored = false }) {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef(null)

  const handleSelect = (sourceId) => {
    onSwitchSource(groupId, homeClientId, sourceId)
    setOpen(false)
  }

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className={`fx-source-trigger${anchored ? ' anchor' : ''}${open ? ' open' : ''}`}
        onClick={() => setOpen(o => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={currentSourceId ? `Source: ${currentSourceId}` : 'Select source'}
        title={currentSourceId || 'Select source'}
      >
        <SourceIcon sourceId={currentSourceId} size={24} />
        <IconChevronDownFilled size={24} aria-hidden />
      </button>
      {open && (
        <SourcePopover
          sources={sources}
          currentSourceId={currentSourceId}
          isMulti={isMulti}
          anchorRef={triggerRef}
          onClose={() => setOpen(false)}
          onSelect={handleSelect}
          onUngroupAll={onUngroupAll}
          onConfigure={onConfigure}
        />
      )}
    </>
  )
}

/* ─────────────────────────────────────────────────────────────────────────────
 * MediaCard — inner sub-card with album art + track meta + progress + controls.
 * Renders for V1/V3 (anywhere a track is present). Falls back to a source
 * glyph in the art slot when no metadata is available.
 * ────────────────────────────────────────────────────────────────────────── */
function MediaCard({ clientId, sourceId, track, playback, empty = false, groupName }) {
  if (empty) {
    return (
      <div className="fx-group-media-card is-empty">
        <div className="fx-group-media-art is-empty" aria-hidden>
          <IconBrandSpotifyFilled size={72} stroke={0} />
        </div>
        <div className="fx-group-media-body">
          <span className="fx-media-empty-cta">
            Connect to {groupName} in Spotify
          </span>
        </div>
      </div>
    )
  }
  const hasMeta = !!track && (track.title || track.artist)
  const isPlaying = !!playback?.is_playing
  const duration = track?.duration_ms || 0
  const livePos = useInterpolatedPosition(playback)
  const clampedPos = Math.max(0, Math.min(livePos, duration || livePos))
  const pct = duration > 0 ? (clampedPos / duration) * 100 : 0

  const [pendingPlaying, setPendingPlaying] = useState(null)
  useEffect(() => { setPendingPlaying(null) }, [playback?.updated_at])
  const displayedPlaying = pendingPlaying ?? isPlaying

  const onPlayPause = async () => {
    if (!clientId) return
    setPendingPlaying(!displayedPlaying)
    try { await sendPlayback(clientId, 'playpause') } catch { setPendingPlaying(null) }
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

  const hasControls = sourceId === 'spotify' && hasMeta
  const titleText = hasMeta ? track.title : (sourceId || '—')
  const subText = hasMeta ? [track.artist, track.album].filter(Boolean).join(' · ') : ''
  const progressHover = useSliderHover()

  return (
    <div className="fx-group-media-card">
      <div className="fx-group-media-art">
        {hasMeta && track.art_url
          ? <img src={track.art_url} alt="" loading="lazy" />
          : <SourceIcon sourceId={sourceId} size={56} />}
      </div>
      <div className="fx-group-media-body">
        <div className="fx-group-media-text">
          <span className="fx-title-track" title={titleText}>{titleText}</span>
          {subText && <span className="fx-meta-track" title={subText}>{subText}</span>}
        </div>
        {hasControls && (
          <div className="fx-group-progress">
            <div className="fx-group-progress-bar">
              <span className="fx-time-track">{fmtTime(clampedPos)}</span>
              <div
                className="fx-group-progress-track"
                ref={progressHover.ref}
                onPointerMove={progressHover.onPointerMove}
                onPointerLeave={progressHover.onPointerLeave}
              >
                <div className="fx-group-progress-hover" />
                <div className="fx-group-progress-fill" style={{ width: `${pct}%` }} />
                <div className="fx-group-progress-thumb" style={{ left: `${pct}%` }} />
                <input
                  type="range"
                  min={0}
                  max={100}
                  step={0.1}
                  value={pct}
                  className="fx-group-progress-input"
                  aria-label="Seek"
                  onChange={onSeek}
                />
              </div>
              <span className="fx-time-track">{fmtTime(duration)}</span>
            </div>
            <div className="fx-group-progress-actions">
              <button type="button" className="fx-icon-btn" onClick={onPrev} aria-label="Previous">
                <IconPlayerTrackPrevFilled size={16} stroke={0} />
              </button>
              <button type="button" className="fx-icon-btn" onClick={onPlayPause} aria-label={displayedPlaying ? 'Pause' : 'Play'}>
                {displayedPlaying
                  ? <IconPlayerPauseFilled size={18} stroke={0} />
                  : <IconPlayerPlayFilled size={18} stroke={0} />}
              </button>
              <button type="button" className="fx-icon-btn" onClick={onNext} aria-label="Next">
                <IconPlayerTrackNextFilled size={16} stroke={0} />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────────────
 * AllRow — accent-colored "All" entry that controls every device in a
 * multi-room group. Display value = average of member volumes; dragging
 * preserves each member's offset from the average (ratio-preserving), so
 * pre-tuned room balance survives global moves. Anchors a baseline
 * snapshot on the first publish of a drag and discards it after a short
 * idle window, so successive drags compose naturally.
 * ────────────────────────────────────────────────────────────────────────── */
function AllRow({ clients, mqtt, homeClientId, onReturnHome, inlineSourceTrigger }) {
  const readVol = useCallback(
    (c) => mqtt.volumes[c.id] ?? c.config?.volume?.percent ?? 0,
    [mqtt.volumes],
  )
  const vols = clients.map(readVol)
  const avg = vols.length
    ? Math.round(vols.reduce((a, b) => a + b, 0) / vols.length)
    : 0
  const iconState = volIconState(avg)
  const lastNonZeroAvgRef = useRef(avg > 0 ? avg : 50)
  if (avg > 0) lastNonZeroAvgRef.current = avg

  const sessionRef = useRef(null)
  const idleTimerRef = useRef(null)
  useEffect(() => () => {
    if (idleTimerRef.current) clearTimeout(idleTimerRef.current)
  }, [])

  const wrappedMqtt = {
    ...mqtt,
    volumes: {},
    publishVolume: (_id, newAvg) => {
      if (!sessionRef.current) {
        sessionRef.current = { avg, vols: clients.map(readVol) }
      }
      const delta = newAvg - sessionRef.current.avg
      sessionRef.current.vols.forEach((v, i) => {
        const target = Math.max(0, Math.min(100, v + delta))
        mqtt.publishVolume(clients[i].id, target)
      })
      if (idleTimerRef.current) clearTimeout(idleTimerRef.current)
      idleTimerRef.current = setTimeout(() => { sessionRef.current = null }, 500)
    },
  }

  const toggleAllMute = () => {
    const next = avg === 0 ? (lastNonZeroAvgRef.current || 50) : 0
    wrappedMqtt.publishVolume('__all__', next)
  }

  return (
    <div className={`fx-group-row-v2 is-all${inlineSourceTrigger ? ' with-source' : ''}`}>
      <div className="fx-group-row-name">
        <span className="fx-name-device fx-group-row-name-label">All</span>
        <button
          type="button"
          className="fx-group-member-x"
          onClick={() => {
            clients.forEach(c => {
              if (c.id !== homeClientId) onReturnHome(c.id)
            })
          }}
          title="Ungroup all"
          aria-label="Ungroup all"
          style={{ marginLeft: 8 }}
        >
          <IconUnlink size={14} stroke={2.5} />
          <span className="fx-group-member-x-label">Ungroup all</span>
        </button>
      </div>
      <div className="fx-group-row-volume">
        <button
          type="button"
          className="fx-group-row-volume-icon"
          onClick={toggleAllMute}
          aria-label={avg === 0 ? 'Unmute all' : 'Mute all'}
        >
          <VolumeIcon size={20} state={iconState} />
        </button>
        <VolumeSlider
          clientId="__all__"
          value={avg}
          mqtt={wrappedMqtt}
          variant="card-v2"
          hideIcon
          hideLabel
          ariaLabel="All devices volume"
        />
      </div>
      {inlineSourceTrigger}
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────────────
 * DeviceRow — one entry in the device-rows section of a group card.
 *   - Grid columns: name (150px) | volume (1fr) [ | source-trigger ]
 *   - The per-row drag handle (the two-bars Figma indicator) shows on hover
 *     for non-home devices in a multi-room card.
 *   - For the "V2 single-device + no media" variant, the source-trigger
 *     is rendered inline as the third column (via `inlineSourceTrigger`).
 * ────────────────────────────────────────────────────────────────────────── */
function DeviceRow({
  client, isHome, isMulti, isOnly, isAirplayHome, hasMedia,
  nameMap, mqtt, onReturnHome, onDragStart, onDragEnd,
  inlineSourceTrigger, isDragPlaceholder,
}) {
  const name = nameMap[client.id] || client.host?.name || client.id
  const vol = mqtt.volumes[client.id] ?? client.config?.volume?.percent ?? 0
  const isAirplay = isOnly ? isAirplayHome : (mqtt.modes[client.id] === 'airplay')
  const rowRef = useRef(null)
  const iconState = volIconState(vol)
  const lastNonZeroRef = useRef(vol > 0 ? vol : 50)
  if (vol > 0) lastNonZeroRef.current = vol
  const toggleMute = () => {
    if (isAirplay) return
    const next = vol === 0 ? (lastNonZeroRef.current || 50) : 0
    mqtt.publishVolume?.(client.id, next)
  }

  // The name container is the row's draggable handle. For multi-room
  // non-home rows that means "move me to another group"; for single-device
  // cards (only ever 1 row) it means "move the whole device to another
  // group." We don't make the home row of a multi-room group draggable
  // because dragging the home would disband the group, which isn't a
  // useful affordance — users return-home via the X.
  const isRowDraggable = !isMulti || !isHome
  const handleNameDragStart = (e) => {
    if (e.target.closest('button, input, [role="slider"]')) {
      e.preventDefault()
      return
    }
    e.dataTransfer.setData('text/plain', client.id)
    e.dataTransfer.effectAllowed = 'move'
    const row = rowRef.current
    const card = row?.closest('.fx-group-card-v2')
    if (row && card) {
      const rowRect = row.getBoundingClientRect()
      const cardRect = card.getBoundingClientRect()
      const ghost = buildDeviceDragGhost(row, cardRect)
      if (ghost) {
        // .v2-single .fx-group-rows pads 16/24/16/32 — the cloned row sits at
        // that offset from the ghost's top-left. Mirror the user's grab point
        // within the row into the same point on the ghost.
        const SHELL_PAD_LEFT = 32
        const SHELL_PAD_TOP = 16
        const offsetX = (e.clientX - rowRect.left) + SHELL_PAD_LEFT
        const offsetY = (e.clientY - rowRect.top) + SHELL_PAD_TOP
        e.dataTransfer.setDragImage(ghost, offsetX, offsetY)
      }
    }
    onDragStart(client.id)
  }
  const handleNameDragEnd = (e) => {
    cleanupDeviceDragGhost()
    onDragEnd?.(e)
  }

  return (
    <div
      ref={rowRef}
      className={`fx-group-row-v2${inlineSourceTrigger ? ' with-source' : ''}${isDragPlaceholder ? ' is-drag-placeholder' : ''}`}
    >
      <div
        className={`fx-group-row-name${isRowDraggable ? ' draggable' : ''}`}
        draggable={isRowDraggable}
        onDragStart={isRowDraggable ? handleNameDragStart : undefined}
        onDragEnd={isRowDraggable ? handleNameDragEnd : undefined}
      >
        {isRowDraggable && (
          <span className="fx-row-drag" aria-hidden>
            <DragBarsIcon size={10} />
          </span>
        )}
        <span className="fx-name-device fx-group-row-name-label">
          {name}
        </span>
        {isMulti && !isHome && (
          <button
            type="button"
            className="fx-group-member-x"
            onClick={() => onReturnHome(client.id)}
            title="Ungroup"
            aria-label="Ungroup"
            style={{ marginLeft: 8 }}
          >
            <IconUnlink size={14} stroke={2.5} />
            <span className="fx-group-member-x-label">Ungroup</span>
          </button>
        )}
      </div>
      <div className="fx-group-row-volume">
        {isAirplay ? (
          <span className="fx-group-row-volume-icon">
            <VolumeIcon size={20} state={iconState} />
          </span>
        ) : (
          <button
            type="button"
            className="fx-group-row-volume-icon"
            onClick={toggleMute}
            aria-label={vol === 0 ? `Unmute ${name}` : `Mute ${name}`}
          >
            <VolumeIcon size={20} state={iconState} />
          </button>
        )}
        <VolumeSlider
          clientId={client.id}
          value={vol}
          mqtt={mqtt}
          variant="card-v2"
          hideIcon
          hideLabel
          ariaLabel={`${name} volume`}
          external={isAirplay}
        />
      </div>
      {inlineSourceTrigger}
      {/* AirPlay caption sits below the row, under the name. We position it
          absolutely so the row's grid track heights don't grow when the
          caption is present. */}
      {isAirplay && isOnly && (
        <span
          className="fx-group-row-name-subtitle"
          style={{ position: 'absolute', left: 8, top: 'calc(50% + 14px)' }}
        >
          Volume controlled by iPhone
        </span>
      )}
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────────────
 * GroupCard — orchestrates the four variant layouts.
 * ────────────────────────────────────────────────────────────────────────── */
export default function GroupCard({
  group, nameMap, mqtt,
  isDragTarget, isDragging, dragClientId, placeholderClientId,
  onDragStart, onDragEnd,
  onDragOverGroup, onDragLeaveGroup, onDropOnGroup,
  onReturnHome, onSwitchSource, onOpenDevice,
}) {
  const isMulti = group.clients.length > 1
  // home_client_id can be null when the server hasn't materialized it yet
  // (or for groups where snapcast/spotify state is out of sync). Fall back
  // to: the single client (single-device groups), the stream-id-encoded
  // home, or the first client. Tracks/playback MQTT keys use this id, so
  // a null home means MediaCard can never resolve metadata.
  const homeClientId =
    group.home_client_id
    || (group.clients.length === 1 ? group.clients[0]?.id : null)
    || (group.stream_id?.match(/source_(fauxnos\d+)_/)?.[1])
    || group.clients[0]?.id
  const cardRef = useRef(null)

  const sorted = [...group.clients].sort((a, b) => {
    if (a.id === homeClientId) return -1
    if (b.id === homeClientId) return 1
    return 0
  })
  const homeClient = sorted.find(c => c.id === homeClientId) || sorted[0]
  const track = mqtt.tracks[homeClientId]
  const playback = mqtt.playback[homeClientId]
  const hasMedia = !!track && (track.title || track.artist)
  const isAirplayHome = mqtt.modes[homeClient?.id] === 'airplay'

  // Extract album-art dominant color and project it onto the card's --art-*
  // tokens. Hook is a no-op when art_url is missing or extraction fails.
  const artColor = useAlbumArtColor(hasMedia ? track?.art_url : null)
  const { effective } = useTheme()
  const tuning = useTuning()
  const artStyle = artColor ? buildArtTokens(artColor, effective === 'dark', tuning) : undefined

  const currentSourceId = mqtt.modes[homeClientId]
    || (group.stream_id ? group.stream_id.replace(/^source_fauxnos\d+_/, '') : null)

  // V1 = multi + media | V2 = single + no media | V3 = single + media | V4 = multi + no media
  const variant = isMulti
    ? (hasMedia ? 'v1' : 'v4')
    : (hasMedia ? 'v3' : 'v2')

  const isSingleNoMedia = variant === 'v2'
  const isDraggedSingleCard = !isMulti && sorted[0]?.id === placeholderClientId
  // Source card: this group contains the device being dragged. Used to disable
  // drop affordance on the source so the placeholder doesn't double as a drop
  // target. Uses the immediate dragClientId (not the rAF-delayed placeholder)
  // so the source is gated from the first dragover.
  const isDragSource = !!dragClientId && group.clients.some(c => c.id === dragClientId)
  // Multi-room groups always show a media card — when no track is playing,
  // we render a skeleton "Connect Spotify to begin" zero state so users
  // understand the slot exists and what fills it. Single-device cards
  // still drop to the inline-trigger V2 layout when there's nothing
  // playing, since the same group is just one row.
  const showMediaCard = hasMedia || isMulti // V1, V3, V4
  const isEmptyMedia = isMulti && !hasMedia // V4 zero-state

  // Reveal animation: when the media card appears (was hidden, now visible),
  // grow the card height while the entire media region moves as one piece.
  // On exit the same shape runs in reverse — we keep the MediaCard mounted
  // with the last known props until the transition finishes, then drop it.
  // Two rAFs sandwich the enter initial-state paint so the transition fires
  // instead of jumping straight to the final values.
  const ANIM_MS = 460
  const prevShowMediaRef = useRef(null)
  const [renderMedia, setRenderMedia] = useState(showMediaCard)
  const [mediaCollapsed, setMediaCollapsed] = useState(false)
  const exitTimerRef = useRef(null)
  const mediaPropsRef = useRef(null)
  if (showMediaCard) {
    // Snapshot every render while the card is supposed to be visible so the
    // exit animation has stable content to display after `track` is cleared.
    mediaPropsRef.current = {
      clientId: homeClientId,
      sourceId: currentSourceId,
      track,
      playback,
      empty: isEmptyMedia,
      groupName: nameMap[homeClientId] || homeClient?.host?.name || homeClientId,
    }
  }
  useLayoutEffect(() => {
    const prev = prevShowMediaRef.current
    prevShowMediaRef.current = showMediaCard
    if (prev === null) {
      setRenderMedia(showMediaCard)
      return
    }
    if (exitTimerRef.current) {
      clearTimeout(exitTimerRef.current)
      exitTimerRef.current = null
    }
    if (showMediaCard && !prev) {
      setRenderMedia(true)
      setMediaCollapsed(true)
      const r1 = requestAnimationFrame(() => {
        requestAnimationFrame(() => setMediaCollapsed(false))
      })
      return () => cancelAnimationFrame(r1)
    }
    if (!showMediaCard && prev) {
      setMediaCollapsed(true)
      exitTimerRef.current = setTimeout(() => {
        setRenderMedia(false)
        setMediaCollapsed(false)
        exitTimerRef.current = null
      }, ANIM_MS)
    }
  }, [showMediaCard])
  useEffect(() => () => {
    if (exitTimerRef.current) clearTimeout(exitTimerRef.current)
  }, [])
  // Anchored trigger sits over the media card; inline only when there's
  // no media card to anchor against (V2).
  // TEMP TEST 2026-05-26: source trigger lives inline next to the first row
  // (All in multi, single device in V3) instead of anchored top-right of
  // the media card. To revert, restore:
  //   const showAnchoredTrigger = showMediaCard
  //   const showInlineTrigger = !showMediaCard
  const showAnchoredTrigger = false
  const showInlineTrigger = true

  // Card itself is never draggable — drag affordance lives on the device
  // name. The slider's pointer-down events would otherwise fight the
  // card's drag start, leaving the slider unusable on touch and mouse
  // alike.

  const handleDragOver = (e) => {
    // Source card is never a drop target — without preventDefault the drop
    // event won't fire and the browser shows the no-drop cursor.
    if (isDragSource) return
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    onDragOverGroup()
  }

  const handleUngroupAll = () => {
    sorted.forEach(c => {
      if (c.id !== homeClientId) onReturnHome(c.id)
    })
  }

  const handleConfigure = () => onOpenDevice(homeClientId)

  const inlineTrigger = showInlineTrigger ? (
    <SourceTrigger
      sources={group.sources || []}
      currentSourceId={currentSourceId}
      isMulti={isMulti}
      groupId={group.id}
      homeClientId={homeClientId}
      onSwitchSource={onSwitchSource}
      onUngroupAll={handleUngroupAll}
      onConfigure={handleConfigure}
    />
  ) : null

  const anchoredTrigger = showAnchoredTrigger ? (
    <SourceTrigger
      sources={group.sources || []}
      currentSourceId={currentSourceId}
      isMulti={isMulti}
      groupId={group.id}
      homeClientId={homeClientId}
      onSwitchSource={onSwitchSource}
      onUngroupAll={handleUngroupAll}
      onConfigure={handleConfigure}
      anchored
    />
  ) : null

  // Drop zone: single cards keep the whole outer card as the target (the
  // card body is the device portion). Multi cards constrain the drop zone
  // to the inner `.fx-group-rows` sub-card so the album-art region isn't
  // treated as a valid drop target. fx-drop outline follows the same
  // placement so the indicator hugs the actual drop area.
  const dropHandlers = {
    onDragOver: handleDragOver,
    onDragLeave: onDragLeaveGroup,
    onDrop: (e) => { e.preventDefault(); onDropOnGroup() },
  }
  const cardDropHandlers = isMulti ? {} : dropHandlers
  const rowsDropHandlers = isMulti ? dropHandlers : {}
  const cardDropClass = !isMulti && isDragTarget ? ' fx-drop' : ''
  const rowsDropClass = isMulti && isDragTarget ? ' fx-drop' : ''

  return (
    <div className="fx-group-row-v2-wrap" data-group-card-id={group.home_client_id || group.id}>
      <div
        ref={cardRef}
        className={`fx-group-card-v2 fx-card-hover ${variant}${isSingleNoMedia ? ' v2-single' : ''}${isEmptyMedia ? ' v4-empty' : ''}${cardDropClass}${isDraggedSingleCard ? ' is-drag-placeholder' : ''}`}
        data-has-media={hasMedia ? 'true' : 'false'}
        style={artStyle}
        {...cardDropHandlers}
        onDoubleClick={(e) => {
          // Quick path to settings: double-click name area opens device panel
          if (e.target.closest('.fx-group-row-name')) {
            onOpenDevice(homeClientId)
          }
        }}
      >
        {renderMedia && mediaPropsRef.current && (
          <div className={`fx-media-reveal${mediaCollapsed ? ' is-entering' : ''}`}>
            <div className="fx-media-reveal-inner">
              <MediaCard {...mediaPropsRef.current} />
            </div>
          </div>
        )}
        {anchoredTrigger}
        <div className={`fx-group-rows${rowsDropClass}`} {...rowsDropHandlers}>
          {isMulti && (
            <AllRow
              clients={sorted}
              mqtt={mqtt}
              homeClientId={homeClientId}
              onReturnHome={onReturnHome}
              inlineSourceTrigger={inlineTrigger}
            />
          )}
          {sorted.map(c => (
            <DeviceRow
              key={c.id}
              client={c}
              isHome={c.id === homeClientId}
              isMulti={isMulti}
              isOnly={!isMulti}
              isAirplayHome={isAirplayHome}
              hasMedia={hasMedia}
              nameMap={nameMap}
              mqtt={mqtt}
              onReturnHome={onReturnHome}
              onDragStart={onDragStart}
              onDragEnd={onDragEnd}
              inlineSourceTrigger={!isMulti && c.id === homeClientId ? inlineTrigger : null}
              isDragPlaceholder={isMulti && c.id === placeholderClientId}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
