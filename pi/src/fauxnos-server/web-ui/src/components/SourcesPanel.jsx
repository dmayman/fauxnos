import { useState, useEffect, useCallback } from 'react'
import { apiFetch } from '../api'

const BUILTIN_DEFS = [
  { id: 'spotify', label: 'Spotify', vc: 'snapcast' },
  { id: 'airplay', label: 'AirPlay', vc: 'snapcast' },
]
const ANALOG_DEF = { id: 'analog', label: 'Analog In', vc: 'self' }

export default function SourcesPanel({ clientId, clientName, onClose }) {
  const [sources, setSources] = useState([])
  const [hasAdc, setHasAdc] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const loadSources = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiFetch(`/api/clients/${clientId}/sources`)
      setSources(data.sources || [])
      setHasAdc(data.has_adc || false)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [clientId])

  useEffect(() => { loadSources() }, [loadSources])

  const defaultSources = sources.filter(s => s.category === 'default')
  const customSources = sources.filter(s => s.category !== 'default')

  const defs = [...BUILTIN_DEFS, ...(hasAdc ? [ANALOG_DEF] : [])]
  const builtIns = defs.map(def =>
    defaultSources.find(s => s.id === def.id) || {
      id: def.id, label: def.label, type: 'internal', category: 'default',
      sink: def.id === 'analog' ? 'analogsink' : 'snapsink',
      starting_volume: 50, volume_controller: def.vc,
    }
  )

  return (
    <div className="side-panel open">
      <div className="side-panel-header">
        <h3>Sources — {clientName}</h3>
        <button className="close-btn" onClick={onClose}>&times;</button>
      </div>

      {loading && <p className="loading">Loading sources...</p>}
      {error && <p className="loading">Error: {error}</p>}

      {!loading && !error && (
        <>
          <div className="source-section-header">Built-in Sources</div>
          {builtIns.map(s => (
            <BuiltInSourceRow key={s.id} source={s} clientId={clientId} onUpdate={loadSources} />
          ))}

          <div className="source-section-header" style={{ marginTop: 16 }}>Custom Sources</div>
          {customSources.length === 0 && (
            <p className="source-empty-hint">No custom sources configured.</p>
          )}
          {customSources.map(s => (
            <CustomSourceRow key={s.id} source={s} clientId={clientId} onDelete={loadSources} onUpdate={loadSources} />
          ))}

          <AddCustomSourceForm clientId={clientId} onAdded={loadSources} />
        </>
      )}
    </div>
  )
}

function BuiltInSourceRow({ source, clientId, onUpdate }) {
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

  const vc = source.volume_controller === 'self' ? 'self' : 'snapcast'

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
    <>
      <div className="source-row source-default">
        <div className="source-info">
          <span className="source-label">{source.label || source.id}</span>
          <span className="source-meta">
            <span className="badge badge-blue">internal &middot; {vc}</span>
          </span>
        </div>
        <button
          className={`btn-icon source-gear${expanded ? ' source-gear-active' : ''}`}
          onClick={() => setExpanded(!expanded)}
          title="Configure external switch"
        >
          &#9881;
        </button>
      </div>
      {expanded && (
        <div className="source-ext-form">
          <label className="source-ext-toggle">
            <input
              type="checkbox"
              checked={enabled}
              onChange={e => setEnabled(e.target.checked)}
            />
            Call external API when selected
          </label>
          {enabled && (
            <div className="ext-fields">
              <label>
                API URL
                <input type="url" value={url} onChange={e => setUrl(e.target.value)} placeholder="https://..." />
              </label>
              <label>
                Payload
                <textarea
                  rows={2}
                  value={payload}
                  onChange={e => setPayload(e.target.value)}
                  placeholder={contentType === 'form' ? '{"arg": "fauxnos"}' : '{"source": "fauxnos"}'}
                />
              </label>
              <label>
                Encoding
                <select value={contentType} onChange={e => setContentType(e.target.value)}>
                  <option value="json">JSON</option>
                  <option value="form">Form (x-www-form-urlencoded)</option>
                </select>
              </label>
              <button className="btn-primary" onClick={handleSave} disabled={saving}>
                {saved ? 'Saved \u2713' : 'Save'}
              </button>
            </div>
          )}
        </div>
      )}
    </>
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
    <>
      <div className="source-row">
        <div className="source-info">
          <span className="source-label">{source.label || source.id}</span>
          <span className="source-meta">
            <span className="badge badge-grey">external</span>
            {source.control_api && (
              <span className="source-api-hint">{source.control_api}</span>
            )}
          </span>
        </div>
        <div style={{ display: 'flex', gap: 2 }}>
          <button
            className={`btn-icon source-gear${editing ? ' source-gear-active' : ''}`}
            onClick={() => setEditing(!editing)}
            title="Edit"
          >
            &#9881;
          </button>
          <button className="btn-icon" onClick={handleDelete} title="Delete">&times;</button>
        </div>
      </div>
      {editing && (
        <div className="source-ext-form">
          <div className="ext-fields">
            <label>
              Label
              <input type="text" value={label} onChange={e => setLabel(e.target.value)} />
            </label>
            <label>
              API URL
              <input type="url" value={apiUrl} onChange={e => setApiUrl(e.target.value)} placeholder="https://..." />
            </label>
            <label>
              Payload
              <textarea
                rows={2}
                value={payload}
                onChange={e => setPayload(e.target.value)}
                placeholder={contentType === 'form' ? '{"arg": "value"}' : '{"source": "vinyl"}'}
              />
            </label>
            <label>
              Encoding
              <select value={contentType} onChange={e => setContentType(e.target.value)}>
                <option value="json">JSON</option>
                <option value="form">Form (x-www-form-urlencoded)</option>
              </select>
            </label>
            <button className="btn-primary" onClick={handleSave} disabled={saving}>
              {saving ? 'Saving...' : 'Save'}
            </button>
          </div>
        </div>
      )}
    </>
  )
}

function AddCustomSourceForm({ clientId, onAdded }) {
  const [open, setOpen] = useState(false)
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
      setId(''); setLabel(''); setApiUrl(''); setPayload(''); setContentType('json')
      setOpen(false)
      onAdded()
    } catch (e) {
      alert(`Add failed: ${e.message}`)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="add-source-form" style={{ marginTop: 16 }}>
      <div
        className="add-source-toggle"
        onClick={() => setOpen(!open)}
      >
        {open ? '−' : '+'} Add Custom Source
      </div>
      {open && (
        <form onSubmit={handleSubmit} style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <label>Source ID <input type="text" value={id} onChange={e => setId(e.target.value)} required placeholder="vinyl" /></label>
          <label>Label <input type="text" value={label} onChange={e => setLabel(e.target.value)} required placeholder="Vinyl" /></label>
          <label>API URL <input type="url" value={apiUrl} onChange={e => setApiUrl(e.target.value)} placeholder="https://" /></label>
          <label>Payload <textarea rows={3} value={payload} onChange={e => setPayload(e.target.value)} placeholder={contentType === 'form' ? '{"arg": "value"}' : '{"source": "vinyl"}'} /></label>
          <label>Encoding
            <select value={contentType} onChange={e => setContentType(e.target.value)}>
              <option value="json">JSON</option>
              <option value="form">Form (x-www-form-urlencoded)</option>
            </select>
          </label>
          <button type="submit" className="btn-primary" disabled={submitting}>Add Custom Source</button>
        </form>
      )}
    </div>
  )
}
