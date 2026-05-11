import { useState, useEffect, useCallback, useRef } from 'react'
import {
  X, Settings2, Plus, ChevronDown, ChevronRight, Check, Trash2,
  Music, Airplay, AudioLines, Plug,
} from 'lucide-react'
import VolumeSlider from './VolumeSlider'
import { apiFetch } from '../api'

// Fallback overlay list for first paint — server is authoritative via
// /api/dac_overlays. Mirrors modules/dac_overlays.py.
const FALLBACK_DAC_OVERLAYS = [
  { id: 'allo-boss-dac-pcm512x-audio', label: 'Allo Boss / INNO-MAKER PCM5122' },
  { id: 'hifiberry-dac',               label: 'HiFiBerry DAC+ Light / MiniAmp / generic PCM5102' },
  { id: 'hifiberry-dacplus',           label: 'HiFiBerry DAC+ Standard / Pro' },
  { id: 'hifiberry-dacplusadc',        label: 'HiFiBerry DAC+ ADC (line-in)' },
  { id: 'iqaudio-dacplus',             label: 'IQaudIO Pi-DAC+' },
]

// Built-in source definitions. Spotify/AirPlay are always shown; Analog is
// gated by has_adc and can be added/removed via the + menu — clicking
// + Analog In flips has_adc=true server-side and re-renders.
const BUILTIN_DEFS = [
  { id: 'spotify', label: 'Spotify', vc: 'snapcast', alwaysOn: true },
  { id: 'airplay', label: 'AirPlay', vc: 'snapcast', alwaysOn: true },
  { id: 'analog',  label: 'Analog In', vc: 'self',  gatedBy: 'has_adc' },
]

/**
 * Maps a source id (or category for non-default sources) to a recognizable
 * glyph. Used in source row labels and the + menu to give each option a
 * visual anchor.
 */
function SourceIcon({ source, size = 16 }) {
  const id = source?.id
  const Icon =
    id === 'spotify' ? Music :
    id === 'airplay' ? Airplay :
    id === 'analog'  ? AudioLines :
    Plug
  return <Icon size={size} aria-hidden />
}

/**
 * Combined device side panel — status, sources, advanced settings, remove.
 *
 * Section flow:
 *   1. Header — editable name + Connected chip + close
 *   2. Sources (built-in + custom, single list, + menu adds either kind)
 *   3. Advanced — DAC overlay (rare, scary)
 *   4. Remove (very rare, terminal)
 */
