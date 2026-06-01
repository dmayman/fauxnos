import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  IconCheckFilled,
  IconBrandSpotifyFilled,
  IconBuildingBroadcastTowerFilled,
  IconMicrophoneFilled,
  IconExternalLinkFilled,
  IconHeadphonesFilled,
} from '@tabler/icons-react'
import CustomIcon from './CustomIcon'

function SourceIcon({ source, size = 24 }) {
  const id = source?.id
  const FallbackIcon =
    id === 'spotify' ? IconBrandSpotifyFilled :
    id === 'airplay' ? IconBuildingBroadcastTowerFilled :
    id === 'analog'  ? IconMicrophoneFilled :
    id ? IconExternalLinkFilled :
    IconHeadphonesFilled
  if (source?.icon) {
    return <CustomIcon name={source.icon} size={size} />
  }
  return <FallbackIcon size={size} aria-hidden />
}

/**
 * Popover that opens when the SourceTrigger button is clicked.
 *
 * - Anchors below-right of the trigger using its `getBoundingClientRect`.
 * - Rows: icon + label, with a check on the active source.
 * - On a multi-room (grouped) card the same full source list is shown, but a
 *   caption warns that picking any source dissolves the group: the caller
 *   ungroups all members first, then switches the chosen source (FX-50).
 * - Closes on click-outside (excluding the anchor) or after a successful
 *   selection.
 */
export default function SourcePopover({
  sources, currentSourceId, isMulti, anchorRef, onClose, onSelect, onConfigure,
}) {
  const visibleSources = sources || []
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
    window.addEventListener('scroll', place, true)
    return () => {
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
    }
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

  const popover = (
    <div
      className="fx-popover fx-source-popover"
      ref={ref}
      role="menu"
      style={pos ? { top: pos.top, right: pos.right } : undefined}
    >
      {isMulti && (
        <div className="fx-source-popover-hint">Changing source will ungroup all</div>
      )}
      {(!visibleSources || visibleSources.length === 0) && (
        <div className="fx-source-popover-empty">No sources available.</div>
      )}
      {visibleSources.map(s => {
        const isActive = currentSourceId === s.id
        return (
          <button
            key={s.id}
            type="button"
            role="menuitemradio"
            aria-checked={isActive}
            className={`fx-source-popover-row${isActive ? ' active' : ''}`}
            onClick={() => onSelect(s.id)}
            title={s.label || s.id}
          >
            <span className="fx-source-popover-row-icon">
              <SourceIcon source={s} size={24} />
            </span>
            <span className="fx-source-popover-row-label">{s.label || s.id}</span>
            {isActive && (
              <span className="fx-source-popover-row-check" aria-hidden>
                <IconCheckFilled size={24} />
              </span>
            )}
          </button>
        )
      })}
      {onConfigure && (
        <button
          type="button"
          className="fx-source-popover-configure"
          onClick={() => { onConfigure(); onClose() }}
        >
          Configure
        </button>
      )}
    </div>
  )

  return createPortal(popover, document.body)
}
