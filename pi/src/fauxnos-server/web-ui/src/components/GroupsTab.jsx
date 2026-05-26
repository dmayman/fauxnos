import { useState, useCallback, useRef, useEffect, useMemo } from 'react'
import { Speaker, Plus } from 'lucide-react'
import GroupCard from './GroupCard'
import { apiFetch } from '../api'

export default function GroupsTab({ groups, clients, mqtt, onRefresh, onOpenDevice, onAddDevice }) {
  const [dragClientId, setDragClientId] = useState(null)
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

  // Name lookup
  const nameMap = {}
  for (const c of clients) {
    nameMap[c.client_id] = c.name
  }

  // Filter to groups with clients
  const activeGroups = effectiveGroups.filter(g => g.clients?.length > 0)

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

  // Stream-id pattern `source_fauxnosNNN_*` encodes the home device. A
  // client's "home group" is the group whose stream_id starts with that
  // client's own id — it always exists in the data (even when empty and
  // therefore hidden from the visible list).
  const isHomeGroupOf = (group, clientId) => {
    const m = group.stream_id?.match(/source_(fauxnos\d+)_/)
    return m?.[1] === clientId
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

  const handleReturnHome = useCallback(async (clientId) => {
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
  }, [])

  // Fires on every drag termination — whether dropped on a group, dropped on
  // the page background, or cancelled with Esc. If a member was dragged out
  // of a multi-device group and not dropped onto another group, treat that
  // as "remove from group" (return-home).
  const handleDragEnd = useCallback(() => {
    const { clientId, droppedOnGroup } = dragRef.current
    dragRef.current = { clientId: null, droppedOnGroup: false }
    setDragClientId(null)
    setDropTargetGroupId(null)
    if (!clientId || droppedOnGroup) return

    const sourceGroup = groups.find(g => g.clients?.some(c => c.id === clientId))
    const eligible = sourceGroup
      && sourceGroup.clients.length > 1
      && sourceGroup.home_client_id !== clientId
    if (eligible) handleReturnHome(clientId)
  }, [groups, handleReturnHome])

  // "Removable" means dropping on the background actually does something —
  // the dragged client is in a multi-device group AND it's not the home
  // device of that group (home can't be ejected).
  const isRemovableDrag = useMemo(() => {
    if (!dragClientId) return false
    const sourceGroup = effectiveGroups.find(
      g => g.clients?.some(c => c.id === dragClientId)
    )
    return !!sourceGroup
      && (sourceGroup.clients?.length || 0) > 1
      && sourceGroup.home_client_id !== dragClientId
  }, [dragClientId, effectiveGroups])

  // Viewport-stroke indicator: live only while the cursor is over the
  // background (no group card claimed it). Mutually exclusive with the
  // per-card .fx-drop highlight so the user never sees two competing
  // drop affordances at once.
  const showBackgroundDropZone = isRemovableDrag && !dropTargetGroupId
  useEffect(() => {
    if (!showBackgroundDropZone) return
    document.body.classList.add('fx-dragging-background')
    return () => document.body.classList.remove('fx-dragging-background')
  }, [showBackgroundDropZone])

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
  }, [dragClientId, groups, handleJoinGroup])

  if (activeGroups.length === 0) {
    return (
      <div className="fx-page">
        <div className="fx-card fx-empty">
          <Speaker size={28} />
          <div className="fx-h3">No devices yet</div>
          <p className="fx-small fx-mute">
            Add your first Fauxnos device to start streaming. You'll need a
            Raspberry Pi and a DAC HAT.
          </p>
          {onAddDevice && (
            <button className="fx-btn primary" onClick={onAddDevice}>
              <Plus size={14} /> Add device
            </button>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="fx-page">
      <div className="fx-groups-grid">
        {activeGroups.map(group => (
          <GroupCard
            key={group.id}
            group={group}
            nameMap={nameMap}
            mqtt={mqtt}
            isDragTarget={dropTargetGroupId === group.id}
            isDragging={!!dragClientId}
            onDragStart={handleDragStart}
            onDragEnd={handleDragEnd}
            onDragOverGroup={() => handleDragOverGroup(group.id)}
            onDragLeaveGroup={handleDragLeaveGroup}
            onDropOnGroup={() => handleDropOnGroup(group.id)}
            onReturnHome={handleReturnHome}
            onSwitchSource={handleSwitchSource}
            onOpenDevice={onOpenDevice}
          />
        ))}
      </div>
    </div>
  )
}
