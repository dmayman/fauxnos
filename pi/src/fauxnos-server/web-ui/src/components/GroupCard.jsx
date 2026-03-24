import { useState, useEffect, useRef, useCallback } from 'react'
import VolumeSlider from './VolumeSlider'

function SourceDropdown({ sources, currentStream, activeMode, groupId, homeClientId, onSwitchSource }) {
  // Prefer MQTT mode (tracks actual active source), fall back to snapcast stream
  const currentSourceId = activeMode
    || (currentStream ? currentStream.replace(/^source_fauxnos\d+_/, '') : null)

  return (
    <select
      className="stream-select"
      value={currentSourceId || ''}
      onChange={e => onSwitchSource(groupId, homeClientId, e.target.value)}
    >
      {sources.length > 0
        ? sources.map(s => (
            <option key={s.id} value={s.id}>{s.label || s.id}</option>
          ))
        : <option>{currentSourceId || '—'}</option>
      }
    </select>
  )
}

function DeviceRow({ client, isHome, nameMap, mqtt, onReturnHome, onDragStart, onDragEnd }) {
  const name = nameMap[client.id] || client.host?.name || client.id
  const vol = mqtt.volumes[client.id] ?? client.config?.volume?.percent ?? 0
  const rowRef = useRef(null)

  return (
    <div className={`device-row${isHome ? ' is-home' : ' is-guest'}`} ref={rowRef}>
      <div className="device-row-left">
        {!isHome ? (
          <span
            className="drag-handle"
            draggable
            onDragStart={e => {
              e.dataTransfer.setData('text/plain', client.id)
              e.dataTransfer.effectAllowed = 'move'
              if (rowRef.current) {
                e.dataTransfer.setDragImage(rowRef.current, 0, 0)
              }
              onDragStart(client.id)
            }}
            onDragEnd={onDragEnd}
            title="Drag to regroup"
          >
            ⠿
          </span>
        ) : (
          <span className="drag-handle-spacer" />
        )}
        <span className={`conn-dot${client.connected ? ' on' : ''}`} />
        <span className="device-row-name">{name}</span>
      </div>
      <div className="device-row-volume">
        <VolumeSlider clientId={client.id} value={vol} mqtt={mqtt} />
      </div>
      <div className="device-row-actions">
        {!isHome ? (
          <button
            className="icon-btn btn-remove"
            onClick={() => onReturnHome(client.id)}
            title="Remove from group"
          >
            &times;
          </button>
        ) : (
          <span className="icon-btn-spacer" />
        )}
      </div>
    </div>
  )
}

export default function GroupCard({
  group, nameMap, mqtt,
  isDragTarget, isDragging,
  onDragStart, onDragEnd,
  onDragOverGroup, onDragLeaveGroup, onDropOnGroup,
  onReturnHome, onSwitchSource, onOpenSources,
}) {
  const homeClientId = group.home_client_id
  const isMulti = group.clients.length > 1
  const cardRef = useRef(null)

  const sorted = [...group.clients].sort((a, b) => {
    if (a.id === homeClientId) return -1
    if (b.id === homeClientId) return 1
    return 0
  })

  const homeClient = sorted.find(c => c.id === homeClientId) || sorted[0]
  const homeVol = mqtt.volumes[homeClient?.id] ?? homeClient?.config?.volume?.percent ?? 0

  const groupName = sorted
    .map(c => nameMap[c.id] || c.host?.name || c.id)
    .join(', ')

  const clientVols = sorted.map(c => mqtt.volumes[c.id] ?? c.config?.volume?.percent ?? 0)
  const groupVol = Math.max(...clientVols, 0)

  const handleDragOver = (e) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    onDragOverGroup()
  }

  return (
    <div className="group-card-row">
      {/* Drag handle in the gutter — only for single-device cards */}
      {!isMulti ? (
        <span
          className="drag-handle"
          draggable
          onDragStart={e => {
            e.dataTransfer.setData('text/plain', homeClientId)
            e.dataTransfer.effectAllowed = 'move'
            if (cardRef.current) {
              e.dataTransfer.setDragImage(cardRef.current, 0, 0)
            }
            onDragStart(homeClientId)
          }}
          onDragEnd={onDragEnd}
          title="Drag to regroup"
        >
          ⠿
        </span>
      ) : (
        <span className="drag-handle-spacer" />
      )}

      <div
        ref={cardRef}
        className={`group-card${isMulti ? ' group-card-multi' : ' group-card-single'}${isDragTarget ? ' drop-target' : ''}`}
        onDragOver={handleDragOver}
        onDragLeave={onDragLeaveGroup}
        onDrop={(e) => { e.preventDefault(); onDropOnGroup() }}
      >
        <div className="group-card-header">
          <span className="group-name">{groupName}</span>
          <div className="group-header-right">
            <SourceDropdown
              sources={group.sources || []}
              currentStream={group.stream_id}
              activeMode={mqtt.modes[homeClientId]}
              groupId={group.id}
              homeClientId={homeClientId}
              onSwitchSource={onSwitchSource}
            />
            <button
              className="icon-btn gear-btn"
              onClick={() => onOpenSources(homeClientId, nameMap[homeClientId] || homeClientId)}
              title="Source settings"
            >
              &#9881;
            </button>
          </div>
        </div>

        {!isMulti && (
          <VolumeSlider clientId={homeClient.id} value={homeVol} mqtt={mqtt} />
        )}

        {isMulti && (
          <>
            <GroupVolumeSlider clients={sorted} mqtt={mqtt} groupVol={groupVol} />
            <div className="group-divider" />
            {sorted.map(c => (
              <DeviceRow
                key={c.id}
                client={c}
                isHome={c.id === homeClientId}
                nameMap={nameMap}
                mqtt={mqtt}
                onReturnHome={onReturnHome}
                onDragStart={onDragStart}
                onDragEnd={onDragEnd}
              />
            ))}
          </>
        )}
      </div>
    </div>
  )
}

function GroupVolumeSlider({ clients, mqtt, groupVol }) {
  const [localVal, setLocalVal] = useState(groupVol)
  const draggingRef = useRef(false)
  const baseVolsRef = useRef(null)

  useEffect(() => {
    if (!draggingRef.current) setLocalVal(groupVol)
  }, [groupVol])

  const publishAll = useCallback((newVol) => {
    const bases = baseVolsRef.current
    if (!bases) return
    const maxBase = Math.max(...Object.values(bases), 1)
    const ratio = newVol / maxBase
    clients.forEach(c => {
      const v = Math.round(Math.min(100, Math.max(0, (bases[c.id] || 0) * ratio)))
      mqtt.publishVolume(c.id, v)
    })
  }, [clients, mqtt])

  return (
    <div className="volume-control group-volume">
      <input
        type="range"
        className="vol-slider"
        min="0"
        max="100"
        value={localVal}
        onPointerDown={() => {
          draggingRef.current = true
          const bases = {}
          clients.forEach(c => {
            bases[c.id] = mqtt.volumes[c.id] ?? c.config?.volume?.percent ?? 0
          })
          baseVolsRef.current = bases
        }}
        onPointerUp={() => { draggingRef.current = false }}
        onInput={e => {
          const v = parseInt(e.target.value, 10)
          setLocalVal(v)
          publishAll(v)
        }}
        onChange={() => {}}
      />
      <span className="vol-label">{localVal}%</span>
    </div>
  )
}