export default function DevicePanel({ client, mqtt, onClose, onRefresh }) {
  const [sources, setSources] = useState([])
  const [hasAdc, setHasAdc] = useState(!!client.has_adc)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [overlays, setOverlays] = useState(FALLBACK_DAC_OVERLAYS)
  const [addMenuOpen, setAddMenuOpen] = useState(false)
  const [addingCustom, setAddingCustom] = useState(false)
  const addMenuRef = useRef(null)

  // Sync local has_adc state when the prop changes (e.g. after refresh).
  useEffect(() => {
    setHasAdc(!!client.has_adc)
  }, [client.has_adc])

  // Fetch sources for this device. has_adc echo from /sources is the
  // source of truth — it's the same value coming from the server's stored
  // client record, but reading from /sources avoids a separate request.
  const loadSources = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiFetch(`/api/clients/${client.client_id}/sources`)
      setSources(data.sources || [])
      setHasAdc(data.has_adc || false)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [client.client_id])

  useEffect(() => { loadSources() }, [loadSources])

  // Fetch the canonical overlay list once — keeps the dropdown honest
  // if the server's allowlist changed since the page loaded.
  useEffect(() => {
    let cancelled = false
    apiFetch('/api/dac_overlays')
      .then(j => {
        if (!cancelled && Array.isArray(j?.overlays) && j.overlays.length) {
          setOverlays(j.overlays)
        }
      })
      .catch(() => { /* fall back */ })
    return () => { cancelled = true }
  }, [])

  // Close the + menu on any outside click.
  useEffect(() => {
    if (!addMenuOpen) return undefined
    const handler = (e) => {
      if (!addMenuRef.current?.contains(e.target)) setAddMenuOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [addMenuOpen])

  const defaultSources = sources.filter(s => s.category === 'default')
  const customSources = sources.filter(s => s.category !== 'default')

  // Build the visible built-in list. Each def is either "always on" or
  // gated by a per-client flag (currently only has_adc → analog).
  const visibleBuiltIns = BUILTIN_DEFS
    .filter(def => def.alwaysOn || (def.gatedBy === 'has_adc' && hasAdc))
    .map(def => defaultSources.find(s => s.id === def.id) || {
      id: def.id, label: def.label, type: 'internal', category: 'default',
      sink: def.id === 'analog' ? 'analogsink' : 'snapsink',
      starting_volume: 50, volume_controller: def.vc,
    })

  // Built-ins not yet added — drives the + menu's built-in entries.
  const addableBuiltIns = BUILTIN_DEFS.filter(def => {
    if (def.alwaysOn) return false
    if (def.gatedBy === 'has_adc') return !hasAdc
    return true
  })

  // Flip has_adc via the same /api/clients/<id> PUT used by the old
  // Devices tab. The client record (not /sources) owns this flag.
  const setHasAdcRemote = useCallback(async (next) => {
    const prev = hasAdc
    setHasAdc(next)  // optimistic
    try {
      await apiFetch(`/api/clients/${client.client_id}`, {
        method: 'PUT',
        body: JSON.stringify({ has_adc: next }),
      })
      onRefresh?.()
    } catch (e) {
      setHasAdc(prev)
      alert(`Failed: ${e.message}`)
    }
  }, [hasAdc, client.client_id, onRefresh])

  const handleAddBuiltIn = useCallback((def) => {
    setAddMenuOpen(false)
    if (def.gatedBy === 'has_adc') setHasAdcRemote(true)
  }, [setHasAdcRemote])

  const handleAddCustom = useCallback(() => {
    setAddMenuOpen(false)
    setAddingCustom(true)
  }, [])

  const handleRemoveBuiltIn = useCallback((sourceId) => {
    // Only analog is removable today — it's the only gated built-in.
    if (sourceId !== 'analog') return
    if (!confirm('Remove Analog In from this device?')) return
    setHasAdcRemote(false)
  }, [setHasAdcRemote])

  return (
    <div className="fx-side-panel fx-device-panel">
      <DevicePanelHeader
        client={client}
        onClose={onClose}
        onRefresh={onRefresh}
      />

      {loading && (
        <div className="fx-row fx-mute" style={{ padding: 'var(--fx-3) 0' }}>
          <span className="fx-spinner" /> Loading sources…
        </div>
      )}
      {error && (
        <div className="fx-banner err">Error: {error}</div>
      )}

      {!loading && !error && (
        <>
          <div className="fx-section-label">
            <span>Sources</span>
            <div className="fx-add-builtin-wrap" ref={addMenuRef}>
              <button
                className="fx-icon-btn sm"
                onClick={() => setAddMenuOpen(v => !v)}
                title="Add a source"
                aria-label="Add source"
              >
                <Plus size={14} />
              </button>
              {addMenuOpen && (
                <div className="fx-popover fx-add-builtin-menu">
                  {addableBuiltIns.map(def => (
                    <button
                      key={def.id}
                      className="fx-add-builtin-item"
                      onClick={() => handleAddBuiltIn(def)}
                    >
                      <SourceIcon source={def} size={14} />
                      <span>{def.label}</span>
                    </button>
                  ))}
                  {addableBuiltIns.length > 0 && <hr className="fx-add-builtin-divider" />}
                  <button
                    className="fx-add-builtin-item"
                    onClick={handleAddCustom}
                  >
                    <Plug size={14} aria-hidden />
                    <span>Custom source…</span>
                  </button>
                </div>
              )}
            </div>
          </div>
          <div className="fx-panel-card fx-source-list">
            {visibleBuiltIns.map(s => (
              <BuiltInSourceRow
                key={s.id}
                source={s}
                clientId={client.client_id}
                mqtt={mqtt}
                removable={s.id === 'analog'}
                onRemove={() => handleRemoveBuiltIn(s.id)}
                onUpdate={loadSources}
              />
            ))}
            {customSources.map(s => (
              <CustomSourceRow
                key={s.id}
                source={s}
                clientId={client.client_id}
                onDelete={loadSources}
                onUpdate={loadSources}
              />
            ))}
            {addingCustom && (
              <AddCustomSourceForm
                clientId={client.client_id}
                onAdded={() => { setAddingCustom(false); loadSources() }}
                onCancel={() => setAddingCustom(false)}
              />
            )}
          </div>

          <AdvancedSettings
            client={client}
            overlays={overlays}
            onRefresh={onRefresh}
          />

          <div className="fx-device-panel-footer">
            <RemoveDeviceButton client={client} onRemoved={() => { onRefresh?.(); onClose?.() }} />
          </div>
        </>
      )}
    </div>
  )
}

function ConnectedChip({ connected }) {
  return (
    <span className={`fx-badge${connected ? ' ok' : ''}`}>
      <span className={`fx-dot${connected ? ' ok' : ''}`} />
      {connected ? 'Connected' : 'Offline'}
    </span>
  )
}

function DevicePanelHeader({ client, onClose, onRefresh }) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(client.name || client.client_id)

  // Keep local name in sync if the prop changes underneath us (e.g.
  // another tab renamed the device). Skip when actively editing so we
  // don't clobber the user's typing.
  useEffect(() => {
    if (!editing) setName(client.name || client.client_id)
  }, [client.name, client.client_id, editing])

  const save = useCallback(async () => {
    setEditing(false)
    if (!name.trim() || name === client.name) {
      setName(client.name || client.client_id)
      return
    }
    try {
      await apiFetch(`/api/clients/${client.client_id}`, {
        method: 'PUT',
        body: JSON.stringify({ name: name.trim() }),
      })
      onRefresh?.()
    } catch {
      setName(client.name || client.client_id)
    }
  }, [name, client, onRefresh])

  return (
    <div className="fx-device-panel-head">
      <input
        className={`fx-device-name-edit${editing ? ' editing' : ''}`}
        value={name}
        readOnly={!editing}
        onDoubleClick={() => setEditing(true)}
        onChange={e => setName(e.target.value)}
        onBlur={save}
        onKeyDown={e => {
          if (e.key === 'Enter') e.target.blur()
          if (e.key === 'Escape') { setEditing(false); setName(client.name || client.client_id) }
        }}
        title="Double-click to rename"
      />
      <ConnectedChip connected={!!client.connected} />
      <button className="fx-icon-btn" onClick={onClose} aria-label="Close">
        <X size={18} />
      </button>
    </div>
  )
}

