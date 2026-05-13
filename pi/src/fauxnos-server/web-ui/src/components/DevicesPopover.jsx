import { useEffect, useRef, useState } from 'react'
import { ChevronRight, Plus } from 'lucide-react'

/**
 * Popover anchored to the top-right status indicator.
 *
 * Lists every registered device (online + offline) so the user has a single
 * place to see fleet state without leaving Groups. Each row is a click
 * target that opens that device's panel; the panel itself is owned by App
 * so it stays mounted when the popover closes.
 *
 * The "Add device" button at the bottom is the only entry point to the
 * install wizard now that the top tabs are gone.
 */
export default function DevicesPopover({ clients, anchorRef, onClose, onOpenDevice, onAddDevice }) {
  const ref = useRef(null)
  // Measured anchor rect → translates into fixed-position top/right so the
  // popover hangs exactly off the pill's bottom-right edge, regardless of
  // viewport width or scroll position. Re-measures on resize.
  const [pos, setPos] = useState(null)

  useEffect(() => {
    const place = () => {
      const el = anchorRef?.current
      if (!el) return
      const r = el.getBoundingClientRect()
      setPos({ top: r.bottom + 8, right: window.innerWidth - r.right })
    }
    place()
    window.addEventListener('resize', place)
    return () => window.removeEventListener('resize', place)
  }, [anchorRef])

  // Close on outside-click. We exclude the anchor element so clicking it
  // again toggles cleanly via Header's own state instead of close-then-open.
  useEffect(() => {
    const handler = (e) => {
      if (ref.current?.contains(e.target)) return
      if (anchorRef?.current?.contains(e.target)) return
      onClose()
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [onClose, anchorRef])

  // Stable sort: connected first, then by display name. The popover is the
  // "fleet inventory" — surfacing online devices at the top keeps the
  // common case (pick the kitchen) one glance away.
  const sorted = [...clients].sort((a, b) => {
    if (a.connected !== b.connected) return a.connected ? -1 : 1
    return (a.name || a.client_id).localeCompare(b.name || b.client_id)
  })

  return (
    <div
      className="fx-popover fx-devices-popover"
      ref={ref}
      role="menu"
      style={pos ? { top: pos.top, right: pos.right } : undefined}
    >
      <div className="fx-devices-popover-header">Devices</div>
      {sorted.length === 0 && (
        <div className="fx-devices-popover-empty">No devices registered.</div>
      )}
      <div className="fx-devices-popover-list">
        {sorted.map((c) => (
          <button
            key={c.client_id}
            className="fx-device-cell"
            onClick={() => { onOpenDevice(c.client_id); onClose() }}
          >
            <span className="fx-device-cell-text">
              <span className="fx-device-cell-name">{c.name || c.client_id}</span>
              <span className="fx-device-cell-id fx-mono">{c.client_id}</span>
            </span>
            <span className={`fx-badge${c.connected ? ' ok' : ''}`}>
              <span className={`fx-dot${c.connected ? ' ok' : ''}`} />
              {c.connected ? 'Connected' : 'Offline'}
            </span>
            <ChevronRight size={14} className="fx-device-cell-chevron" aria-hidden />
          </button>
        ))}
      </div>
      <div className="fx-devices-popover-footer">
        <button className="fx-btn block" onClick={() => { onAddDevice(); onClose() }}>
          <Plus size={14} /> Add device
        </button>
      </div>
    </div>
  )
}
