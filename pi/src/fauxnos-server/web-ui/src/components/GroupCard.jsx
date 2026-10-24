import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
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
  IconCheckFilled,
  IconChevronDown,
  IconAdjustmentsHorizontal,
  IconPower,
} from '@tabler/icons-react'

/* Drag-grip glyph — two short vertical bars. This is the original handle the
   group cards shipped with (restored per preference over the dotted grip). */
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
import CustomIcon from './CustomIcon'
import AddDevicesPopover from './AddDevicesPopover'
import useAlbumArtColor from '../hooks/useAlbumArtColor'
import { useTuning } from '../hooks/useTuning'
import { useTheme } from '../hooks/useTheme'
import { useSliderHover } from '../hooks/useSliderHover'
import { buildArtTokens } from '../lib/artTokens'
import { homeIdOf, sourceIdOf } from '../lib/nowPlaying'
import { noiseArtUrl } from '../lib/noiseArt'
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
function SourceIcon({ sourceId, icon, size = 24 }) {
  // A custom per-source icon (set in the source editor) wins over the semantic
  // per-id fallback glyph, so a renamed source (e.g. analog → "Turntable")
  // shows its chosen icon on the card, matching the source picker. FX-69.
  if (icon) return <CustomIcon name={icon} size={size} />
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
    '.fx-source-trigger, .fx-name-action-btn, .fx-group-row-name-subtitle'
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

/* Anything inside a drag host that owns its own pointer gesture — the volume
   control, the source trigger, the ungroup button, the add-devices chevron
   button, and any raw button/input/anchor/slider. A pointerdown landing on one
   of these must NOT arm the native device drag, so the slider (and every other
   control) gets a clean, uninterrupted gesture. The same selector gates
   dragstart as a belt-and-suspenders guard.
   The device title is deliberately NOT here — it's part of the drag area; its
   only interactive child (the chevron button) opts out via the `button` rule. */
const DRAG_OPT_OUT =
  '.fx-group-row-volume, .fx-source-trigger, ' +
  '.fx-group-progress, .fx-noise-controls, button, input, a, [role="slider"]'

/* Arm/disarm the native drag on the pointerdown that precedes it. Setting
   `draggable` synchronously here — before the browser's mousemove drag
   heuristic runs — is what guarantees a press on the slider can never be
   hijacked into a device drag (the #1 complaint). On whitespace we arm it;
   on any control we disarm it for this gesture. Each pointerdown recomputes,
   so state never gets stuck.

   Mweb (≤600px) twist (FX-42, first cut — interaction TBD): there are no drag
   handles on small screens, so a stray swipe over a card's whitespace would
   otherwise start a drag instead of scrolling. We gate the arm behind a short
   press-and-hold: draggable stays false until the pointer has been held ~280ms
   without moving past a small threshold; any earlier move (a scroll) or release
   cancels it. Desktop keeps the instant synchronous arm. */
const DRAG_HOLD_MS = 280
const DRAG_HOLD_SLOP = 8

function armDragOnPointerDown(hostEl, enabled, e) {
  if (!hostEl) return
  const wantDrag = enabled && !e.target.closest(DRAG_OPT_OUT)
  const isMweb = window.matchMedia('(max-width: 600px)').matches
  if (!isMweb) {
    hostEl.draggable = wantDrag
    return
  }
  // Mweb: disarm immediately, then arm after the hold elapses.
  hostEl.draggable = false
  if (!wantDrag) return
  const startX = e.clientX
  const startY = e.clientY
  const cleanup = () => {
    clearTimeout(timer)
    window.removeEventListener('pointermove', onMove, true)
    window.removeEventListener('pointerup', cleanup, true)
    window.removeEventListener('pointercancel', cleanup, true)
  }
  const onMove = (ev) => {
    if (Math.hypot(ev.clientX - startX, ev.clientY - startY) < DRAG_HOLD_SLOP) return
    hostEl.draggable = false
    cleanup()
  }
  const timer = setTimeout(() => {
    hostEl.draggable = true
    cleanup()
  }, DRAG_HOLD_MS)
  window.addEventListener('pointermove', onMove, true)
  window.addEventListener('pointerup', cleanup, true)
  window.addEventListener('pointercancel', cleanup, true)
}

/* Shared dragstart for both drag hosts (the whole card for single-device
   groups, an individual member row for multi-room). Builds the V2-pill ghost
   from the row element and mirrors the grab point onto it, clamped so a grab
   started up in the media region still lands the ghost under the cursor. */
function startDeviceDrag(e, { clientId, hostEl, rowEl, onDragStart }) {
  if (e.target.closest(DRAG_OPT_OUT)) {
    e.preventDefault()
    return
  }
  e.dataTransfer.setData('text/plain', clientId)
  e.dataTransfer.effectAllowed = 'move'
  const card = hostEl?.closest('.fx-group-card-v2') || hostEl
  const row = rowEl || card?.querySelector('.fx-group-row-v2')
  if (row && card) {
    const rowRect = row.getBoundingClientRect()
    const cardRect = card.getBoundingClientRect()
    const ghost = buildDeviceDragGhost(row, cardRect)
    if (ghost) {
      // .v2-single .fx-group-rows pads 16/24/16/32 — the cloned row sits at
      // that offset from the ghost's top-left. Mirror the user's grab point
      // within the row into the same point on the ghost; clamp so a grab from
      // the media region (above the row) still pins the ghost to the cursor.
      const SHELL_PAD_LEFT = 32
      const SHELL_PAD_TOP = 16
      const GHOST_H = 74
      const offsetX = Math.min(Math.max((e.clientX - rowRect.left) + SHELL_PAD_LEFT, 0), cardRect.width)
      const offsetY = Math.min(Math.max((e.clientY - rowRect.top) + SHELL_PAD_TOP, 0), GHOST_H)
      e.dataTransfer.setDragImage(ghost, offsetX, offsetY)
    }
  }
  onDragStart(clientId)
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
 * a SourcePopover listing every available source with the active one checked.
 * On a multi-room card the same full list is shown, but selecting a source
 * ungroups all members first, then switches (see handleSelect). Anchored
 * top-right of the outer card for V1/V3, inline in the row for V2/V4.
 * ────────────────────────────────────────────────────────────────────────── */
function SourceTrigger({ sources, currentSourceId, isMulti, groupId, homeClientId, onSwitchSource, onUngroupAll, onConfigure, anchored = false }) {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef(null)
  // Active source object so the trigger glyph + a11y label reflect a custom
  // icon/label (e.g. a renamed analog), not just the raw id. FX-69.
  const activeSource = (sources || []).find(s => s.id === currentSourceId)
  const activeLabel = activeSource?.label || currentSourceId

  const handleSelect = async (sourceId) => {
    // On a multi-device card, picking any source dissolves the group first
    // (members return to their own home groups), then the chosen source is
    // switched on the home device. The popover caption warns about this.
    //
    // The ungroup MUST complete before the switch fires: the server-side
    // /api/groups/source has a ratchet that 409-rejects any non-spotify
    // source while the group still has >1 connected client (only Spotify is
    // multiroom-capable). Since the entire point of this flow is picking a
    // non-spotify source, firing them concurrently means the switch lands
    // while snapcast still shows the group intact → rejected, and the source
    // never changes even though the group dissolves. Awaiting the ungroup
    // lets snapcast settle (home alone on the original group id) so the
    // ratchet passes and Group.SetStream targets the right group (FX-50).
    setOpen(false)
    if (isMulti) await onUngroupAll()
    onSwitchSource(groupId, homeClientId, sourceId)
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
        aria-label={activeLabel ? `Source: ${activeLabel}` : 'Select source'}
        title={activeLabel || 'Select source'}
      >
        <SourceIcon sourceId={currentSourceId} icon={activeSource?.icon} size={24} />
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
          onConfigure={onConfigure}
        />
      )}
    </>
  )
}

