import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  IconCheckFilled,
  IconBrandSpotifyFilled,
  IconBuildingBroadcastTowerFilled,
  IconMicrophoneFilled,
  IconExternalLinkFilled,
  IconHeadphonesFilled,
  IconUnlink,
  IconChevronRight,
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
 * - Rows: icon + label, with a check on the active source. Locked rows
 *   (non-spotify on multi-room groups) render dimmed with a tooltip.
 * - Closes on click-outside (excluding the anchor) or after a successful
 *   selection.
 */
export default function SourcePopover({
  sources, currentSourceId, isMulti, anchorRef, onClose, onSelect, onUngroupAll, onConfigure,
}) {
  /* Multi-room groups can only run Spotify — instead of showing the other
     sources as locked rows, hide them entirely and surface an explicit
     "Ungroup to use a different source" hint + Ungroup-all button so the
     user has a clear path out of the constraint. */
  const visibleSources = isMulti
    ? sources.filter(s => s.id === 'spotify')
    : sources
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
      {isMulti && onUngroupAll && (
        <div className="fx-source-popover-ungroup-group">
          <div className="fx-source-popover-hint">
            Ungroup to use other sources
          </div>
          <button
            type="button"
            className="fx-source-popover-ungroup"
            onClick={() => { onUngroupAll(); onClose() }}
          >
            <IconUnlink size={18} stroke={2.5} aria-hidden />
            <span>Ungroup all</span>
          </button>
        </div>
      )}
      {onConfigure && (
        <button
          type="button"
          className="fx-source-popover-configure"
          onClick={() => { onConfigure(); onClose() }}
        >
          <span className="fx-source-popover-configure-label">Configure</span>
          <IconChevronRight size={16} aria-hidden />
        </button>
      )}
    </div>
  )

  return createPortal(popover, document.body)
}
