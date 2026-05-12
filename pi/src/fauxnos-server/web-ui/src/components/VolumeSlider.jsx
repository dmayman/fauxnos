import { useState, useEffect, useRef } from 'react'
import { Volume1, Volume2, VolumeX } from 'lucide-react'

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

  const mqttVol = mqtt?.volumes?.[clientId]
  const displayVol = mqttVol ?? value

  // Snap back to the canonical value once the user lets go — but don't
  // clobber the in-flight drag value (causes jitter when echoes lag).
  useEffect(() => {
    if (!draggingRef.current) setLocalVal(displayVol)
  }, [displayVol])

  const pct = Math.max(0, Math.min(100, localVal))
  const pctStr = `${pct}%`
  const Icon = pct === 0 ? VolumeX : pct < 40 ? Volume1 : Volume2

  if (external) {
    return (
      <div className={`fx-volume fx-volume-external ${variant}`}>
        {!hideIcon && (
          <span className="fx-volume-icon"><Icon size={16} /></span>
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
        <span className="fx-volume-icon"><Icon size={16} /></span>
      )}
      <div className="fx-volume-track">
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
