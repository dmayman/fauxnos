import { useEffect, useRef, useState } from 'react'
import {
  IconCheck,
  IconBrandSpotifyFilled,
  IconBuildingBroadcastTowerFilled,
  IconMicrophoneFilled,
  IconExternalLinkFilled,
  IconHeadphonesFilled,
} from '@tabler/icons-react'

function SourceIcon({ sourceId, size = 24 }) {
  const Icon =
    sourceId === 'spotify' ? IconBrandSpotifyFilled :
    sourceId === 'airplay' ? IconBuildingBroadcastTowerFilled :
    sourceId === 'analog'  ? IconMicrophoneFilled :
    sourceId ? IconExternalLinkFilled :
    IconHeadphonesFilled
  return <Icon size={size} aria-hidden />
}

/**
 * Popover that opens when the SourceTrigger button is clicked.
 *
 * - Anchors below-right of the trigger using its `getBoundingClientRect`.
 * - Rows: icon + label, with a check on the active source. Locked rows
 *   (non-spotify on multi-room groups) render dimmed with a tooltip.
 * - Closes on click-outside (excluding the anchor) or after a successful
 *   selection.
 */
export default function SourcePopover({
  sources, currentSourceId, isMulti, anchorRef, onClose, onSelect,
}) {
  const ref = useRef(null)
  const [pos, setPos] = useState(null)

  useEffect(() => {
    const place = () => {
      const el = anchorRef?.current
      if (!el) return
      const r = el.getBoundingClientRect()
      // Hang from the trigger's bottom-right edge with 8px gap.
      setPos({ top: r.bottom + 8, right: window.innerWidth - r.right })
    }
    place()
    window.addEventListener('resize', place)
    return () => window.removeEventListener('resize', place)
  }, [anchorRef])

  useEffect(() => {
    const handler = (e) => {
      if (ref.current?.contains(e.target)) return
      if (anchorRef?.current?.contains(e.target)) return
      onClose()
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [onClose, anchorRef])

  return (
    <div
      className="fx-popover fx-source-popover"
      ref={ref}
      role="menu"
      style={pos ? { top: pos.top, right: pos.right } : undefined}
    >
      {(!sources || sources.length === 0) && (
        <div className="fx-source-popover-empty">No sources available.</div>
      )}
      {sources.map(s => {
        const isActive = currentSourceId === s.id
        const isLocked = isMulti && s.id !== 'spotify'
        return (
          <button
            key={s.id}
            type="button"
            role="menuitemradio"
            aria-checked={isActive}
            disabled={isLocked}
            className={`fx-source-popover-row${isActive ? ' active' : ''}${isLocked ? ' locked' : ''}`}
            onClick={() => {
              if (isLocked) return
              onSelect(s.id)
            }}
            title={isLocked ? 'Multi-room groups only support Spotify' : (s.label || s.id)}
          >
            <span className="fx-source-popover-row-icon">
              <SourceIcon sourceId={s.id} size={24} />
            </span>
            <span className="fx-source-popover-row-label">{s.label || s.id}</span>
            {isActive && (
              <span className="fx-source-popover-row-check" aria-hidden>
                <IconCheck size={24} stroke={2} />
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}
