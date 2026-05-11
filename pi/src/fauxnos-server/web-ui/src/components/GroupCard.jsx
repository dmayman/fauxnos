import { useState, useEffect, useRef, useCallback } from 'react'
import { Settings2, GripVertical, X } from 'lucide-react'
import VolumeSlider from './VolumeSlider'

function SourceToggleGroup({ sources, currentStream, activeMode, groupId, homeClientId, onSwitchSource }) {
  // Prefer MQTT mode (tracks actual active source), fall back to snapcast stream.
  // We replace the leading `source_fauxnos<N>_` prefix to get the bare source id
  // — matches the value the toggle buttons fire and lets MQTT echoes light up
  // the correct button before our optimistic update lands.
  const currentSourceId = activeMode
    || (currentStream ? currentStream.replace(/^source_fauxnos\d+_/, '') : null)

  // Empty source list (transient on first render) — render a single
  // disabled button echoing the current source id so the card doesn't
  // jump in height once /api/groups resolves.
  if (sources.length === 0) {
    return (
      <div className="fx-segmented">
        <button className="fx-segmented-btn active" disabled>
          {currentSourceId || '—'}
        </button>
      </div>
    )
  }

  return (
    <div className="fx-segmented" role="radiogroup">
      {sources.map(s => {
        const isActive = currentSourceId === s.id
        return (
          <button
            key={s.id}
            type="button"
            role="radio"
            aria-checked={isActive}
            className={`fx-segmented-btn${isActive ? ' active' : ''}`}
            onClick={() => onSwitchSource(groupId, homeClientId, s.id)}
            title={s.label || s.id}
          >
            {s.label || s.id}
          </button>
        )
      })}
    </div>
  )
}

function DeviceRow({ client, isHome, nameMap, mqtt, onReturnHome, onDragStart, onDragEnd }) {
  const name = nameMap[client.id] || client.host?.name || client.id
  const vol = mqtt.volumes[client.id] ?? client.config?.volume?.percent ?? 0
  const rowRef = useRef(null)

  return (
    <div className="fx-group-member" ref={rowRef}>
      <span className="fx-group-member-handle">
        {!isHome ? (
          <span
            className="fx-drag"
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
            <GripVertical size={14} />
          </span>
        ) : null}
      </span>
      <span className="fx-group-member-name">
        <span className={`fx-dot ${client.connected ? 'ok' : ''}`} />
        <span className="fx-group-member-label">{name}</span>
      </span>
      <div className="fx-group-member-slider">
        <VolumeSlider clientId={client.id} value={vol} mqtt={mqtt} hideIcon ariaLabel={`${name} volume`} />
      </div>
      <span className="fx-group-member-actions">
        {!isHome ? (
          <button
            className="fx-icon-btn sm danger"
            onClick={() => onReturnHome(client.id)}
            title="Remove from group"
            aria-label="Remove from group"
          >
            <X size={14} />
          </button>
        ) : null}
      </span>
    </div>
  )
}

export default function GroupCard({
  group, nameMap, mqtt,
  isDragTarget, isDragging,
  onDragStart, onDragEnd,
  onDragOverGroup, onDragLeaveGroup, onDropOnGroup,
  onReturnHome, onSwitchSource, onOpenDevice,
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
    <div className="fx-group-row">
      {/* Drag handle in the gutter — only for single-device cards */}
      <span className="fx-group-gutter">
        {!isMulti && (
          <span
            className="fx-drag"
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
            <GripVertical size={16} />
          </span>
        )}
      </span>

      <div
        ref={cardRef}
        className={`fx-card fx-card-hover fx-group-card${isDragTarget ? ' fx-drop' : ''}`}
        onDragOver={handleDragOver}
        onDragLeave={onDragLeaveGroup}
        onDrop={(e) => { e.preventDefault(); onDropOnGroup() }}
      >
        <div className="fx-group-head">
          <span className="fx-group-name">{groupName}</span>
          <button
            className="fx-icon-btn"
            onClick={() => onOpenDevice(homeClientId)}
            title="Device settings"
            aria-label="Device settings"
          >
            <Settings2 size={16} />
          </button>
        </div>

        <SourceToggleGroup
          sources={group.sources || []}
          currentStream={group.stream_id}
          activeMode={mqtt.modes[homeClientId]}
          groupId={group.id}
          homeClientId={homeClientId}
          onSwitchSource={onSwitchSource}
        />

        {!isMulti && (
          <div className="fx-group-vol">
            <VolumeSlider
              clientId={homeClient.id}
              value={homeVol}
              mqtt={mqtt}
              variant="accent"
              ariaLabel={`${groupName} volume`}
            />
          </div>
        )}

        {isMulti && (
          <>
            <div className="fx-group-vol">
              <GroupVolumeSlider clients={sorted} mqtt={mqtt} groupVol={groupVol} />
            </div>
            <hr className="fx-divider" />
            <div className="fx-group-members">
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
            </div>
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

  // Custom slider drawing — same look as VolumeSlider but writes proportional
  // values to every member. We could pass a publisher down to VolumeSlider
  // but the proportional-ratio logic only makes sense at this level.
  const pct = `${localVal}%`

  return (
    <div className="fx-volume lg accent">
      <div className="fx-volume-track">
        <div className="fx-volume-fill" style={{ width: pct }} />
        <div className="fx-volume-thumb" style={{ left: pct }} />
        <input
          className="fx-volume-input"
          type="range"
          min={0}
          max={100}
          value={localVal}
          aria-label="Group volume"
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
      </div>
      <span className="fx-volume-label fx-num">{localVal}%</span>
    </div>
  )
}