/**
 * Per-source built-in row. Lifted from the old SourcesPanel — same fields,
 * just hairline-separated rows instead of nested cards, and the form drops
 * inline beneath the row instead of inside its own surface fill.
 */
function BuiltInSourceRow({ source, clientId, mqtt, removable, onRemove, onUpdate }) {
  const [expanded, setExpanded] = useState(false)
  const ext = source.external_switch || {}
  const [enabled, setEnabled] = useState(ext.enabled || false)
  const [url, setUrl] = useState(ext.control_api || '')
  const [payload, setPayload] = useState(
    ext.control_payload ? JSON.stringify(ext.control_payload) : ''
  )
  const [contentType, setContentType] = useState(ext.content_type || 'json')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  const vcLabel = source.volume_controller === 'self' ? 'Self' : 'Snapcast'

  const calLive = mqtt?.calibrations?.[clientId]?.[source.id]
  const calibration = (typeof calLive === 'number') ? calLive : 100
  const handleCalibrationChange = (e) => {
    const v = parseInt(e.target.value, 10)
    if (Number.isFinite(v) && mqtt?.publishCalibration) {
      mqtt.publishCalibration(clientId, source.id, v)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    let parsedPayload = null
    if (payload.trim()) {
      try { parsedPayload = JSON.parse(payload) } catch { parsedPayload = payload }
    }
    try {
      await apiFetch(`/api/clients/${clientId}/sources/${source.id}`, {
        method: 'PUT',
        body: JSON.stringify({
          external_switch: { enabled, control_api: url, control_payload: parsedPayload, content_type: contentType },
        }),
      })
      setSaved(true)
      setTimeout(() => setSaved(false), 1500)
      onUpdate()
    } catch (e) {
      alert(`Save failed: ${e.message}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={`fx-source-item${expanded ? ' expanded' : ''}`}>
      <div className="fx-source-row">
        <div className="fx-source-info">
          <span className="fx-source-label">
            <span className="fx-source-icon"><SourceIcon source={source} /></span>
            <span>{source.label || source.id}</span>
          </span>
          <span className="fx-row" style={{ gap: 'var(--fx-1)' }}>
            <span className="fx-badge accent">Internal</span>
            <span className="fx-badge">{vcLabel}</span>
          </span>
        </div>
        <div className="fx-source-actions">
          <button
            className={`fx-icon-btn sm${expanded ? ' active' : ''}`}
            onClick={() => setExpanded(!expanded)}
            title="Configure"
            aria-label="Configure"
          >
            <Settings2 size={14} />
          </button>
          {removable && (
            <button
              className="fx-icon-btn sm danger"
              onClick={onRemove}
              title="Remove"
              aria-label="Remove this built-in source"
            >
              <Trash2 size={14} />
            </button>
          )}
        </div>
      </div>
      {expanded && (
        <div className="fx-source-form">
          <div className="fx-source-setting">
            <span className="fx-source-setting-label">Volume calibration</span>
            <div className="fx-volume accent fx-volume-compact">
              <div className="fx-volume-track">
                <div className="fx-volume-fill" style={{ width: `${calibration}%` }} />
                <div className="fx-volume-thumb" style={{ left: `${calibration}%` }} />
                <input
                  className="fx-volume-input"
                  type="range"
                  min={0}
                  max={100}
                  step={1}
                  value={calibration}
                  onChange={handleCalibrationChange}
                  aria-label="Volume calibration"
                />
              </div>
            </div>
          </div>
          <label className="fx-source-setting">
            <span className="fx-source-setting-label">Call an external API selected</span>
            <input
              className="fx-checkbox"
              type="checkbox"
              checked={enabled}
              onChange={e => setEnabled(e.target.checked)}
            />
          </label>
          {enabled && (
            <div className="fx-stack" style={{ gap: 'var(--fx-3)' }}>
              <div>
                <label className="fx-label">API URL</label>
                <input className="fx-input" type="url" value={url} onChange={e => setUrl(e.target.value)} placeholder="https://…" />
              </div>
              <div>
                <label className="fx-label">Payload</label>
                <textarea
                  className="fx-textarea"
                  rows={2}
                  value={payload}
                  onChange={e => setPayload(e.target.value)}
                  placeholder={contentType === 'form' ? '{"arg": "fauxnos"}' : '{"source": "fauxnos"}'}
                />
              </div>
              <div>
                <label className="fx-label">Encoding</label>
                <select className="fx-select" value={contentType} onChange={e => setContentType(e.target.value)}>
                  <option value="json">JSON</option>
                  <option value="form">Form (x-www-form-urlencoded)</option>
                </select>
              </div>
              <div>
                <button className="fx-btn primary" onClick={handleSave} disabled={saving}>
                  {saved ? <><Check size={14} /> Saved</> : <><Check size={14} /> Save</>}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function CustomSourceRow({ source, clientId, onDelete, onUpdate }) {
  const [editing, setEditing] = useState(false)
  const [label, setLabel] = useState(source.label || '')
  const [apiUrl, setApiUrl] = useState(source.control_api || '')
  const [payload, setPayload] = useState(
    source.control_payload ? JSON.stringify(source.control_payload) : ''
  )
  const [contentType, setContentType] = useState(source.content_type || 'json')
  const [saving, setSaving] = useState(false)

  const handleDelete = async () => {
    if (!confirm(`Delete source "${source.id}"?`)) return
    try {
      await apiFetch(`/api/clients/${clientId}/sources/${source.id}`, { method: 'DELETE' })
      onDelete()
    } catch (e) {
      alert(`Delete failed: ${e.message}`)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    let parsedPayload = null
    if (payload.trim()) {
      try { parsedPayload = JSON.parse(payload) } catch { parsedPayload = payload }
    }
    try {
      await apiFetch(`/api/clients/${clientId}/sources/${source.id}`, {
        method: 'PUT',
        body: JSON.stringify({
          label: label.trim(),
          control_api: apiUrl.trim(),
          control_payload: parsedPayload,
          content_type: contentType,
        }),
      })
      setEditing(false)
      onUpdate()
    } catch (e) {
      alert(`Save failed: ${e.message}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={`fx-source-item${editing ? ' expanded' : ''}`}>
      <div className="fx-source-row">
        <div className="fx-source-info">
          <span className="fx-source-label">
            <span className="fx-source-icon"><SourceIcon source={source} /></span>
            <span>{source.label || source.id}</span>
          </span>
          <span className="fx-row" style={{ gap: 'var(--fx-1)' }}>
            <span className="fx-badge">External</span>
            {source.control_api && (
              <span className="fx-source-api-hint">{source.control_api}</span>
            )}
          </span>
        </div>
        <div className="fx-source-actions">
          <button
            className={`fx-icon-btn sm${editing ? ' active' : ''}`}
            onClick={() => setEditing(!editing)}
            title="Edit"
            aria-label="Edit"
          >
            <Settings2 size={14} />
          </button>
          <button
            className="fx-icon-btn sm danger"
            onClick={handleDelete}
            title="Delete"
            aria-label="Delete"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>
      {editing && (
        <div className="fx-source-form">
          <div>
            <label className="fx-label">Label</label>
            <input className="fx-input" type="text" value={label} onChange={e => setLabel(e.target.value)} />
          </div>
          <div>
            <label className="fx-label">API URL</label>
            <input className="fx-input" type="url" value={apiUrl} onChange={e => setApiUrl(e.target.value)} placeholder="https://…" />
          </div>
          <div>
            <label className="fx-label">Payload</label>
            <textarea
              className="fx-textarea"
              rows={2}
              value={payload}
              onChange={e => setPayload(e.target.value)}
              placeholder={contentType === 'form' ? '{"arg": "value"}' : '{"source": "vinyl"}'}
            />
          </div>
          <div>
            <label className="fx-label">Encoding</label>
            <select className="fx-select" value={contentType} onChange={e => setContentType(e.target.value)}>
              <option value="json">JSON</option>
              <option value="form">Form (x-www-form-urlencoded)</option>
            </select>
          </div>
          <div>
            <button className="fx-btn primary" onClick={handleSave} disabled={saving}>
              {saving ? 'Saving…' : <><Check size={14} /> Save</>}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

/**
 * Inline new-source form. Now opens from the + menu rather than living
 * as a perma disclosure below the list.
 */
function AddCustomSourceForm({ clientId, onAdded, onCancel }) {
  const [id, setId] = useState('')
  const [label, setLabel] = useState('')
  const [apiUrl, setApiUrl] = useState('')
  const [payload, setPayload] = useState('')
  const [contentType, setContentType] = useState('json')
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!id.trim() || !label.trim()) return
    setSubmitting(true)
    const source = {
      id: id.trim(), label: label.trim(),
      type: 'external', category: 'custom',
      control_api: apiUrl.trim(),
      content_type: contentType,
    }
    if (payload.trim()) {
      try { source.control_payload = JSON.parse(payload) } catch { source.control_payload = payload }
    }
    try {
      await apiFetch(`/api/clients/${clientId}/sources`, {
        method: 'POST',
        body: JSON.stringify(source),
      })
      onAdded()
    } catch (e) {
      alert(`Add failed: ${e.message}`)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="fx-stack fx-add-source-form">
      <div className="fx-row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
        <span className="fx-h3">New custom source</span>
        <button type="button" className="fx-icon-btn sm" onClick={onCancel} aria-label="Cancel">
          <X size={14} />
        </button>
      </div>
      <div>
        <label className="fx-label">Source ID</label>
        <input className="fx-input" type="text" value={id} onChange={e => setId(e.target.value)} required placeholder="vinyl" />
      </div>
      <div>
        <label className="fx-label">Label</label>
        <input className="fx-input" type="text" value={label} onChange={e => setLabel(e.target.value)} required placeholder="Vinyl" />
      </div>
      <div>
        <label className="fx-label">API URL</label>
        <input className="fx-input" type="url" value={apiUrl} onChange={e => setApiUrl(e.target.value)} placeholder="https://…" />
      </div>
      <div>
        <label className="fx-label">Payload</label>
        <textarea
          className="fx-textarea"
          rows={3}
          value={payload}
          onChange={e => setPayload(e.target.value)}
          placeholder={contentType === 'form' ? '{"arg": "value"}' : '{"source": "vinyl"}'}
        />
      </div>
      <div>
        <label className="fx-label">Encoding</label>
        <select className="fx-select" value={contentType} onChange={e => setContentType(e.target.value)}>
          <option value="json">JSON</option>
          <option value="form">Form (x-www-form-urlencoded)</option>
        </select>
      </div>
      <div>
        <button type="submit" className="fx-btn primary" disabled={submitting}>
          <Plus size={14} /> Add custom source
        </button>
      </div>
    </form>
  )
}

/**
 * Advanced Settings — currently just DAC overlay. Collapsed by default
 * because a wrong overlay choice can leave the Pi without audio until
 * recovery, so we want it out of the casual-tweak path.
 */
function AdvancedSettings({ client, overlays, onRefresh }) {
  const [open, setOpen] = useState(false)
  const [selectedOverlay, setSelectedOverlay] = useState(client.dac_overlay || '')
  const [applying, setApplying] = useState(false)
  const [applyMessage, setApplyMessage] = useState(null)
  const [rebootingUntil, setRebootingUntil] = useState(0)

  useEffect(() => {
    setSelectedOverlay(client.dac_overlay || '')
  }, [client.dac_overlay])

  const overlayLocked = !!client.dac_overlay_locked
  const overlayDirty = selectedOverlay && selectedOverlay !== client.dac_overlay
  const isRebooting = rebootingUntil > Date.now()

  // While a reboot is in progress poll every 5s so connectivity flips
  // back to green without manual refresh. Tear down on unmount.
  useEffect(() => {
    if (!isRebooting) return undefined
    const t = setInterval(() => onRefresh?.(), 5000)
    const stop = setTimeout(() => setRebootingUntil(0), Math.max(rebootingUntil - Date.now(), 0))
    return () => { clearInterval(t); clearTimeout(stop) }
  }, [isRebooting, rebootingUntil, onRefresh])

  const handleApplyOverlay = useCallback(async () => {
    if (overlayLocked) return
    setApplying(true)
    setApplyMessage(null)
    try {
      const j = await apiFetch(`/api/clients/${client.client_id}/dac_overlay/apply`, {
        method: 'POST',
        body: JSON.stringify({ dac_overlay: selectedOverlay }),
      })
      const seconds = j?.expected_reboot_seconds || 60
      setRebootingUntil(Date.now() + seconds * 1000)
      setApplyMessage(`Rebooting (~${seconds}s)…`)
      onRefresh?.()
    } catch (e) {
      setApplyMessage(`Failed: ${e.message}`)
    } finally {
      setApplying(false)
    }
  }, [client.client_id, selectedOverlay, overlayLocked, onRefresh])

  return (
    <>
      <div className="fx-section-label">
        <span>Advanced settings</span>
        <button
          className="fx-icon-btn sm"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          title={open ? 'Collapse' : 'Expand'}
        >
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </button>
      </div>
      {open && (
        <div className="fx-panel-card fx-advanced-body">
          <RemoteControlSection client={client} />
          <div className="fx-advanced-section">
            <div className="fx-advanced-title">Choose the audio hat this device uses</div>
            <div className="fx-row" style={{ gap: 'var(--fx-2)', marginTop: 'var(--fx-3)' }}>
              <select
                className="fx-select"
                value={selectedOverlay || ''}
                disabled={overlayLocked || applying || isRebooting}
                onChange={e => setSelectedOverlay(e.target.value)}
                title={overlayLocked
                  ? "Server hardware overlay is locked (analog-input detection in install.sh keys off this exact value)."
                  : "Pick the matching DAC HAT and press Apply to reboot."
                }
                style={{ flex: 1, minWidth: 0 }}
              >
                {(overlays || []).map(o => (
                  <option key={o.id} value={o.id}>{o.label}</option>
                ))}
                {selectedOverlay && !overlays?.some(o => o.id === selectedOverlay) && (
                  <option value={selectedOverlay}>{selectedOverlay} (custom)</option>
                )}
              </select>
              <button
                className={overlayDirty ? 'fx-btn primary' : 'fx-btn'}
                disabled={overlayLocked || applying || isRebooting || !selectedOverlay}
                onClick={handleApplyOverlay}
                title="Rewrite /boot/firmware/config.txt and reboot. Device offline for ~60s."
              >
                {applying ? 'Applying…' : isRebooting ? 'Rebooting…' : (overlayDirty ? 'Apply + reboot' : 'Re-apply')}
              </button>
            </div>
            {selectedOverlay && (
              <code className="fx-mono fx-overlay-code">dtoverlay={selectedOverlay}</code>
            )}
            {applyMessage && (
              <div className="fx-small" style={{ marginTop: 'var(--fx-2)', color: applyMessage.startsWith('Failed') ? 'var(--fx-err)' : 'var(--fx-text-2)' }}>
                {applyMessage}
              </div>
            )}
            {overlayLocked && (
              <p className="fx-small fx-mute" style={{ marginTop: 'var(--fx-2)' }}>
                Locked: install.sh's analog-input detection keys off this exact value.
              </p>
            )}
          </div>
        </div>
      )}
    </>
  )
}

// Canonical IR command list — must match COMMAND_IDS in
// client/modules/ir_listener.py and server IR_COMMAND_IDS.
const IR_COMMANDS = [
  { id: 'volume_up',    label: 'Volume up' },
  { id: 'volume_down',  label: 'Volume down' },
  { id: 'mute',         label: 'Mute' },
  { id: 'source_cycle', label: 'Source' },
  { id: 'play_pause',   label: 'Play / Pause' },
  { id: 'next',         label: 'Next' },
  { id: 'previous',     label: 'Previous' },
]

const LEARN_TIMEOUT_S = 15

/**
 * Remote control (hardware IR) settings — toggle + per-command learn UI.
 *
 * Flow:
 *  - Mount fetches /api/clients/<id>/ir for initial mirror state.
 *  - SSE /api/clients/<id>/ir/stream pushes learn lifecycle events
 *    (started / captured / timeout / cancelled / rejected). Captures
 *    carry the protocol + scancode so we update the row in place
 *    without a refetch.
 *  - Toggling the checkbox PUTs {enabled:bool}. The client echoes the
 *    new state back via MQTT and the next stream snapshot reflects it,
 *    but we optimistically flip the checkbox so it feels instant.
 *  - Learn buttons POST /api/clients/<id>/ir/learn — server publishes
 *    the MQTT start command and the client takes over. The button
 *    flips to Cancel until a terminal lifecycle event arrives.
 */
function RemoteControlSection({ client }) {
  const [enabled, setEnabled] = useState(false)
  const [mappings, setMappings] = useState({})
  const [learningCommand, setLearningCommand] = useState(null)
  const [feedbackVolume, setFeedbackVolume] = useState(30)
  const [loading, setLoading] = useState(true)
  const [errorMsg, setErrorMsg] = useState(null)
  // Debounce ref for the feedback-volume slider — only commit (PUT) the
  // last value after 200ms of no movement, so dragging doesn't spam
  // preview-sound playbacks on the device.
  const feedbackDebounceRef = useRef(null)

  // Initial load — gives us the persisted mappings even if the SSE
  // stream hasn't delivered a snapshot yet (no learn ever happened).
  useEffect(() => {
    let cancelled = false
    apiFetch(`/api/clients/${client.client_id}/ir`)
      .then(j => {
        if (cancelled) return
        const ir = j?.ir || {}
        setEnabled(!!ir.enabled)
        setMappings(ir.mappings || {})
        if (typeof ir.feedback_volume === 'number') {
          setFeedbackVolume(ir.feedback_volume)
        }
      })
      .catch(e => { if (!cancelled) setErrorMsg(e.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [client.client_id])

  // SSE — keeps learn state in lockstep with the device. We only
  // process the `learn_event` and `snapshot` events; the latter is
  // just the last learn_event replayed for late subscribers.
  useEffect(() => {
    if (!client.client_id) return undefined
    const es = new EventSource(`/api/clients/${client.client_id}/ir/stream`)
    const handler = (e) => {
      let data
      try { data = JSON.parse(e.data) } catch { return }
      const ev = data?.event
      if (ev === 'started') {
        setLearningCommand(data.command_id)
      } else if (ev === 'captured') {
        setLearningCommand(prev => prev === data.command_id ? null : prev)
        setMappings(prev => ({
          ...prev,
          [data.command_id]: { protocol: data.protocol, scancode: data.scancode },
        }))
      } else if (ev === 'timeout' || ev === 'cancelled' || ev === 'rejected') {
        setLearningCommand(prev => prev === data.command_id ? null : prev)
      }
    }
    es.addEventListener('learn_event', handler)
    es.addEventListener('snapshot', handler)
    es.onerror = () => { /* EventSource auto-reconnects; nothing to do */ }
    return () => es.close()
  }, [client.client_id])

  const toggleEnabled = useCallback(async () => {
    const next = !enabled
    setEnabled(next)  // optimistic
    try {
      await apiFetch(`/api/clients/${client.client_id}/ir`, {
        method: 'PUT',
        body: JSON.stringify({ enabled: next }),
      })
    } catch (e) {
      setEnabled(!next)  // revert
      setErrorMsg(`Failed to ${next ? 'enable' : 'disable'} remote: ${e.message}`)
    }
  }, [client.client_id, enabled])

  const startLearn = useCallback(async (commandId) => {
    setErrorMsg(null)
    setLearningCommand(commandId)  // optimistic
    try {
      await apiFetch(`/api/clients/${client.client_id}/ir/learn`, {
        method: 'POST',
        body: JSON.stringify({ command_id: commandId, timeout_s: LEARN_TIMEOUT_S }),
      })
    } catch (e) {
      setLearningCommand(null)
      setErrorMsg(`Learn failed: ${e.message}`)
    }
  }, [client.client_id])

  const cancelLearn = useCallback(async () => {
    try {
      await apiFetch(`/api/clients/${client.client_id}/ir/learn/cancel`, {
        method: 'POST',
      })
    } catch (e) {
      setErrorMsg(`Cancel failed: ${e.message}`)
    }
  }, [client.client_id])

  const clearCommand = useCallback(async (commandId) => {
    setMappings(prev => ({ ...prev, [commandId]: null }))  // optimistic
    try {
      await apiFetch(`/api/clients/${client.client_id}/ir`, {
        method: 'PUT',
        body: JSON.stringify({ clear: commandId }),
      })
    } catch (e) {
      setErrorMsg(`Clear failed: ${e.message}`)
    }
  }, [client.client_id])

  const onFeedbackVolumeChange = useCallback((newVal) => {
    setFeedbackVolume(newVal)  // optimistic visual
    // Debounce the PUT so a slider drag doesn't fire dozens of preview
    // sounds. After 200ms of no movement, send the settled value and
    // the device plays one preview at the new level.
    if (feedbackDebounceRef.current) clearTimeout(feedbackDebounceRef.current)
    feedbackDebounceRef.current = setTimeout(() => {
      apiFetch(`/api/clients/${client.client_id}/ir`, {
        method: 'PUT',
        body: JSON.stringify({ feedback_volume: newVal }),
      }).catch(e => setErrorMsg(`Feedback volume failed: ${e.message}`))
    }, 200)
  }, [client.client_id])

  return (
    <div className="fx-advanced-section">
      <label className="fx-ir-toggle">
        <input
          type="checkbox"
          checked={enabled}
          disabled={loading}
          onChange={toggleEnabled}
        />
        <span className="fx-advanced-title" style={{ margin: 0 }}>Remote control</span>
      </label>
      {!enabled && !loading && (
        <p className="fx-small fx-mute" style={{ marginTop: 'var(--fx-2)' }}>
          Wire a 38 kHz IR receiver (e.g. VS1838B) to GPIO17 / 3V3 / GND and enable
          to teach this device a remote.
        </p>
      )}
      {enabled && (
        <>
          <div className="fx-source-setting" style={{ marginTop: 'var(--fx-2)' }}>
            <span className="fx-source-setting-label">
              Feedback volume <span className="fx-mute" style={{ fontVariantNumeric: 'tabular-nums' }}>{feedbackVolume}%</span>
            </span>
            <div className="fx-volume accent fx-volume-compact">
              <div className="fx-volume-track">
                <div className="fx-volume-fill" style={{ width: `${feedbackVolume}%` }} />
                <div className="fx-volume-thumb" style={{ left: `${feedbackVolume}%` }} />
                <input
                  className="fx-volume-input"
                  type="range"
                  min={0}
                  max={100}
                  step={1}
                  value={feedbackVolume}
                  onChange={e => onFeedbackVolumeChange(parseInt(e.target.value, 10))}
                  aria-label="Feedback volume"
                />
              </div>
            </div>
          </div>
          <div className="fx-ir-rows">
            {IR_COMMANDS.map(c => (
              <IrCommandRow
                key={c.id}
                label={c.label}
                mapping={mappings[c.id]}
                learning={learningCommand === c.id}
                disabled={learningCommand !== null && learningCommand !== c.id}
                onLearn={() => startLearn(c.id)}
                onCancel={cancelLearn}
                onClear={() => clearCommand(c.id)}
              />
            ))}
          </div>
        </>
      )}
      {errorMsg && (
        <div className="fx-small" style={{ marginTop: 'var(--fx-2)', color: 'var(--fx-err)' }}>
          {errorMsg}
        </div>
      )}
    </div>
  )
}

function IrCommandRow({ label, mapping, learning, disabled, onLearn, onCancel, onClear }) {
  const valueText = learning
    ? 'Learning…'
    : (mapping
        ? `${(mapping.protocol || '?').toUpperCase()} ${mapping.scancode || ''}`
        : '—')

  return (
    <div className="fx-ir-row">
      <span className="fx-ir-label">{label}</span>
      <code className={`fx-mono fx-ir-value ${learning ? 'learning' : ''} ${mapping && !learning ? 'set' : ''}`}>
        {valueText}
      </code>
      <div className="fx-ir-actions">
        {learning ? (
          <button className="fx-btn" onClick={onCancel}>Cancel</button>
        ) : (
          <>
            {mapping && (
              <button
                className="fx-icon-btn sm"
                onClick={onClear}
                disabled={disabled}
                title="Forget this mapping"
              >
                <X size={14} />
              </button>
            )}
            <button
              className="fx-btn"
              onClick={onLearn}
              disabled={disabled}
              title={disabled ? 'Cancel the in-flight learn first' : 'Press a button on your remote after clicking'}
            >
              {mapping ? 'Re-learn' : 'Learn'}
            </button>
          </>
        )}
      </div>
    </div>
  )
}

function RemoveDeviceButton({ client, onRemoved }) {
  const handleRemove = useCallback(async () => {
    if (!confirm(`Remove device ${client.client_id}? This cannot be undone.`)) return
    try {
      await apiFetch(`/api/clients/${client.client_id}`, { method: 'DELETE' })
      onRemoved?.()
    } catch (e) {
      alert(`Remove failed: ${e.message}`)
    }
  }, [client.client_id, onRemoved])

  return (
    <button className="fx-btn danger" onClick={handleRemove}>
      <Trash2 size={14} /> Remove device
    </button>
  )
}
