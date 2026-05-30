import { useState, useCallback, useRef, useEffect, useMemo, useLayoutEffect } from 'react'
import { Speaker, Plus } from 'lucide-react'
import GroupCard from './GroupCard'
import ScaffoldGroupCard from './ScaffoldGroupCard'
import { apiFetch } from '../api'

// Mirrors GroupCard's home-client resolution so we can look up playback in
// the same place the card will. `mqtt.playback` is keyed by home client id.
const resolveHomeClientId = (g) =>
  g.home_client_id
  || (g.clients?.length === 1 ? g.clients[0]?.id : null)
  || (g.stream_id?.match(/source_(fauxnos\d+)_/)?.[1])
  || g.clients?.[0]?.id

const hasTrackMeta = (track) => !!track && (track.title || track.artist)

export default function GroupsTab({ groups, clients, mqtt, onRefresh, onOpenDevice, onAddDevice }) {
  const [dragClientId, setDragClientId] = useState(null)
  const [placeholderClientId, setPlaceholderClientId] = useState(null)
  const [dropTargetGroupId, setDropTargetGroupId] = useState(null)
  // Refs track the live drag because dragend fires after dropOnGroup's
  // setDragClientId(null), so reading state from a closure can race.
  const dragRef = useRef({ clientId: null, droppedOnGroup: false })

  // Optimistic override of the `groups` prop — set by drag/click handlers
  // so the UI reacts instantly; cleared when fresh server data lands. The
  // useEffect dependency on `groups` (the prop) means any onRefresh-driven
  // setGroups in the parent reconciles us back to the server's view.
  const [optimisticGroups, setOptimisticGroups] = useState(null)
  useEffect(() => { setOptimisticGroups(null) }, [groups])
  const effectiveGroups = optimisticGroups || groups
  // Ungroup anchors: when a device is ungrouped from a multi-card we pin its
  // newly-standalone home group to sit immediately below the source card,
  // overriding the default tier sort. Entries are cleared when the device
  // joins another group again or its source multi-card disappears.
  const [ungroupAnchors, setUngroupAnchors] = useState(() => new Map())
  const gridRef = useRef(null)
  const prevGroupRectsRef = useRef(new Map())

  // Name lookup
  const nameMap = {}
  for (const c of clients) {
    nameMap[c.client_id] = c.name
  }

  // Stream-id pattern `source_fauxnosNNN_*` encodes the home device. A
  // client's "home group" is the group whose stream_id starts with that
  // client's own id — it always exists in the data (even when empty and
  // therefore hidden from the visible list). Defined up here because the
  // anchor reordering in activeGroups below depends on it.
  const isHomeGroupOf = (group, clientId) => {
    const m = group.stream_id?.match(/source_(fauxnos\d+)_/)
    return m?.[1] === clientId
  }

  // Filter to groups with clients, then sort: media > playing > grouped > idle.
  // Track metadata is the authoritative "this card has media" signal used by
  // GroupCard, so rechecking this on every render keeps media devices pinned
  // above inactive devices even when playback state arrives late or briefly
  // reports not-playing.
  // Stable within each tier via the index tiebreak so cards don't jitter
  // when unrelated state (e.g. volume) changes.
  const tierOf = (g) => {
    const home = resolveHomeClientId(g)
    if (home && hasTrackMeta(mqtt.tracks[home])) return 0
    if (home && mqtt.playback[home]?.is_playing) return 1
    if ((g.clients?.length || 0) > 1) return 2
    return 3
  }
  const tierSorted = effectiveGroups
    .filter(g => g.clients?.length > 0)
    .map((g, i) => ({ g, i, t: tierOf(g) }))
    .sort((a, b) => a.t - b.t || a.i - b.i)
    .map(x => x.g)
  // Apply ungroup anchors after the tier sort. For each anchored (clientId,
  // sourceGroupId) entry, move clientId's home group to sit immediately after
  // sourceGroupId. Multiple anchors against the same source land in
  // most-recent-first order (so the latest ungroup is closest to the card).
  const activeGroups = (() => {
    if (ungroupAnchors.size === 0) return tierSorted
    const result = [...tierSorted]
    ungroupAnchors.forEach((sourceGroupId, clientId) => {
      const homeIdx = result.findIndex(
        g => g.clients?.some(c => c.id === clientId) && isHomeGroupOf(g, clientId)
      )
      const sourceIdx = result.findIndex(g => g.id === sourceGroupId)
      if (homeIdx === -1 || sourceIdx === -1) return
      let target = sourceIdx + 1
      if (homeIdx === target) return
      const [home] = result.splice(homeIdx, 1)
      if (homeIdx < target) target -= 1
      result.splice(target, 0, home)
    })
    return result
  })()
  // FLIP and React key by home_client_id rather than group.id. The
  // optimistic ungroup path synthesizes a group with id `optimistic_X_home`
  // which the server then replaces with a real id — using home_client_id
  // keeps the React component (and FLIP rect lookup) stable across that
  // swap, so the post-ungroup refresh no longer unmounts/flashes the card.
  const stableKey = (g) => g.home_client_id || g.id
  const activeGroupOrderKey = activeGroups.map(stableKey).join('|')

  useLayoutEffect(() => {
    const grid = gridRef.current
    if (!grid) return
    const cards = Array.from(grid.querySelectorAll('[data-group-card-id]'))
    const previous = prevGroupRectsRef.current
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

    if (!reduceMotion) {
      cards.forEach((node) => {
        const id = node.getAttribute('data-group-card-id')
        const prev = previous.get(id)
        const next = node.getBoundingClientRect()
        if (!prev) return
        const dy = prev.top - next.top
        if (Math.abs(dy) < 1) return
        node.animate(
          [
            { transform: `translateY(${dy}px)` },
            { transform: 'translateY(0)' },
          ],
          {
            duration: 320,
            easing: 'cubic-bezier(0.2, 0.8, 0.2, 1)',
          },
        )
      })
    }

    prevGroupRectsRef.current = new Map(
      cards.map(node => [node.getAttribute('data-group-card-id'), node.getBoundingClientRect()])
    )
  }, [activeGroupOrderKey])

  // Locate a client object by id across all groups in `base`. We need the
  // object (not just the id) so we can re-insert it into a different
  // group's clients[] without losing any per-client metadata like
  // host/name/config.
  const findClient = (base, clientId) => {
    for (const g of base) {
      const found = g.clients?.find(c => c.id === clientId)
      if (found) return found
    }
    return null
  }

  const handleJoinGroup = useCallback(async (clientId, targetHomeClientId) => {
    // Optimistic: move clientId out of its current group and into the
    // target group (the one whose home_client_id matches the target).
    setOptimisticGroups(prev => {
      const base = prev || groups
      const moving = findClient(base, clientId)
      if (!moving) return base
      return base.map(g => {
        const without = (g.clients || []).filter(c => c.id !== clientId)
        if (g.home_client_id === targetHomeClientId) {
          return { ...g, clients: [...without, moving] }
        }
        return { ...g, clients: without }
      })
    })
    try {
      await apiFetch('/api/groups/join', {
        method: 'POST',
        body: JSON.stringify({ client_id: clientId, target_client_id: targetHomeClientId }),
      })
      onRefresh()
    } catch (e) {
      console.error('Join group failed:', e)
      onRefresh() // reconcile to server reality on error too
    }
  }, [onRefresh, groups])

  // Multi-add from the "+" checklist: move every selected device into the
  // target group at once. We keep the existing single-join endpoint and loop
  // it client-side rather than adding a batched endpoint — that keeps this
  // change out of api_server.py (and clear of FX-7's server work). One
  // optimistic update covers all selections; the API calls fire sequentially
  // so the server applies them in order, then a single onRefresh reconciles.
  const handleAddDevices = useCallback(async (clientIds, targetHomeClientId) => {
    if (!clientIds?.length) return
    setOptimisticGroups(prev => {
      const base = prev || groups
      const moving = clientIds.map(id => findClient(base, id)).filter(Boolean)
      if (moving.length === 0) return base
      const movingIds = new Set(moving.map(c => c.id))
      return base.map(g => {
        const without = (g.clients || []).filter(c => !movingIds.has(c.id))
        if (g.home_client_id === targetHomeClientId) {
          return { ...g, clients: [...without, ...moving] }
        }
        return { ...g, clients: without }
      })
    })
    try {
      for (const id of clientIds) {
        await apiFetch('/api/groups/join', {
          method: 'POST',
          body: JSON.stringify({ client_id: id, target_client_id: targetHomeClientId }),
        })
      }
      onRefresh()
    } catch (e) {
      console.error('Add devices failed:', e)
      onRefresh() // reconcile to server reality on error too
    }
  }, [onRefresh, groups])

  const handleReturnHome = useCallback(async (clientId) => {
    // Record an ungroup anchor so the new home card pins right below the
    // source multi-card instead of dropping to the bottom of the tier sort.
    // Only meaningful when the device is currently in a multi-device group.
    const sourceMulti = (optimisticGroups || groups).find(
      g => (g.clients?.length || 0) > 1 && g.clients.some(c => c.id === clientId)
    )
    if (sourceMulti) {
      setUngroupAnchors(prev => {
        const next = new Map(prev)
        // Reinsert so the newest anchor sorts to the front when multiple
        // devices are ungrouped from the same source (Map iteration order).
        next.delete(clientId)
        next.set(clientId, sourceMulti.id)
        return next
      })
    }
    // Optimistic: pull clientId out of whatever group it's in and drop
    // it back into its own home group. The home group exists in `groups`
    // as long as the server returns it (even empty); when it doesn't —
    // some servers omit empty groups — we synthesize one so the device
    // pops back into the visible list immediately. Server refresh will
    // replace our placeholder with the real group entry.
    setOptimisticGroups(prev => {
      const base = prev || groups
      const moving = findClient(base, clientId)
      if (!moving) return base
      let foundHome = false
      const updated = base.map(g => {
        const without = (g.clients || []).filter(c => c.id !== clientId)
        if (isHomeGroupOf(g, clientId)) {
          foundHome = true
          return { ...g, clients: [...without, moving] }
        }
        return { ...g, clients: without }
      })
      if (!foundHome) {
        updated.push({
          id: `optimistic_${clientId}_home`,
          home_client_id: clientId,
          stream_id: `source_${clientId}_spotify`,
          clients: [moving],
          sources: [],
          available_streams: [],
        })
      }
      return updated
    })
    try {
      await apiFetch('/api/groups/return-home', {
        method: 'POST',
        body: JSON.stringify({ client_id: clientId }),
      })
      onRefresh()
    } catch (e) {
      console.error('Return home failed:', e)
      onRefresh()
    }
  }, [onRefresh, groups, optimisticGroups])

  // Drop stale ungroup anchors: when the device has rejoined another group
  // (or its source multi-card no longer exists) the anchor is no longer
  // meaningful, so let the natural tier sort take over again.
  useEffect(() => {
    if (ungroupAnchors.size === 0) return
    setUngroupAnchors(prev => {
      let changed = false
      const next = new Map(prev)
      prev.forEach((sourceGroupId, clientId) => {
        const homeGroup = groups.find(
          g => g.clients?.some(c => c.id === clientId) && isHomeGroupOf(g, clientId)
        )
        const sourceExists = groups.find(g => g.id === sourceGroupId)
        if (!homeGroup || !sourceExists) {
          next.delete(clientId)
          changed = true
        }
      })
      return changed ? next : prev
    })
    // isHomeGroupOf is a stable in-component helper
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groups])

  // Ungroup every member of a multi-device group at once. The naive approach
  // — looping `handleReturnHome` per member — fires N concurrent
  // /api/groups/return-home calls, and the server's return_client_to_home does
  // a read-modify-write (read group members → SetClients to "everyone but me").
  // Concurrent calls for the same group both read the full member list and
  // clobber each other's eviction, so one member survives and the group snaps
  // back to N-1 devices. We fix it here, on the client: one optimistic update
  // covering all members, the API calls fired *sequentially* so each reads
  // fresh snapcast state, then a single onRefresh at the end (rather than one
  // per call thrashing the optimistic view mid-flight).
  const handleUngroupAll = useCallback(async (clientIds) => {
    if (!clientIds?.length) return
    setOptimisticGroups(prev => {
      let base = prev || groups
      for (const clientId of clientIds) {
        const moving = findClient(base, clientId)
        if (!moving) continue
        let foundHome = false
        base = base.map(g => {
          const without = (g.clients || []).filter(c => c.id !== clientId)
          if (isHomeGroupOf(g, clientId)) {
            foundHome = true
            return { ...g, clients: [...without, moving] }
          }
          return { ...g, clients: without }
        })
        if (!foundHome) {
          base = [...base, {
            id: `optimistic_${clientId}_home`,
            home_client_id: clientId,
            stream_id: `source_${clientId}_spotify`,
            clients: [moving],
            sources: [],
            available_streams: [],
          }]
        }
      }
      return base
    })
    try {
      for (const clientId of clientIds) {
        await apiFetch('/api/groups/return-home', {
          method: 'POST',
          body: JSON.stringify({ client_id: clientId }),
        })
      }
      onRefresh()
    } catch (e) {
      console.error('Ungroup all failed:', e)
      onRefresh() // reconcile to server reality on error too
    }
    // isHomeGroupOf is a stable in-component helper
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onRefresh, groups])

  const handleSwitchSource = useCallback(async (groupId, homeClientId, sourceId) => {
    // Optimistic update — show new source immediately
    mqtt.setMode(homeClientId, sourceId)
    try {
      await apiFetch('/api/groups/source', {
        method: 'POST',
        body: JSON.stringify({ group_id: groupId, home_client_id: homeClientId, source_id: sourceId }),
      })
      onRefresh()
    } catch (e) {
      console.error('Switch source failed:', e)
    }
  }, [mqtt, onRefresh])

  // Drag and drop handlers for the tab level
  const handleDragStart = useCallback((clientId) => {
    dragRef.current = { clientId, droppedOnGroup: false }
    setDragClientId(clientId)
    requestAnimationFrame(() => {
      if (dragRef.current.clientId === clientId) setPlaceholderClientId(clientId)
    })
  }, [])

  // Fires on every drag termination — whether dropped on a group, dropped on
  // the page background, or cancelled with Esc. If a member was dragged out
  // of a multi-device group and not dropped onto another group, treat that
  // as "remove from group" (return-home).
  const handleDragEnd = useCallback(() => {
    const { clientId, droppedOnGroup } = dragRef.current
    dragRef.current = { clientId: null, droppedOnGroup: false }
    setDragClientId(null)
    setPlaceholderClientId(null)
    setDropTargetGroupId(null)
    setActiveSlotIndex(null)
    if (!clientId || droppedOnGroup) return

    const sourceGroup = groups.find(g => g.clients?.some(c => c.id === clientId))
    const eligible = sourceGroup
      && sourceGroup.clients.length > 1
      && sourceGroup.home_client_id !== clientId
    if (eligible) handleReturnHome(clientId)
  }, [groups, handleReturnHome])

  // "Removable" means dropping on background/slot actually changes anything —
  // the dragged client is in a multi-device group AND it's not the home
  // device of that group (home can't be ejected). For non-removable drags
  // (e.g. dragging a standalone device), slot drops still resolve cleanly
  // but the API call is a no-op since the device is already where it'd land.
  const isRemovableDrag = useMemo(() => {
    if (!dragClientId) return false
    const sourceGroup = effectiveGroups.find(
      g => g.clients?.some(c => c.id === dragClientId)
    )
    return !!sourceGroup
      && (sourceGroup.clients?.length || 0) > 1
      && sourceGroup.home_client_id !== dragClientId
  }, [dragClientId, effectiveGroups])

  // Document-level dragover/drop. Without these, the browser treats the
  // page background as a non-drop region: the drag image plays a revert
  // animation and the actual move only fires on dragEnd. By preventing
  // default on dragover (which marks the location as a valid drop) and
  // handling drop ourselves, the drag completes instantly the moment the
  // user releases, no revert animation. If a group card's React onDrop
  // already ran, e.defaultPrevented will be true and we no-op.
  useEffect(() => {
    if (!dragClientId) return
    const onDragOver = (e) => { e.preventDefault() }
    const onDrop = (e) => {
      if (e.defaultPrevented) return
      e.preventDefault()
      const clientId = dragRef.current.clientId
      dragRef.current.droppedOnGroup = true // suppress duplicate in dragEnd
      if (clientId && isRemovableDrag) {
        handleReturnHome(clientId)
      }
      setDragClientId(null)
      setPlaceholderClientId(null)
      setDropTargetGroupId(null)
    }
    document.addEventListener('dragover', onDragOver)
    document.addEventListener('drop', onDrop)
    return () => {
      document.removeEventListener('dragover', onDragOver)
      document.removeEventListener('drop', onDrop)
    }
  }, [dragClientId, isRemovableDrag, handleReturnHome])

  const handleDragOverGroup = useCallback((groupId) => {
    setDropTargetGroupId(groupId)
  }, [])

  const handleDragLeaveGroup = useCallback(() => {
    setDropTargetGroupId(null)
  }, [])

  const handleDropOnGroup = useCallback((targetGroupId) => {
    dragRef.current.droppedOnGroup = true
    setDropTargetGroupId(null)
    if (!dragClientId) return

    // Find the home client of the target group
    const targetGroup = groups.find(g => g.id === targetGroupId)
    if (!targetGroup?.home_client_id) return

    // Don't drop on own group
    const sourceGroup = groups.find(g => g.clients?.some(c => c.id === dragClientId))
    if (sourceGroup?.id === targetGroupId) return

    handleJoinGroup(dragClientId, targetGroup.home_client_id)
    setDragClientId(null)
    setPlaceholderClientId(null)
  }, [dragClientId, groups, handleJoinGroup])

  if (activeGroups.length === 0) {
    return (
      <div className="fx-page">
        <div className="fx-groups-grid">
          <ScaffoldGroupCard />
        </div>
        <div className="fx-card fx-empty">
          <Speaker size={28} />
          <div className="fx-h3">No devices yet</div>
          <p className="fx-small fx-mute">
            Add your first Fauxnos device to start streaming. You'll need a
            Raspberry Pi and a DAC HAT.
          </p>
          {onAddDevice && (
            <button className="fx-btn primary pill" onClick={onAddDevice}>
              <Plus size={14} /> Add device
            </button>
          )}
        </div>
      </div>
    )
  }

  const isDragging = !!dragClientId
  return (
    <div className="fx-page">
      <div className="fx-groups-grid" ref={gridRef}>
        <ScaffoldGroupCard />
        {activeGroups.map((group) => (
          <GroupCard
            key={stableKey(group)}
            group={group}
            nameMap={nameMap}
            mqtt={mqtt}
            clients={clients}
            isDragTarget={dropTargetGroupId === group.id}
            isDragging={isDragging}
            dragClientId={dragClientId}
            placeholderClientId={placeholderClientId}
            onDragStart={handleDragStart}
            onDragEnd={handleDragEnd}
            onDragOverGroup={() => handleDragOverGroup(group.id)}
            onDragLeaveGroup={handleDragLeaveGroup}
            onDropOnGroup={() => handleDropOnGroup(group.id)}
            onReturnHome={handleReturnHome}
            onUngroupAll={handleUngroupAll}
            onSwitchSource={handleSwitchSource}
            onOpenDevice={onOpenDevice}
            onAddDevices={handleAddDevices}
          />
        ))}
      </div>
    </div>
  )
}
