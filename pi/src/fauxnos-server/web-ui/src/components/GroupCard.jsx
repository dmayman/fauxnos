import { useState, useEffect, useRef, useCallback } from 'react'
import { Settings2, GripVertical, X, Music, AudioLines, Plug, Cast } from 'lucide-react'
import VolumeSlider from './VolumeSlider'

/**
 * Icon for a source row/button. Built-ins map to recognizable glyphs;
 * everything else (custom external sources) gets a neutral Plug icon.
 */
function SourceIcon({ source, size = 14 }) {
  const id = source?.id
  const Icon =
    id === 'spotify' ? Music :
    id === 'airplay' ? Cast :
    id === 'analog'  ? AudioLines :
    Plug
  return <Icon size={size} aria-hidden />
}

/**
 * Right-aligned source pickers that sit in the same row as the group
 * title. Active source renders as a filled primary button, the others
 * as quiet neutral buttons — enough hierarchy to read the active one at
 * a glance without screaming.
 */
function SourceButtons({ sources, currentStream, activeMode, groupId, homeClientId, onSwitchSource }) {
  // Prefer MQTT mode (tracks actual active source), fall back to snapcast stream.
  // Replace the leading `source_fauxnos<N>_` prefix to get the bare source id
  // — matches the value the buttons fire so MQTT echoes light up the right one.
  const currentSourceId = activeMode
    || (currentStream ? currentStream.replace(/^source_fauxnos\d+_/, '') : null)

  if (sources.length === 0) {
    return (
      <div className="fx-source-buttons">
        <button type="button" className="fx-source-btn active" disabled>
          <SourceIcon source={{ id: currentSourceId }} />
          <span>{currentSourceId || '—'}</span>
        </button>
      </div>
    )
  }

  return (
    <div className="fx-source-buttons" role="radiogroup">
      {sources.map(s => {
        const isActive = currentSourceId === s.id
        return (
          <button
            key={s.id}
            type="button"
            role="radio"
            aria-checked={isActive}
            className={`fx-source-btn${isActive ? ' active' : ''}`}
            onClick={() => onSwitchSource(groupId, homeClientId, s.id)}
            title={s.label || s.id}
          >
            <SourceIcon source={s} />
            <span className="fx-source-btn-label">{s.label || s.id}</span>
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
  // AirPlay's volume is owned by the iPhone — we display, but cannot
  // push back without a DACP client. Slider becomes read-only.
  const isAirplay = mqtt.modes[client.id] === 'airplay'

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
        <span className="fx-group-member-label">{name}</span>
        {!isHome && (
          <button
            className="fx-group-member-x"
            onClick={() => onReturnHome(client.id)}
            title="Remove from group"
            aria-label="Remove from group"
          >
            <X size={12} />
          </button>
        )}
      </span>
      <div className="fx-group-member-slider">
        <VolumeSlider
          clientId={client.id}
          value={vol}
          mqtt={mqtt}
          hideIcon
          ariaLabel={`${name} volume`}
          external={isAirplay}
        />
      </div>
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
  // AirPlay's volume is owned by the iPhone slider — we display the
  // current value (mirrored in via shairport metadata pipe → MQTT)
  // but cannot push back. So lock the fauxnos slider on this source.
  const isAirplayHome = mqtt.modes[homeClient?.id] === 'airplay'

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
          <span className="fx-group-name">
            {/* The name text and the subtitle are siblings, NOT nested:
                the ellipsis-clipping `overflow: hidden` lives on
                .fx-group-name-main only, so it doesn't clip the
                absolutely-positioned subtitle that sits below. */}
            <span className="fx-group-name-main">{groupName}</span>
            {isAirplayHome && !isMulti && (
              <span className="fx-group-name-subtitle">
                Volume controlled by iPhone
              </span>
            )}
          </span>
          <SourceButtons
            sources={group.sources || []}
            currentStream={group.stream_id}
            activeMode={mqtt.modes[homeClientId]}
            groupId={group.id}
            homeClientId={homeClientId}
            onSwitchSource={onSwitchSource}
          />
          <button
            className="fx-icon-btn"
            onClick={() => onOpenDevice(homeClientId)}
            title="Device settings"
            aria-label="Device settings"
          >
            <Settings2 size={16} />
          </button>
        </div>

        {!isMulti && (
          <div className="fx-group-vol">
            <VolumeSlider
              clientId={homeClient.id}
              value={homeVol}
              mqtt={mqtt}
              variant="accent"
              ariaLabel={`${groupName} volume`}
              external={isAirplayHome}
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