/* ─────────────────────────────────────────────────────────────────────────────
 * HoverTip — a small label that floats above an anchor element on hover.
 * Portaled to document.body so the group card's overflow:hidden never clips
 * it. Replaces the old inline slide-in labels on the row action buttons.
 * ────────────────────────────────────────────────────────────────────────── */
function HoverTip({ anchorRef, label, visible }) {
  const [pos, setPos] = useState(null)
  useLayoutEffect(() => {
    if (!visible) return
    const el = anchorRef?.current
    if (!el) return
    const r = el.getBoundingClientRect()
    // Anchor the tip's bottom-center to the button's top-center; the CSS
    // transform lifts it fully above and centers it horizontally.
    setPos({ left: r.left + r.width / 2, top: r.top - 8 })
  }, [visible, anchorRef])
  if (!visible || !pos) return null
  return createPortal(
    <span className="fx-icon-tip" style={{ left: pos.left, top: pos.top }}>{label}</span>,
    document.body,
  )
}

/* IconTipButton — circular icon button with a portaled hover label. Used for
 * the ungroup / ungroup-all affordances (the add button manages its own
 * hover state since it also drives a popover). */
function IconTipButton({ label, className, onClick, children, ...rest }) {
  const ref = useRef(null)
  const [hover, setHover] = useState(false)
  return (
    <>
      <button
        ref={ref}
        type="button"
        className={className}
        onClick={onClick}
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
        {...rest}
      >
        {children}
      </button>
      <HoverTip anchorRef={ref} label={label} visible={hover} />
    </>
  )
}

/* ─────────────────────────────────────────────────────────────────────────────
 * RowName — the device/group title in a row. The label itself is part of the
 * drag area (it carries the grab cursor and starts a device drag, same as the
 * rest of the row/card). A single action button sits next to the label, sharing
 * one 36×36 treatment (`.fx-name-action-btn`, matching what was the ungroup
 * icon): the "All" row + single-device cards get the add-to-group disclosure
 * chevron (`addDevices`); multi-room member rows get the ungroup button
 * (`ungroup`). Both opt out of the drag via the `button` rule in DRAG_OPT_OUT,
 * so dragging the title never fights the action click. They reveal together on
 * card hover (see the CSS), so hovering anywhere over the card shows them all.
 * ────────────────────────────────────────────────────────────────────────── */
