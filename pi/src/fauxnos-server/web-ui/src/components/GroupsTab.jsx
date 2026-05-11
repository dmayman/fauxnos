import { useState, useCallback } from 'react'
import { RefreshCw, Speaker, Plus } from 'lucide-react'
import GroupCard from './GroupCard'
import { apiFetch } from '../api'

export default function GroupsTab({ groups, clients, mqtt, onRefresh, onOpenDevice, onAddDevice }) {
  const [dragClientId, setDragClientId] = useState(null)
  const [dropTargetGroupId, setDropTargetGroupId] = useState(null)

  // Name lookup
  const nameMap = {}
  for (const c of clients) {
    nameMap[c.client_id] = c.name
  }

  // Filter to groups with clients
  const activeGroups = groups.filter(g => g.clients?.length > 0)

  const handleJoinGroup = useCallback(async (clientId, targetHomeClientId) => {
    try {
      await apiFetch('/api/groups/join', {
        method: 'POST',
        body: JSON.stringify({ client_id: clientId, target_client_id: targetHomeClientId }),
      })
      onRefresh()
    } catch (e) {
      console.error('Join group failed:', e)
    }
  }, [onRefresh])

  const handleReturnHome = useCallback(async (clientId) => {
    try {
      await apiFetch('/api/groups/return-home', {
        method: 'POST',
        body: JSON.stringify({ client_id: clientId }),
      })
      onRefresh()
    } catch (e) {
      console.error('Return home failed:', e)
    }
  }, [onRefresh])

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
    setDragClientId(clientId)
  }, [])

  const handleDragEnd = useCallback(() => {
    setDragClientId(null)
    setDropTargetGroupId(null)
  }, [])

  const handleDragOverGroup = useCallback((groupId) => {
    setDropTargetGroupId(groupId)
  }, [])

  const handleDragLeaveGroup = useCallback(() => {
    setDropTargetGroupId(null)
  }, [])

  const handleDropOnGroup = useCallback((targetGroupId) => {
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
        <div className="fx-page-head">
          <h1 className="fx-h1">Groups</h1>
          <button className="fx-btn" onClick={onRefresh} aria-label="Refresh">
            <RefreshCw size={14} /> Refresh
          </button>
        </div>
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
      <div className="fx-page-head">
        <h1 className="fx-h1">Groups</h1>
        <button className="fx-btn" onClick={onRefresh} aria-label="Refresh">
          <RefreshCw size={14} /> Refresh
        </button>
      </div>
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
