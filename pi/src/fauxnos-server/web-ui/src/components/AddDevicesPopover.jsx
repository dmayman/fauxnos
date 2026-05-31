import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { IconCheck, IconUnlink } from '@tabler/icons-react'

/**
 * Popover that opens from a group's title chevron — the single place to
 * compose or edit a group's membership.
 *
 * - Anchors below-left of the trigger using its `getBoundingClientRect`.
 * - Shows the WHOLE fleet, always. The home (master) device is pinned
 *   checked + disabled — it can never leave its own group. Current members
 *   come pre-checked and can be unchecked to remove them.
 * - A "Select all" link in the title row checks every device at once.
 * - The commit button reconciles: it hands the full desired membership to the
 *   caller, which diffs against live state and fires the right joins/removes.
 *   Label is "Create group" when the card is still a single device, "Update
 *   group" once it's already a group. Disabled until the selection differs
 *   from the current membership (and, when creating, until 1+ device beyond
 *   the home is picked).
 * - Closes on click-outside (excluding the anchor) or after confirm.
 */
export default function AddDevicesPopover({ devices, homeClientId, memberIds, isGroup, anchorRef, onClose, onConfirm }) {
  const ref = useRef(null)
  const [pos, setPos] = useState(null)

  // Current membership as a stable set — the baseline the selection diffs
  // against and the seed for the initial checked state.
  const memberSet = useMemo(() => new Set(memberIds), [memberIds])

  // Home (master) device always sits at the top — it's the locked anchor of
  // the group. Everything else keeps the caller's name-sorted order.
  const orderedDevices = useMemo(() => {
    const home = devices.filter(d => d.id === homeClientId)
    const rest = devices.filter(d => d.id !== homeClientId)
    return [...home, ...rest]
  }, [devices, homeClientId])
  const [selected, setSelected] = useState(() => {
    const init = new Set(memberIds)
    init.add(homeClientId) // home is always part of its own group
    return init
  })

  useEffect(() => {
    const place = () => {
      const el = anchorRef?.current
      if (!el) return
      const r = el.getBoundingClientRect()
      // Hang from the trigger's bottom-left edge with an 8px gap. The chevron
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
    if (id === homeClientId) return // home is locked in
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  // Toggle between "all selected" and "only the home". When everything is
  // already checked, this clears back down to the locked-in home device.
  const allSelected = selected.size === devices.length
  const toggleSelectAll = () =>
    setSelected(allSelected ? new Set([homeClientId]) : new Set(devices.map(d => d.id)))

  // Dirty = the chosen membership differs from what's live. Plus, when
  // creating, require at least one device beyond the home (a one-device
  // "group" isn't a group). Same size + same contents ⇒ no change.
  const sameAsMembers =
    selected.size === memberSet.size && [...selected].every(id => memberSet.has(id))
  const isDirty = !sameAsMembers && (isGroup || selected.size > 1)

  const popover = (
    <div
      className="fx-popover fx-add-devices-popover"
      ref={ref}
      role="menu"
      style={pos ? { top: pos.top, left: pos.left } : undefined}
    >
      <div className="fx-add-devices-header">
        <span className="fx-add-devices-title">Audio group</span>
        <button type="button" className="fx-add-devices-select-all" onClick={toggleSelectAll}>
          {allSelected ? 'Select none' : 'Select all'}
        </button>
      </div>
      <div className="fx-add-devices-list">
        {orderedDevices.map(d => {
          const checked = selected.has(d.id)
          const locked = d.id === homeClientId
          return (
            <button
              key={d.id}
              type="button"
              role="menuitemcheckbox"
              aria-checked={checked}
              disabled={locked}
              className={`fx-add-devices-row${checked ? ' selected' : ''}${locked ? ' locked' : ''}`}
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
      {isGroup && !isDirty ? (
        // Existing group, untouched: the only action is to disband it. Tertiary
        // outlined treatment so it reads as a quieter, destructive-ish option;
        // confirming with just the home returns every member to its own group.
        <button
          type="button"
          className="fx-add-devices-confirm tertiary"
          onClick={() => {
            onConfirm([homeClientId])
            onClose()
          }}
        >
          <IconUnlink size={16} /> Break group
        </button>
      ) : (
        <button
          type="button"
          className="fx-add-devices-confirm primary"
          disabled={!isDirty}
          onClick={() => {
            onConfirm([...selected])
            onClose()
          }}
        >
          Update group
        </button>
      )}
    </div>
  )

  return createPortal(popover, document.body)
}