function RowName({ label, addDevices, ungroup }) {
  const [open, setOpen] = useState(false)
  const btnRef = useRef(null)
  const clickable = !!addDevices
  return (
    <div className={`fx-group-row-name${clickable ? ' has-add' : ''}${open ? ' open' : ''}`}>
      <span className="fx-name-device fx-group-row-name-label">{label}</span>
      {clickable ? (
        <button
          ref={btnRef}
          type="button"
          className={`fx-name-action-btn${open ? ' open' : ''}`}
          onClick={() => setOpen(o => !o)}
          aria-haspopup="menu"
          aria-expanded={open}
          aria-label="Add devices to group"
        >
          <IconChevronDownFilled className="fx-name-chevron" size={24} aria-hidden />
        </button>
      ) : ungroup ? (
        <button
          type="button"
          className="fx-name-action-btn"
          onClick={ungroup}
          aria-label="Ungroup"
        >
          <IconUnlink size={20} />
        </button>
      ) : null}
      {clickable && open && (
        <AddDevicesPopover
          devices={addDevices.devices}
          homeClientId={addDevices.homeClientId}
          memberIds={addDevices.memberIds}
          isGroup={addDevices.isGroup}
          anchorRef={btnRef}
          onClose={() => setOpen(false)}
          onConfirm={addDevices.onConfirm}
        />
      )}
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────────────
 * EditGroupButton — full-width pill pinned to the bottom of the rows sub-card.
 * It's the touch-first entry point to the group-membership editor: on mweb
 * (≤600px) the hover-revealed name chevrons aren't discoverable, so this button
 * opens the same AddDevicesPopover explicitly. Hidden on desktop via CSS (the
 * hover affordances cover that case); always visible on multi-room cards at
 * mweb. Mirrors RowName's clickable branch — own open state, anchors the
 * popover to itself.
 * ────────────────────────────────────────────────────────────────────────── */
function EditGroupButton({ addDevices }) {
  const [open, setOpen] = useState(false)
  const btnRef = useRef(null)
  if (!addDevices) return null
  return (
    <>
      <button
        ref={btnRef}
        type="button"
        className={`fx-edit-group-btn${open ? ' open' : ''}`}
        onClick={() => setOpen(o => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <span>Edit group</span>
        <IconChevronDownFilled className="fx-edit-group-chevron" size={20} aria-hidden />
      </button>
      {open && (
        <AddDevicesPopover
          devices={addDevices.devices}
          homeClientId={addDevices.homeClientId}
          memberIds={addDevices.memberIds}
          isGroup={addDevices.isGroup}
          anchorRef={btnRef}
          onClose={() => setOpen(false)}
          onConfirm={addDevices.onConfirm}
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
function MediaCard({ clientId, sourceId, source, track, playback, empty = false, groupName }) {
  if (empty) {
    return (
      <div className="fx-group-media-card is-empty">
        <div className="fx-group-media-art is-empty" aria-hidden>
          <IconBrandSpotifyFilled size={72} stroke={0} />
        </div>
        <div className="fx-group-media-body">
          <span className="fx-media-empty-cta">
            Connect to <strong className="fx-media-empty-name">{groupName}</strong> in Spotify to begin
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
  // No track metadata (non-Spotify source): show the source's custom label
  // (e.g. "Turntable") rather than the raw id. FX-69.
  const titleText = hasMeta ? track.title : (source?.label || sourceId || '—')
  const subText = hasMeta ? [track.artist, track.album].filter(Boolean).join(' · ') : ''
  const progressHover = useSliderHover()

  return (
    <div className="fx-group-media-card">
      <div className="fx-group-media-art">
        {hasMeta && track.art_url
          ? <img src={track.art_url} alt="" loading="lazy" draggable={false} />
          : <SourceIcon sourceId={sourceId} icon={source?.icon} size={56} />}
      </div>
      {/* Desktop keeps the body wrapper (art | body[text, progress]) exactly as
          before. On mweb (≤600px) index.css sets the body to display:contents so
          text + progress lift into the media card's grid and reflow via named
          areas — art+title on top, progress full-width below — without changing
          the desktop layout. */}
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
 * NoiseMediaCard — the media card while a room plays Noise. Generated art
 * (lib/noiseArt) stands in for a cover, so the card tint and page backdrop
 * work as they do for Spotify. The title opens the colour menu; under it,
 * Tune opens the band graph (low/high cuts) in a popover. Power sits on the
 * right, in line with the rows' source icons. Settings live on the device
 * (NoiseSettings, status/clients/<id>/noise). Every change restarts the
 * generator for about a second, so the graph sends on release.
 * ────────────────────────────────────────────────────────────────────────── */
const NOISE_COLORS = ['white', 'pink', 'brown']
const capitalize = (s) => s[0].toUpperCase() + s.slice(1)

// Band graph: log frequency axis, 20 Hz–20 kHz. Each cut has its own range;
// dragging past the end of it turns that cut off.
const F_MIN = 20, F_MAX = 20000
const LOW_CUT = { min: 20, max: 2000 }
const HIGH_CUT = { min: 200, max: 20000 }
const G = { w: 320, h: 88, padX: 8, top: 10, floorDb: 30 }
const fToX = (f) => G.padX + (Math.log10(f / F_MIN) / 3) * (G.w - 2 * G.padX)
const xToF = (x) => F_MIN * Math.pow(10, (3 * (x - G.padX)) / (G.w - 2 * G.padX))
// 2-pole Butterworth magnitude in dB — the same filters sox applies.
const responseDb = (f, low, high) => {
  let db = 0
  if (low) db += 10 * Math.log10(Math.pow(f / low, 4) / (1 + Math.pow(f / low, 4)))
  if (high) db -= 10 * Math.log10(1 + Math.pow(f / high, 4))
  return db
}
const dbToY = (db) => G.top + (Math.min(G.floorDb, -db) / G.floorDb) * (G.h - G.top)
const roundHz = (hz) => {
  const step = hz < 100 ? 5 : hz < 1000 ? 10 : 100
  return Math.round(hz / step) * step
}
const fmtHz = (hz) => (!hz ? 'Off' : hz >= 1000 ? `${(hz / 1000).toFixed(1)} kHz` : `${hz} Hz`)

// Clamp a dragged cut into its range, keep the band at least ~half an
// octave wide, and turn the cut off when dragged past the outer end.
function clampCut(which, hz, other) {
  if (which === 'low') {
    if (hz < LOW_CUT.min * 1.1) return 0
    const max = Math.min(LOW_CUT.max, other ? other / 1.5 : Infinity)
    return roundHz(Math.min(hz, max))
  }
  if (hz > HIGH_CUT.max / 1.1) return 0
  const min = Math.max(HIGH_CUT.min, other ? other * 1.5 : 0)
  return roundHz(Math.max(hz, min))
}

function NoiseBandGraph({ lowCut, highCut, onCommit }) {
  const svgRef = useRef(null)
  // Draft values while dragging/keying; the device only hears the commit.
  const [draft, setDraft] = useState(null)
  const dragRef = useRef(null)
  const low = draft ? draft.low : lowCut
  const high = draft ? draft.high : highCut

  const points = []
  for (let i = 0; i <= 96; i++) {
    const f = F_MIN * Math.pow(10, (3 * i) / 96)
    points.push(`${fToX(f).toFixed(1)},${dbToY(responseDb(f, low, high)).toFixed(1)}`)
  }
  const line = `M${points.join(' L')}`
  const area = `${line} L${fToX(F_MAX)},${G.h} L${fToX(F_MIN)},${G.h} Z`
  const handleX = { low: fToX(low || F_MIN), high: fToX(high || F_MAX) }
  const handleY = { low: dbToY(low ? -3 : 0), high: dbToY(high ? -3 : 0) }

  const toSvgX = (clientX) => {
    const r = svgRef.current.getBoundingClientRect()
    return ((clientX - r.left) / r.width) * G.w
  }
  const update = (which, hz, base) => {
    const next = { ...base }
    next[which] = clampCut(which, hz, which === 'low' ? base.high : base.low)
    setDraft(next)
    return next
  }
  const commit = (next) => {
    setDraft(null)
    const changes = {}
    if (next.low !== (lowCut || 0)) changes.low_cut = next.low
    if (next.high !== (highCut || 0)) changes.high_cut = next.high
    if (Object.keys(changes).length) onCommit(changes)
  }

  const onPointerDown = (e) => {
    const x = toSvgX(e.clientX)
    // Grab whichever edge is nearer; the band middle splits the two.
    const which = Math.abs(x - handleX.low) <= Math.abs(x - handleX.high) ? 'low' : 'high'
    dragRef.current = { which, base: { low: lowCut || 0, high: highCut || 0 } }
    e.currentTarget.setPointerCapture(e.pointerId)
    dragRef.current.last = update(which, xToF(x), dragRef.current.base)
  }
  const onPointerMove = (e) => {
    const d = dragRef.current
    if (!d) return
    d.last = update(d.which, xToF(toSvgX(e.clientX)), d.base)
  }
  const onPointerUp = () => {
    const d = dragRef.current
    dragRef.current = null
    if (d?.last) commit(d.last)
  }
  // Arrow keys move a focused edge by a sixth of an octave.
  const onKeyDown = (which) => (e) => {
    const dir = e.key === 'ArrowRight' || e.key === 'ArrowUp' ? 1
      : e.key === 'ArrowLeft' || e.key === 'ArrowDown' ? -1 : 0
    if (!dir) return
    e.preventDefault()
    const base = draft || { low: lowCut || 0, high: highCut || 0 }
    const cur = base[which] || (which === 'low' ? LOW_CUT.min : HIGH_CUT.max)
    update(which, cur * Math.pow(2, dir / 6), base)
  }
  const onKeyUp = () => draft && commit(draft)

  return (
    <div className="fx-noise-controls">
      <svg
        ref={svgRef}
        className="fx-noise-graph"
        viewBox={`0 0 ${G.w} ${G.h}`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        {[100, 1000, 10000].map(f => (
          <line key={f} className="fx-noise-graph-grid" x1={fToX(f)} x2={fToX(f)} y1={G.top} y2={G.h} />
        ))}
        <path className="fx-noise-graph-area" d={area} />
        <path className="fx-noise-graph-line" d={line} />
        {['low', 'high'].map(which => (
          <circle
            key={which}
            className="fx-noise-graph-handle"
            cx={handleX[which]}
            cy={handleY[which]}
            r={5}
            tabIndex={0}
            role="slider"
            aria-label={which === 'low' ? 'Low cut' : 'High cut'}
            aria-valuetext={fmtHz(which === 'low' ? low : high)}
            onKeyDown={onKeyDown(which)}
            onKeyUp={onKeyUp}
          />
        ))}
      </svg>
      <div className="fx-noise-graph-labels">
        <span>Low cut {fmtHz(low)}</span>
        <span>High cut {fmtHz(high)}</span>
      </div>
    </div>
  )
}

// Popover portaled to <body> (the card clips overflow), hung below its
// anchor. It copies the card's --art-* tokens so it matches the card's tint.
function NoisePopover({ anchorRef, onClose, className = '', role, children }) {
  const ref = useRef(null)
  const [style, setStyle] = useState(null)
  useEffect(() => {
    const place = () => {
      const el = anchorRef.current
      if (!el) return
      const r = el.getBoundingClientRect()
      const cs = getComputedStyle(el)
      const tokens = {}
      for (const t of ['--art-accent', '--art-accent-soft']) {
        const v = cs.getPropertyValue(t).trim()
        if (v) tokens[t] = v
      }
      // Hang from whichever side keeps it on screen.
      const side = r.left > window.innerWidth / 2
        ? { right: Math.max(8, window.innerWidth - r.right), left: 'auto' }
        : { left: r.left, right: 'auto' }
      setStyle({ top: r.bottom + 8, ...side, ...tokens })
    }
    place()
    const onDown = (e) => {
      if (ref.current?.contains(e.target) || anchorRef.current?.contains(e.target)) return
      onClose()
    }
    document.addEventListener('mousedown', onDown)
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => {
      document.removeEventListener('mousedown', onDown)
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
    }
  }, [anchorRef, onClose])
  if (!style) return null
  return createPortal(
    <div ref={ref} className={`fx-popover fx-source-popover ${className}`} role={role} style={style}>
      {children}
    </div>,
    document.body,
  )
}

function NoiseMediaCard({ noise, onNoiseChange }) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [tuneOpen, setTuneOpen] = useState(false)
  const titleRef = useRef(null)
  const tuneRef = useRef(null)
  const closeMenu = useCallback(() => setMenuOpen(false), [])
  const closeTune = useCallback(() => setTuneOpen(false), [])
  const color = noise?.color || 'brown'
  const isOn = noise?.on !== false
  const label = `${capitalize(color)} noise`
  return (
    <div className={`fx-group-media-card fx-noise-card${isOn ? '' : ' is-off'}`}>
      <div className="fx-group-media-art">
        <img src={noiseArtUrl(color)} alt="" draggable={false} />
      </div>
      <div className="fx-group-media-body">
        <div className="fx-group-media-text fx-noise-head">
          <div className="fx-noise-title">
            <button
              ref={titleRef}
              type="button"
              className="fx-noise-title-btn"
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen(o => !o)}
            >
              <span className="fx-title-track" title={label}>{label}</span>
              <IconChevronDown className="fx-noise-title-chevron" size={22} aria-hidden />
            </button>
            <div className="fx-noise-status">
              <button
                ref={tuneRef}
                type="button"
                className="fx-meta-track fx-noise-text-btn"
                aria-haspopup="dialog"
                aria-expanded={tuneOpen}
                onClick={() => setTuneOpen(o => !o)}
              >
                <IconAdjustmentsHorizontal size={18} aria-hidden />
                Tune
              </button>
            </div>
          </div>
          <button
            type="button"
            className={`fx-icon-btn fx-noise-power${isOn ? ' is-on' : ''}`}
            aria-label={isOn ? 'Turn noise off' : 'Turn noise on'}
            aria-pressed={isOn}
            title={isOn ? 'Turn off' : 'Turn on'}
            onClick={() => onNoiseChange({ on: !isOn })}
          >
            <IconPower size={20} />
          </button>
        </div>
      </div>
      {menuOpen && (
        <NoisePopover anchorRef={titleRef} onClose={closeMenu} role="menu">
          {NOISE_COLORS.map(c => (
            <button
              key={c}
              type="button"
              role="menuitemradio"
              aria-checked={color === c}
              className={`fx-source-popover-row${color === c ? ' active' : ''}`}
              onClick={() => { setMenuOpen(false); if (c !== color) onNoiseChange({ color: c }) }}
            >
              <span className="fx-source-popover-row-icon">
                <img className="fx-noise-swatch" src={noiseArtUrl(c)} alt="" />
              </span>
              <span className="fx-source-popover-row-label">{capitalize(c)}</span>
              {color === c && (
                <span className="fx-source-popover-row-check" aria-hidden>
                  <IconCheckFilled size={24} />
                </span>
              )}
            </button>
          ))}
        </NoisePopover>
      )}
      {tuneOpen && (
        <NoisePopover anchorRef={tuneRef} onClose={closeTune} role="dialog" className="fx-noise-tune-popover">
          <NoiseBandGraph
            lowCut={noise?.low_cut || 0}
            highCut={noise?.high_cut || 0}
            onCommit={onNoiseChange}
          />
        </NoisePopover>
      )}
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
function AllRow({ clients, mqtt, addDevices, sourceTrigger }) {
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
    <div className="fx-group-row-v2 is-all with-source">
      <RowName label="All" addDevices={addDevices} />
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
      {sourceTrigger}
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
  inlineSourceTrigger, isDragPlaceholder, addDevices,
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

  // Per-row dragging only applies to multi-room *member* rows ("move me to
  // another group"). The multi-room home row isn't draggable (dragging home
  // would disband the group — users ungroup-all by picking a source in the
  // source menu, which dissolves the group as a side effect), and
  // single-device cards now drag from the whole card (see GroupCard), not the
  // inner row, so the grab area runs edge-to-edge. Interactive children opt
  // out via DRAG_OPT_OUT in both the pointerdown arm and the dragstart guard.
  const isRowDraggable = isMulti && !isHome
  // The grip handle is a hover-revealed affordance advertising "you can drag
  // this." It shows on every draggable device row (multi-room members) and on
  // single-device rows (where the whole card is the drag host). It's a DOM
  // child of the drag host, so grabbing it starts the drag naturally; it's
  // deliberately NOT in DRAG_OPT_OUT.
  const showDragHandle = !isMulti || !isHome
  const handleRowPointerDown = (e) => armDragOnPointerDown(rowRef.current, isRowDraggable, e)
  const handleRowDragStart = (e) =>
    startDeviceDrag(e, { clientId: client.id, rowEl: rowRef.current, onDragStart })
  const handleRowDragEnd = (e) => {
    cleanupDeviceDragGhost()
    onDragEnd?.(e)
  }

  return (
    <div
      ref={rowRef}
      className={`fx-group-row-v2${isMulti ? ' with-source no-trailing' : inlineSourceTrigger ? ' with-source' : ''}${isRowDraggable ? ' draggable' : ''}${isDragPlaceholder ? ' is-drag-placeholder' : ''}`}
      draggable={isRowDraggable}
      onPointerDown={isRowDraggable ? handleRowPointerDown : undefined}
      onDragStart={isRowDraggable ? handleRowDragStart : undefined}
      onDragEnd={isRowDraggable ? handleRowDragEnd : undefined}
    >
      {showDragHandle && (
        <span className="fx-drag-grip" aria-hidden>
          <DragBarsIcon size={10} />
        </span>
      )}
      <RowName
        label={name}
        addDevices={addDevices}
        ungroup={isMulti && !isHome ? () => onReturnHome(client.id) : undefined}
      />
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
      {/* Trailing column (right of the slider): single-device cards keep the
          source-trigger here. Multi-room rows have no trailing control — the
          ungroup affordance now lives next to the name (see RowName.ungroup) —
          so they drop the 68px track (`no-trailing`) and the slider runs to the
          card's right edge. */}
      {!isMulti ? inlineSourceTrigger : null}
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
  group, nameMap, mqtt, clients,
  isDragTarget, isDragging, dragClientId, placeholderClientId,
  onDragStart, onDragEnd,
  onDragOverGroup, onDragLeaveGroup, onDropOnGroup,
  onReturnHome, onUngroupAll, onSwitchSource, onOpenDevice, onAddDevices,
  isExpanded = false, onToggleExpand,
  appear = false, appearDelayMs = 0,
}) {
  const isMulti = group.clients.length > 1
  const homeClientId = homeIdOf(group)
  const cardRef = useRef(null)

  // The mweb "Edit group" pill is revealed by tapping the card body; only one
  // card is expanded at a time (state lives in GroupsTab, passed as isExpanded /
  // onToggleExpand) so tapping one card collapses any other. Desktop keeps the
  // hover-chevron path, so the pill is CSS-hidden there regardless. (FX-42)

  // Mweb press feedback: the whole card springs down a touch on press. Driven by
  // pointerdown (not CSS :active, which mobile browsers suppress the moment a
  // scroll starts) so the feedback fires on touch-down and — crucially — stays
  // pressed *while scrolling*. We deliberately do NOT release on pointercancel
  // (the browser fires that the instant it claims the gesture for scrolling,
  // which would pop the card back immediately); instead we hold until the finger
  // actually lifts (touchend/pointerup). Presses on a control are ignored so
  // adjusting volume / tapping a button doesn't scale the card. (FX-42)
  const [pressed, setPressed] = useState(false)
  const handleCardPress = (e) => {
    if (!window.matchMedia('(max-width: 600px)').matches) return
    if (e.target.closest(
      'button, input, a, [role="slider"], .fx-group-row-volume, .fx-group-progress, .fx-noise-controls, .fx-source-trigger, .fx-edit-group-btn'
    )) return
    setPressed(true)
    const release = () => {
      setPressed(false)
      window.removeEventListener('pointerup', release, true)
      window.removeEventListener('touchend', release, true)
      window.removeEventListener('touchcancel', release, true)
    }
    window.addEventListener('pointerup', release, true)
    window.addEventListener('touchend', release, true)
    window.addEventListener('touchcancel', release, true)
  }

  const sorted = [...group.clients].sort((a, b) => {
    if (a.id === homeClientId) return -1
    if (b.id === homeClientId) return 1
    return 0
  })
  const homeClient = sorted.find(c => c.id === homeClientId) || sorted[0]
  const track = mqtt.tracks[homeClientId]
  const playback = mqtt.playback[homeClientId]

  // The now-playing media surface (album art, track meta, transport, progress)
  // is Spotify-only: go-librespot is the sole source that publishes track
  // metadata and drives the transport endpoint. Other sources (AirPlay, Vinyl,
  // Analog, custom) have no transport, and a stale Spotify track lingers in
  // mqtt.tracks after switching away — so gate the media surface on Spotify
  // mode and let other sources fall back to the plain device-row layout.
  // Noise is the exception: it has no track, but its media card carries the
  // noise colour + cut controls (NoiseMediaCard).
  const currentSourceId = sourceIdOf(group, mqtt, homeClientId)
  const isSpotify = currentSourceId === 'spotify'
  const isNoise = currentSourceId === 'noise'
  const hasTrack = isSpotify && !!track && (track.title || track.artist)
  const hasMedia = hasTrack || isNoise
  const isAirplayHome = mqtt.modes[homeClient?.id] === 'airplay'

  // Extract album-art dominant color and project it onto the card's --art-*
  // tokens. Hook is a no-op when art_url is missing or extraction fails.
  // Noise has no cover, so its generated art (lib/noiseArt) stands in.
  const noiseColor = mqtt.noise?.[homeClientId]?.color
  const artColor = useAlbumArtColor(
    hasTrack ? track?.art_url : isNoise ? noiseArtUrl(noiseColor) : null
  )
  const { effective } = useTheme()
  const tuning = useTuning()
  const artStyle = artColor ? buildArtTokens(artColor, effective === 'dark', tuning) : undefined

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
      source: (group.sources || []).find(s => s.id === currentSourceId),
      track: isNoise ? null : track,
      playback,
      noise: mqtt.noise?.[homeClientId],
      onNoiseChange: (changes) => mqtt.publishNoise?.(homeClientId, changes),
      empty: isEmptyMedia,
      groupName: nameMap[homeClientId] || homeClient?.host?.name || homeClientId,
    }
  }
  useLayoutEffect(() => {
    const prev = prevShowMediaRef.current
    prevShowMediaRef.current = showMediaCard
    if (prev === null) {
      // First mount. Normally we snap straight to the final state. But during
      // the groups-list reveal (`appear`), a playing card should crop up from
      // the placeholder height as it fades in — so run the same collapse→
      // expand the live V2→V3 path uses, held by the per-card stagger delay so
      // the crop syncs with the wrapper fade (FX-27).
      // First mount snaps straight to the final render state. The groups-list
      // reveal crop (`appear`) is driven by a pure CSS animation on the
      // media-reveal element (see the fx-media-appear className below), NOT a
      // JS timer — a timer here is fragile under StrictMode's mount
      // double-invoke (run → cleanup → run), which cancels the scheduled
      // expand and strands the media region collapsed (FX-27).
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

  // Single-device cards drag from the whole card (edge-to-edge), not the
  // inner row — so the grab area covers the card's padding and (in V3) the
  // media region too. Multi-room cards aren't card-draggable; their member
  // rows carry their own per-row drag. The pointerdown arm disables the
  // native drag the instant a control is pressed, so the slider stays clean.
  const singleDragClientId = !isMulti ? sorted[0]?.id : null
  const cardDraggable = !!singleDragClientId
  const handleCardPointerDown = (e) => armDragOnPointerDown(cardRef.current, cardDraggable, e)
  const handleCardDragStart = (e) =>
    startDeviceDrag(e, { clientId: singleDragClientId, hostEl: cardRef.current, onDragStart })
  const handleCardDragEnd = (e) => {
    cleanupDeviceDragGhost()
    onDragEnd?.(e)
  }

  // Tap-to-reveal the Edit-group pill (mweb). Applies to every card — single
  // and multi-room — so the one-at-a-time selection in GroupsTab governs them
  // uniformly. Ignores taps that land on a control (slider, source trigger, any
  // button/input, the pill itself) or the media transport — those own their own
  // gesture. A drag suppresses the trailing click, so a hold-drag never toggles.
  const handleCardClick = (e) => {
    if (e.target.closest(
      'button, input, a, [role="slider"], .fx-group-row-volume, .fx-group-progress, .fx-noise-controls'
    )) return
    onToggleExpand?.()
  }

  const handleDragOver = (e) => {
    // Source card is never a drop target — without preventDefault the drop
    // event won't fire and the browser shows the no-drop cursor.
    if (isDragSource) return
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    onDragOverGroup()
  }

  // Batched ungroup — hand the full member list to GroupsTab so it can
  // serialize the return-home calls. Looping onReturnHome here would fire
  // concurrent requests that race on the server (see handleUngroupAll there).
  // Returns the promise so callers (SourceTrigger.handleSelect) can await the
  // dissolve before switching source.
  const handleUngroupAll = () =>
    onUngroupAll(sorted.filter(c => c.id !== homeClientId).map(c => c.id))

  const handleConfigure = () => onOpenDevice(homeClientId)

  // The group checklist shows the WHOLE fleet, always — the home device pinned
  // checked+disabled, current members pre-checked (uncheckable to remove). The
  // popover diffs its final selection against the live membership, so a single
  // `onAddDevices(desiredIds, homeClientId)` call covers both add and remove.
  // `clients` is the fleet (keyed by client_id); members are `group.clients`
  // (keyed by id). The chevron hides only when the fleet is a single device
  // (nothing to group). Drives both the "All" row (multi) and the lone row.
  const memberIds = group.clients.map(c => c.id)
  const allDevices = (clients || [])
    .map(c => ({ id: c.client_id, name: nameMap[c.client_id] || c.name || c.client_id }))
    .sort((a, b) => a.name.localeCompare(b.name))
  const addDevices = (onAddDevices && allDevices.length > 1)
    ? {
        devices: allDevices,
        homeClientId,
        memberIds,
        isGroup: isMulti,
        onConfirm: (ids) => onAddDevices(ids, homeClientId),
      }
    : null

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

  // Drop zone: whenever a media player sits above the device row(s) — every
  // multi card (V1/V4) and single cards showing a media player (V3) — constrain
  // the drop zone to the inner `.fx-group-rows` sub-card so the album-art region
  // isn't treated as a drop target and the fx-drop outline hugs only the row(s).
  // Single cards with no media (V2) have nothing below the row, so the whole
  // outer card stays the target. fx-drop placement follows the handlers.
  const scopeDropToRows = isMulti || hasMedia
  const dropHandlers = {
    onDragOver: handleDragOver,
    onDragLeave: onDragLeaveGroup,
    onDrop: (e) => { e.preventDefault(); onDropOnGroup() },
  }
  const cardDropHandlers = scopeDropToRows ? {} : dropHandlers
  const rowsDropHandlers = scopeDropToRows ? dropHandlers : {}
  const cardDropClass = !scopeDropToRows && isDragTarget ? ' fx-drop' : ''
  const rowsDropClass = scopeDropToRows && isDragTarget ? ' fx-drop' : ''

  // Groups-list reveal crop: when a playing card mounts during the reveal, its
  // media region crop-grows in via a pure CSS animation (StrictMode-immune).
  // Suppressed while the JS V2→V3 reveal owns the region (mediaCollapsed), so
  // the two never fight over grid-template-rows.
  const mediaAppear = appear && showMediaCard && !mediaCollapsed

  return (
    <div
      className={`fx-group-row-v2-wrap${appear ? ' fx-appear' : ''}`}
      /* --art-* sits on the wrapper too (the card inherits it) so the gutter
         glow pseudo-element — which lives outside the card's overflow:hidden
         box — can read the accent hue. */
      style={{ ...artStyle, ...(appear ? { '--appear-delay': `${appearDelayMs}ms` } : null) }}
      data-group-card-id={group.home_client_id || group.id}
    >
      <div
        ref={cardRef}
        className={`fx-group-card-v2 fx-card-hover ${variant}${isSingleNoMedia ? ' v2-single' : ''}${isEmptyMedia ? ' v4-empty' : ''}${cardDropClass}${cardDraggable ? ' fx-drag-host' : ''}${isDraggedSingleCard ? ' is-drag-placeholder' : ''}${isExpanded ? ' is-expanded' : ''}${pressed ? ' is-pressed' : ''}`}
        data-has-media={hasMedia ? 'true' : 'false'}
        style={artStyle}
        draggable={cardDraggable}
        onPointerDown={(e) => {
          handleCardPress(e)
          if (cardDraggable) handleCardPointerDown(e)
        }}
        onDragStart={cardDraggable ? handleCardDragStart : undefined}
        onDragEnd={cardDraggable ? handleCardDragEnd : undefined}
        onClick={handleCardClick}
        {...cardDropHandlers}
        onDoubleClick={(e) => {
          // Quick path to settings: double-click name area opens device panel
          if (e.target.closest('.fx-group-row-name')) {
            onOpenDevice(homeClientId)
          }
        }}
      >
        {renderMedia && mediaPropsRef.current && (
          <div
            className={`fx-media-reveal${mediaCollapsed ? ' is-entering' : ''}${mediaAppear ? ' fx-media-appear' : ''}`}
            style={mediaAppear ? { '--appear-delay': `${appearDelayMs}ms` } : undefined}
          >
            <div className="fx-media-reveal-inner">
              {/* Separate components, not a branch inside MediaCard: a room
                  switching Spotify → Noise while the card is open remounts
                  instead of changing MediaCard's hook order. */}
              {mediaPropsRef.current.sourceId === 'noise'
                ? <NoiseMediaCard {...mediaPropsRef.current} />
                : <MediaCard {...mediaPropsRef.current} />}
            </div>
          </div>
        )}
        {anchoredTrigger}
        <div className={`fx-group-rows${rowsDropClass}`} {...rowsDropHandlers}>
          {isMulti && (
            <AllRow
              clients={sorted}
              mqtt={mqtt}
              addDevices={addDevices}
              sourceTrigger={inlineTrigger}
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
              addDevices={!isMulti && c.id === homeClientId ? addDevices : null}
              isDragPlaceholder={isMulti && c.id === placeholderClientId}
            />
          ))}
          {/* Edit-group pill — mweb-only (CSS-gated). Revealed by tapping the
              card (single or multi); only one card is expanded at a time (see
              GroupsTab). The touch-first replacement for the hover chevron that
              opens the membership editor. */}
          {isExpanded && <EditGroupButton addDevices={addDevices} />}
        </div>
      </div>
    </div>
  )
}
