import { useState, useEffect, useRef } from 'react'
import { useSliderHover } from '../hooks/useSliderHover'

/**
 * VolumeSlider — custom track-fill slider.
 *
 * Renders a visible filled portion (not just a bare native range), an
 * expanding thumb on hover/drag, and a tabular-num percentage label so
 * width doesn't reflow as the value changes.
 *
 * The native <input type="range"> sits invisibly on top of the visual
 * track so we keep keyboard support + accessibility, while the colored
 * fill + thumb are rendered by us underneath.
 *
 * Variants via className suffix:
 *   - "accent" — fill uses --fx-accent (for the active source's volume)
 *   - "lg"     — taller track (used for group-level slider in multi cards)
 *   - hideIcon — skip the leading speaker glyph (row-level sliders that
 *                already carry a name + status dot)
 *
 * `external` mode: for sources whose volume is owned outside fauxnos
 * (the airplay source — iPhone slider drives shairport's software
 * volume). We render the track shape for visual continuity but hide
 * the fill, thumb, value label, and disable input. The "Volume
 * controlled by iPhone" caption is rendered by the parent card
 * (see GroupCard's .fx-group-name-subtitle) so the slider area
 * height stays invariant across source switches.
 */

// Solid speaker icon — speaker body is filled; waves render as strokes
// (filled crescents read as smudges at 16px). State: 'mute' (X), 'low'
// (1 wave), 'high' (2 waves). The `mute` variant is only used at vol 0.
export function VolumeIcon({ size = 16, state }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path
        d="M11 4.3L6.4 8H4a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.4l4.6 3.7a1 1 0 0 0 1.6-.8V5.1a1 1 0 0 0-1.6-.8z"
        fill="currentColor"
      />
      {state === 'high' && (
        <>
          <path d="M16 9a4 4 0 0 1 0 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          <path d="M19 6a8 8 0 0 1 0 12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </>
      )}
      {state === 'low' && (
        <path d="M16 9a4 4 0 0 1 0 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      )}
      {state === 'mute' && (
        <>
          <path d="M17 9l5 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          <path d="M22 9l-5 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </>
      )}
    </svg>
  )
}

export default function VolumeSlider({
  clientId, value, mqtt,
  variant = '',
  hideIcon = false,
  hideLabel = false,
  ariaLabel,
  external = false,
}) {
  const [localVal, setLocalVal] = useState(value)
  const draggingRef = useRef(false)
  // Restore-on-unmute target. Default to 50 if the user has only ever
  // seen a 0 value. We refresh this whenever a settled (non-drag) echo
  // arrives with a positive volume, so unmute returns to the value the
  // user actually left, not whatever transient value passed through.
  const lastNonZeroRef = useRef(value > 0 ? value : 50)

  const mqttVol = mqtt?.volumes?.[clientId]
  const displayVol = mqttVol ?? value

  // Snap back to the canonical value once the user lets go — but don't
  // clobber the in-flight drag value (causes jitter when echoes lag).
  useEffect(() => {
    if (!draggingRef.current) setLocalVal(displayVol)
  }, [displayVol])

  useEffect(() => {
    if (!draggingRef.current && displayVol > 0) {
      lastNonZeroRef.current = displayVol
    }
  }, [displayVol])

  const pct = Math.max(0, Math.min(100, localVal))
  const pctStr = `${pct}%`
  const iconState = pct === 0 ? 'mute' : pct < 40 ? 'low' : 'high'
  const hover = useSliderHover()

  const toggleMute = () => {
    const next = pct === 0 ? (lastNonZeroRef.current || 50) : 0
    if (pct > 0) lastNonZeroRef.current = pct
    setLocalVal(next)
    mqtt?.publishVolume?.(clientId, next)
  }

  if (external) {
    return (
      <div className={`fx-volume fx-volume-external ${variant}`}>
        {!hideIcon && (
          <span className="fx-volume-icon"><VolumeIcon size={16} state={iconState} /></span>
        )}
        {/* Empty track for shape continuity — no fill, no thumb, no input.
            The ::after pseudo on the parent reserves a 32px right slot
            that keeps the track length matched to the normal slider. */}
        <div className="fx-volume-track" aria-disabled="true" />
      </div>
    )
  }

  return (
    <div className={`fx-volume ${variant}`}>
      {!hideIcon && (
        <button
          type="button"
          className="fx-volume-icon fx-volume-icon-btn"
          onClick={toggleMute}
          aria-label={pct === 0 ? 'Unmute' : 'Mute'}
        >
          <VolumeIcon size={16} state={iconState} />
        </button>
      )}
      <div
        className="fx-volume-track"
        ref={hover.ref}
        onPointerMove={hover.onPointerMove}
        onPointerLeave={hover.onPointerLeave}
      >
        <div className="fx-volume-hover" />
        <div className="fx-volume-fill" style={{ width: pctStr }} />
        <div className="fx-volume-thumb" style={{ left: pctStr }} />
        <input
          className="fx-volume-input"
          type="range"
          min={0}
          max={100}
          value={pct}
          aria-label={ariaLabel || 'Volume'}
          onPointerDown={() => { draggingRef.current = true }}
          onPointerUp={() => { draggingRef.current = false }}
          onInput={(e) => {
            const v = parseInt(e.target.value, 10)
            setLocalVal(v)
            mqtt?.publishVolume?.(clientId, v)
          }}
          onChange={() => {}}
        />
      </div>
      {!hideLabel && (
        <span className="fx-volume-label fx-num">{pct}%</span>
      )}
    </div>
  )
}
