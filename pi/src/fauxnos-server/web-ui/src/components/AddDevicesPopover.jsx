import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { IconCheck } from '@tabler/icons-react'

/**
 * Popover that opens from a group's "+" (add devices) button.
 *
 * - Anchors below-left of the trigger using its `getBoundingClientRect`.
 * - Each row is a checkbox: device name on the left, a check box on the
 *   right. Multi-select — toggling rows accumulates a selection set.
 * - A commit button sits at the bottom: with nothing checked it's a secondary
 *   "Group all" (adds every available device); checking 1+ flips it to a
 *   primary "Add to group" that adds just the selection. Either way the parent
 *   loops single `/api/groups/join` calls.
 * - Closes on click-outside (excluding the anchor) or after confirm.
 *
 * `devices` is the list of devices NOT already in the group — the caller is
 * responsible for that filtering, so this component never offers a member.
 */
export default function AddDevicesPopover({ devices, anchorRef, onClose, onConfirm }) {
  const ref = useRef(null)
  const [pos, setPos] = useState(null)
  const [selected, setSelected] = useState(() => new Set())

  useEffect(() => {
    const place = () => {
      const el = anchorRef?.current
      if (!el) return
      const r = el.getBoundingClientRect()
      // Hang from the trigger's bottom-left edge with an 8px gap. The "+"
      // lives on the left side of the card, so left-anchoring keeps the
      // popover on-screen without overflowing the right edge.
      setPos({ top: r.bottom + 8, left: r.left })
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

  const toggle = (id) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const popover = (
    <div
      className="fx-popover fx-add-devices-popover"
      ref={ref}
      role="menu"
      style={pos ? { top: pos.top, left: pos.left } : undefined}
    >
      <div className="fx-add-devices-header">Add to group</div>
      {devices.length === 0 ? (
        <div className="fx-add-devices-empty">No other devices to add.</div>
      ) : (
        <div className="fx-add-devices-list">
          {devices.map(d => {
            const checked = selected.has(d.id)
            return (
              <button
                key={d.id}
                type="button"
                role="menuitemcheckbox"
                aria-checked={checked}
                className={`fx-add-devices-row${checked ? ' selected' : ''}`}
                onClick={() => toggle(d.id)}
              >
                <span className="fx-add-devices-row-label" title={d.name}>{d.name}</span>
                <span className={`fx-add-devices-check${checked ? ' on' : ''}`} aria-hidden>
                  {checked && <IconCheck size={14} stroke={3} />}
                </span>
              </button>
            )
          })}
        </div>
      )}
      {devices.length > 0 && (
        <button
          type="button"
          className={`fx-add-devices-confirm ${selected.size > 0 ? 'primary' : 'secondary'}`}
          onClick={() => {
            // With a selection, add exactly those; with none, "Group all"
            // pulls in every available device at once.
            const ids = selected.size > 0 ? [...selected] : devices.map(d => d.id)
            onConfirm(ids)
            onClose()
          }}
        >
          {selected.size > 0 ? 'Add to group' : 'Group all'}
        </button>
      )}
    </div>
  )

  return createPortal(popover, document.body)
}
