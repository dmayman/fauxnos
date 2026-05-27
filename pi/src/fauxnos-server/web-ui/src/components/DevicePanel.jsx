import { useState, useEffect, useCallback, useRef, Suspense, lazy } from 'react'

const LazyCustomIcon = lazy(() => import('./CustomIcon'))
const LazyIconPickerButton = lazy(() => import('./IconPickerButton'))
import {
  IconBrandSpotifyFilled,
  IconBuildingBroadcastTowerFilled,
  IconMicrophoneFilled,
  IconExternalLinkFilled,
  IconHeadphonesFilled,
  IconXFilled,
  IconAdjustmentsFilled,
  IconPlusFilled,
  IconChevronDownFilled,
  IconChevronRightFilled,
  IconCheckFilled,
  IconTrashFilled,
  IconDownloadFilled,
  IconGitBranch,
  IconWorldFilled,
  IconHelpCircleFilled,
  IconPlug,
  IconPlayerRecordFilled,
  IconPlayerStopFilled,
} from '@tabler/icons-react'
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

// Built-in source definitions. Spotify + AirPlay are always shown
// (shairport-sync is installed on every fauxnos device by install.sh,
// so AirPlay is a first-class default). Analog is gated by has_adc
// and can be added/removed via the + menu — clicking + Analog In
// flips has_adc=true server-side and re-renders.
const BUILTIN_DEFS = [
  { id: 'spotify', label: 'Spotify',   vc: 'snapcast', alwaysOn: true },
  { id: 'airplay', label: 'AirPlay',   vc: 'external', alwaysOn: true },
  { id: 'analog',  label: 'Analog In', vc: 'self',     gatedBy: 'has_adc' },
]

/**
 * Maps a source id (or category for non-default sources) to a recognizable
 * glyph. Used in source row labels and the + menu to give each option a
 * visual anchor.
 */
function SourceIcon({ source, size = 16 }) {
  const id = source?.id
  const FallbackIcon =
    id === 'spotify' ? IconBrandSpotifyFilled :
    id === 'airplay' ? IconBuildingBroadcastTowerFilled :
    id === 'analog'  ? IconMicrophoneFilled :
    id ? IconExternalLinkFilled :
    IconHeadphonesFilled
  if (source?.icon) {
    return (
      <Suspense fallback={<FallbackIcon size={size} aria-hidden />}>
        <LazyCustomIcon name={source.icon} size={size} />
      </Suspense>
    )
  }
  return <FallbackIcon size={size} aria-hidden />
}

function hostnameOf(url) {
  if (!url) return ''
  let host
  try {
    const u = /^https?:\/\//i.test(url) ? new URL(url) : new URL(`http://${url}`)
    host = u.hostname
  } catch {
    return url
  }
  const parts = host.split('.')
  return parts.length > 2 ? parts.slice(-2).join('.') : host
}

function HelpPopover({ children }) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef(null)
  useEffect(() => {
    if (!open) return undefined
    const handler = (e) => {
      if (!wrapRef.current?.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])
  return (
    <div className="fx-help-wrap" ref={wrapRef}>
      <button
        type="button"
        className="fx-icon-btn sm"
        onClick={() => setOpen(v => !v)}
        title="Help"
        aria-label="Help"
        aria-expanded={open}
      >
        <IconHelpCircleFilled size={14} />
      </button>
      {open && <div className="fx-popover fx-help-popover">{children}</div>}
    </div>
  )
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
export default function DevicePanel({ client, mqtt, onClose, onRefresh, onUpdateClient, serverVersion }) {
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
                <IconPlusFilled size={14} />
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
                    <IconPlug size={14} aria-hidden />
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

          <EqualizerSection client={client} />

          <VersionSection
            client={client}
            serverVersion={serverVersion}
            onUpdateClient={onUpdateClient}
          />

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

/**
 * Per-device version + update affordance.
 *
 * Sits between AdvancedSettings and the remove-device footer. Shows what
 * SHA this device's client install was last deployed to (deployed_client_sha),
 * when, and whether it lags the client-subtree tip on origin/main.
 *
 * Phase F1 (2026-05-13): fauxnos000 is rendered here like any other
 * client — its client install is updated through the same UpdateRunner
 * orchestrator, just using a local subprocess instead of SSH. The
 * server's source tree is updated separately via the header "Update
 * server" button (git pull + fauxnos-server restart).
 *
 * The inline Update button kicks off a single-device update. Hidden
 * when the device is offline or when it's already at the client tip.
 */
function VersionSection({ client, serverVersion, onUpdateClient }) {
  const [open, setOpen] = useState(false)
  const deploy = client.deploy
  const deployedShort = deploy?.deployed_client_sha_short
  const deployedAt = deploy?.deployed_at
  const behind = deploy?.commits_behind
  const everDeployed = !!deploy?.deployed_client_sha
  const serverShort = serverVersion?.short_sha
  const canUpdate = !!onUpdateClient && client.connected
  const needsUpdate = !everDeployed || (behind !== null && behind > 0)

  return (
    <div className="fx-device-version-section">
      <div
        className="fx-section-label fx-section-label-clickable"
        role="button"
        tabIndex={0}
        onClick={() => setOpen(v => !v)}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpen(v => !v) } }}
        aria-expanded={open}
      >
        <span>Version</span>
        <button
          className="fx-icon-btn sm"
          onClick={(e) => { e.stopPropagation(); setOpen(!open) }}
          aria-expanded={open}
          title={open ? 'Collapse' : 'Expand'}
        >
          {open ? <IconChevronDownFilled size={14} /> : <IconChevronRightFilled size={14} />}
        </button>
      </div>
      {open && (() => {
        let statusKind, statusText
        if (!everDeployed) {
          statusKind = 'warn'
          statusText = 'Never deployed via the update pipeline.'
        } else if (behind === null) {
          statusKind = 'warn'
          statusText = "Stored SHA isn't in the server's git history."
        } else if (behind > 0 && !canUpdate) {
          statusKind = 'err'
          statusText = `${behind} commit${behind === 1 ? '' : 's'} behind — device offline.`
        } else if (behind > 0) {
          statusKind = 'warn'
          statusText = `${behind} commit${behind === 1 ? '' : 's'} behind the server.`
        } else {
          statusKind = 'ok'
          statusText = 'Up to date with the server.'
        }
        return (
          <div className="fx-panel-card fx-device-version-card">
            <div className={`fx-version-status fx-version-status-${statusKind}`}>
              <IconCheckFilled size={12} aria-hidden />
              <span>{statusText}</span>
            </div>
            <div className="fx-row fx-device-version-row">
              <span className="fx-mute fx-device-version-label">Deployed</span>
              <span className="fx-mono fx-device-version-value">
                <IconGitBranch size={12} aria-hidden />
                {deployedShort || '—'}
              </span>
            </div>
            <div className="fx-row fx-device-version-row">
              <span className="fx-mute fx-device-version-label">Server is at</span>
              <span className="fx-mono fx-device-version-value">{serverShort || '—'}</span>
            </div>
            {deployedAt && (
              <div className="fx-row fx-device-version-row">
                <span className="fx-mute fx-device-version-label">Last update</span>
                <span className="fx-device-version-value">{formatRelativeTime(deployedAt)}</span>
              </div>
            )}
            {needsUpdate && canUpdate && (
              <button
                type="button"
                className="fx-btn fx-device-version-btn"
                onClick={() => onUpdateClient(client)}
              >
                <IconDownloadFilled size={14} />
                <span>
                  {everDeployed
                    ? `Update this device${behind > 0 ? ` (${behind} behind)` : ''}`
                    : 'Run first update'}
                </span>
              </button>
            )}
          </div>
        )
      })()}
    </div>
  )
}

function formatRelativeTime(iso) {
  try {
    const then = new Date(iso).getTime()
    const now = Date.now()
    const seconds = Math.max(0, Math.round((now - then) / 1000))
    if (seconds < 60) return `${seconds}s ago`
    const minutes = Math.round(seconds / 60)
    if (minutes < 60) return `${minutes}m ago`
    const hours = Math.round(minutes / 60)
    if (hours < 24) return `${hours}h ago`
    const days = Math.round(hours / 24)
    if (days < 30) return `${days}d ago`
    return new Date(iso).toLocaleDateString()
  } catch {
    return iso
  }
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
        <IconXFilled size={18} />
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

  // Pretty label per volume_controller. The badge tells the operator
  // who owns the audio attenuation for this source — useful debug
  // surface when something sounds two-stage or unresponsive. Anything
  // unknown falls back to the raw value so the badge isn't silently
  // wrong (the old code mapped EVERYTHING non-'self' to 'Snapcast',
  // which mislabeled both go_librespot and external sources).
  const VC_LABELS = {
    self: 'Self',
    snapcast: 'Snapcast',
    go_librespot: 'Spotify Connect',
    external: 'External',
  }
  const vcLabel = VC_LABELS[source.volume_controller] || source.volume_controller || 'Self'

  // Calibration is stored on the client as PulseAudio percent 0-200
  // (100 = unity, <100 = cut, >100 = software boost via pactl). The UI
  // exposes that as a center-notched slider: display value is `cal-100`,
  // so the user sees -100..0..+100 with 0 meaning "no change". On the
  // way out we add 100 back to land in PA percent. Snaps to 0 within a
  // small dead-zone so the notch detents cleanly.
  const calLive = mqtt?.calibrations?.[clientId]?.[source.id]
  const calibration = (typeof calLive === 'number') ? calLive : 100
  const displayCal = calibration - 100  // -100..+100, 0 = unity
  // Thumb position 0-100% across the track (calibration 0→0%, 100→50%, 200→100%).
  const thumbPct = calibration / 2
  // Center-anchored fill: from 50% outward toward the thumb.
  const fillLeftPct = calibration >= 100 ? 50 : thumbPct
  const fillWidthPct = Math.abs(displayCal) / 2
  const handleCalibrationChange = (e) => {
    let v = parseInt(e.target.value, 10)
    if (!Number.isFinite(v)) return
    // Dead-zone snap to 0 (unity) so the notch actually catches.
    if (Math.abs(v) <= 2) v = 0
    if (mqtt?.publishCalibration) {
      mqtt.publishCalibration(clientId, source.id, v + 100)
    }
  }
  const calLabel = displayCal === 0
    ? '0'
    : (displayCal > 0 ? `+${displayCal}` : `${displayCal}`)

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
      <div
        className="fx-source-row fx-source-row-clickable"
        role="button"
        tabIndex={0}
        onClick={() => setExpanded(v => !v)}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setExpanded(v => !v) } }}
        aria-expanded={expanded}
      >
        <div className="fx-source-info">
          <span className="fx-source-label">
            <span className="fx-source-icon"><SourceIcon source={source} /></span>
            <span>{source.label || source.id}</span>
          </span>
        </div>
        <div className="fx-source-actions">
          <button
            className={`fx-icon-btn sm${expanded ? ' active' : ''}`}
            onClick={(e) => { e.stopPropagation(); setExpanded(!expanded) }}
            title="Configure"
            aria-label="Configure"
          >
            <IconAdjustmentsFilled size={14} />
          </button>
          {removable && (
            <button
              className="fx-icon-btn sm danger"
              onClick={(e) => { e.stopPropagation(); onRemove() }}
              title="Remove"
              aria-label="Remove this built-in source"
            >
              <IconTrashFilled size={14} />
            </button>
          )}
        </div>
      </div>
      {expanded && (
        <div className="fx-source-form">
          <div className="fx-source-setting">
            <span className="fx-source-setting-label">
              Volume calibration
              <span className="fx-source-setting-value">{calLabel}</span>
            </span>
            <div className="fx-volume accent fx-volume-compact">
              <div className="fx-volume-track">
                {/* Center notch (0 = unity gain detent). */}
                <div className="fx-volume-notch" />
                <div
                  className="fx-volume-fill"
                  style={{ left: `${fillLeftPct}%`, right: 'auto', width: `${fillWidthPct}%` }}
                />
                <div className="fx-volume-thumb" style={{ left: `${thumbPct}%` }} />
                <input
                  className="fx-volume-input"
                  type="range"
                  min={-100}
                  max={100}
                  step={1}
                  value={displayCal}
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
                  {saved ? <><IconCheckFilled size={14} /> Saved</> : <><IconCheckFilled size={14} /> Save</>}
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
  const [icon, setIcon] = useState(source.icon || '')
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
          icon: icon || null,
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
      <div
        className="fx-source-row fx-source-row-clickable"
        role="button"
        tabIndex={0}
        onClick={() => setEditing(v => !v)}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setEditing(v => !v) } }}
        aria-expanded={editing}
      >
        <div className="fx-source-info">
          <span className="fx-source-label">
            <span className="fx-source-icon"><SourceIcon source={source} /></span>
            <span>{source.label || source.id}</span>
            <span className="fx-badge">
              <IconWorldFilled size={12} aria-hidden />
              {hostnameOf(source.control_api) || 'External'}
            </span>
          </span>
        </div>
        <div className="fx-source-actions">
          <button
            className={`fx-icon-btn sm${editing ? ' active' : ''}`}
            onClick={(e) => { e.stopPropagation(); setEditing(!editing) }}
            title="Edit"
            aria-label="Edit"
          >
            <IconAdjustmentsFilled size={14} />
          </button>
          <button
            className="fx-icon-btn sm danger"
            onClick={(e) => { e.stopPropagation(); handleDelete() }}
            title="Delete"
            aria-label="Delete"
          >
            <IconTrashFilled size={14} />
          </button>
        </div>
      </div>
      {editing && (
        <div className="fx-source-form">
          <div>
            <label className="fx-label">Label</label>
            <div className="fx-input-with-icon">
              <Suspense fallback={<button type="button" className="fx-icon-picker-trigger" disabled aria-label="Pick an icon" />}>
                <LazyIconPickerButton value={icon} onChange={setIcon} />
              </Suspense>
              <input className="fx-input" type="text" value={label} onChange={e => setLabel(e.target.value)} />
            </div>
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
              {saving ? 'Saving…' : <><IconCheckFilled size={14} /> Save</>}
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
  const [label, setLabel] = useState('')
  const [apiUrl, setApiUrl] = useState('')
  const [payload, setPayload] = useState('')
  const [contentType, setContentType] = useState('json')
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!label.trim()) return
    setSubmitting(true)
    const source = {
      label: label.trim(),
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
          <IconXFilled size={14} />
        </button>
      </div>
      <div>
        <label className="fx-label">Name</label>
        <input className="fx-input" type="text" value={label} onChange={e => setLabel(e.target.value)} required placeholder="Vinyl" autoFocus />
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
          <IconPlusFilled size={14} /> Add custom source
        </button>
      </div>
    </form>
  )
}

/**
 * ExternalVolumeControllerSection — opt-in routing of this device's volume
 * slider through an external endpoint instead of attenuating locally. Used
 * for room amps that own their own volume (e.g. a Particle Photon's
 * TDA7468-based vinyl table). When enabled:
 *   • UI slider POSTs to /api/clients/<id>/external_volume per move
 *   • Server sends the value out via the configured transport (HTTP or MQTT)
 *   • Server pins the client's local audio chain to volume=100 (unity)
 *
 * Two transports, chosen by a radio:
 *   HTTP — outbound is a POST you configure (URL + payload template + encoding).
 *          Inbound is a webhook URL fauxnos exposes; the device POSTs there
 *          when its local volume changes.
 *   MQTT — outbound is a publish to the topic you pick. Inbound is fauxnos
 *          subscribing to a topic the device publishes on knob turn. Broker
 *          is always fauxnos's own mosquitto — shown read-only, never edited.
 *
 * Save writes ALL fields (both blocks) so toggling transport doesn't lose
 * what you typed in the other one.
 */
function ExternalVolumeControllerSection({ client, onRefresh }) {
  const evc = client.external_volume_controller || {}
  const [enabled, setEnabled] = useState(!!evc.enabled)
  const [transport, setTransport] = useState(evc.transport || 'http')
  // HTTP fields
  const [url, setUrl] = useState(evc.control_api || '')
  const [payload, setPayload] = useState(
    evc.control_payload
      ? (typeof evc.control_payload === 'string'
          ? evc.control_payload
          : JSON.stringify(evc.control_payload))
      : ''
  )
  const [contentType, setContentType] = useState(evc.content_type || 'json')
  // MQTT fields
  const [mqttTopicOut, setMqttTopicOut] = useState(evc.mqtt_topic_out || '')
  const [mqttPayloadOut, setMqttPayloadOut] = useState(evc.mqtt_payload_out || '{{volume}}/100')
  const [mqttTopicIn, setMqttTopicIn] = useState(evc.mqtt_topic_in || '')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  // The "Connect your device to" block needs to show users where their
  // device should point. We derive from window.location so the UI works
  // identically over fauxnos.local, fauxnos000.local, or a raw IP.
  // MQTT broker port is the standard 1883 (mosquitto's TCP listener).
  // The webhook origin is just the same origin the UI is loaded from.
  const brokerHost = typeof window !== 'undefined' ? window.location.hostname : 'fauxnos.local'
  const brokerPort = 1883
  const webhookOrigin = typeof window !== 'undefined' ? window.location.origin : 'http://fauxnos.local'
  const inboundWebhookUrl = `${webhookOrigin}/api/clients/${client.client_id}/external_volume_inbound`

  // Re-sync state when the prop changes (panel re-opened, App refreshed).
  useEffect(() => {
    const e = client.external_volume_controller || {}
    setEnabled(!!e.enabled)
    setTransport(e.transport || 'http')
    setUrl(e.control_api || '')
    setPayload(
      e.control_payload
        ? (typeof e.control_payload === 'string' ? e.control_payload : JSON.stringify(e.control_payload))
        : ''
    )
    setContentType(e.content_type || 'json')
    setMqttTopicOut(e.mqtt_topic_out || '')
    setMqttPayloadOut(e.mqtt_payload_out || '{{volume}}/100')
    setMqttTopicIn(e.mqtt_topic_in || '')
  }, [client.external_volume_controller])

  const handleSave = useCallback(async () => {
    setSaving(true)
    let parsedPayload = null
    if (payload.trim()) {
      try { parsedPayload = JSON.parse(payload) } catch { parsedPayload = payload }
    }
    try {
      await apiFetch(`/api/clients/${client.client_id}/external_volume_controller`, {
        method: 'PUT',
        body: JSON.stringify({
          enabled,
          transport,
          // Write BOTH blocks every time. Switching transport doesn't
          // discard the other side's config — users can flip back without
          // having to retype URLs / topics.
          control_api: url,
          control_payload: parsedPayload,
          content_type: contentType,
          mqtt_topic_out: mqttTopicOut,
          mqtt_payload_out: mqttPayloadOut,
          mqtt_topic_in: mqttTopicIn,
        }),
      })
      setSaved(true)
      setTimeout(() => setSaved(false), 1500)
      // Triggers /api/clients reload — useMqtt's external routing map and
      // the server's MQTT subscription set both reconcile from it.
      onRefresh?.()
    } catch (e) {
      alert(`Save failed: ${e.message}`)
    } finally {
      setSaving(false)
    }
  }, [client.client_id, enabled, transport, url, payload, contentType,
      mqttTopicOut, mqttPayloadOut, mqttTopicIn, onRefresh])

  return (
    <div className="fx-advanced-evc">
      <div className="fx-advanced-title">External volume controller</div>
      <label className="fx-source-setting">
        <span className="fx-source-setting-label">Use external volume</span>
        <input
          className="fx-checkbox"
          type="checkbox"
          checked={enabled}
          onChange={e => setEnabled(e.target.checked)}
        />
      </label>
      {enabled && (
        <div className="fx-stack" style={{ gap: 'var(--fx-3)' }}>
          <p className="fx-small fx-mute" style={{ margin: 0 }}>
            Volume slider sends each move to your device. Local PA/snapcast is
            pinned at unity — the external controller owns attenuation.
          </p>
          {/* Transport radio — picks which transport's fields are live. */}
          <div>
            <label className="fx-label">Transport</label>
            <div className="fx-stack" style={{ flexDirection: 'row', gap: 'var(--fx-3)' }}>
              <label style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--fx-1)' }}>
                <input
                  type="radio"
                  name={`evc-transport-${client.client_id}`}
                  value="http"
                  checked={transport === 'http'}
                  onChange={() => setTransport('http')}
                />
                HTTP
              </label>
              <label style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--fx-1)' }}>
                <input
                  type="radio"
                  name={`evc-transport-${client.client_id}`}
                  value="mqtt"
                  checked={transport === 'mqtt'}
                  onChange={() => setTransport('mqtt')}
                />
                MQTT
              </label>
            </div>
          </div>

          {transport === 'http' && (
            <div className="fx-stack" style={{ gap: 'var(--fx-3)' }}>
              <p className="fx-small fx-mute" style={{ margin: 0 }}>
                Use <code>{'{{volume}}'}</code> as a placeholder for the 0-100
                slider value. Append <code>/N</code> if your device expects a
                different scale (e.g. <code>{'{{volume}}/100'}</code>).
              </p>
              <div>
                <label className="fx-label">API URL</label>
                <input
                  className="fx-input"
                  type="url"
                  value={url}
                  onChange={e => setUrl(e.target.value)}
                  placeholder="https://api.particle.io/v1/devices/<id>/setVolume"
                />
              </div>
              <div>
                <label className="fx-label">Payload</label>
                <textarea
                  className="fx-textarea"
                  rows={3}
                  value={payload}
                  onChange={e => setPayload(e.target.value)}
                  placeholder={contentType === 'form'
                    ? '{"arg": "{{volume}}/100", "access_token": "…"}'
                    : '{"value": "{{volume}}"}'}
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
                <label className="fx-label">Inbound webhook (your device POSTs here on knob turn)</label>
                <input
                  className="fx-input"
                  type="text"
                  readOnly
                  value={inboundWebhookUrl}
                  onClick={e => e.target.select()}
                  title="Click to select. Configure your device to POST {value: N} (N in 0-100) to this URL whenever its volume changes locally."
                  style={{ fontFamily: 'var(--fx-font-mono, monospace)', fontSize: 'var(--fx-fs-sm)' }}
                />
              </div>
            </div>
          )}

          {transport === 'mqtt' && (
            <div className="fx-stack" style={{ gap: 'var(--fx-3)' }}>
              <p className="fx-small fx-mute" style={{ margin: 0 }}>
                Use <code>{'{{volume}}'}</code> as a placeholder for the 0-100
                slider value. Append <code>/N</code> if your device expects a
                different scale (e.g. <code>{'{{volume}}/100'}</code>). Inbound
                payloads are parsed as plain integers 0-100 (or <code>N/M</code>).
              </p>
              <div>
                <label className="fx-label">Outbound topic (fauxnos publishes on slider move)</label>
                <input
                  className="fx-input"
                  type="text"
                  value={mqttTopicOut}
                  onChange={e => setMqttTopicOut(e.target.value)}
                  placeholder="vinyltable/setVolume"
                />
              </div>
              <div>
                <label className="fx-label">Outbound payload template</label>
                <input
                  className="fx-input"
                  type="text"
                  value={mqttPayloadOut}
                  onChange={e => setMqttPayloadOut(e.target.value)}
                  placeholder="{{volume}}/100"
                />
              </div>
              <div>
                <label className="fx-label">Inbound topic (fauxnos subscribes; your device publishes on knob turn)</label>
                <input
                  className="fx-input"
                  type="text"
                  value={mqttTopicIn}
                  onChange={e => setMqttTopicIn(e.target.value)}
                  placeholder="vinyltable/volume"
                />
              </div>
              {/* Read-only broker info — users need this to configure
                  their device, but the broker itself is part of fauxnos
                  (mosquitto on the server), so the user never picks it. */}
              <div className="fx-panel-card" style={{ padding: 'var(--fx-2) var(--fx-3)' }}>
                <div className="fx-small" style={{ marginBottom: 'var(--fx-1)', fontWeight: 600 }}>
                  Connect your device to:
                </div>
                <div className="fx-small fx-mute" style={{ fontFamily: 'var(--fx-font-mono, monospace)' }}>
                  Broker: {brokerHost}:{brokerPort} (TCP, no auth)
                </div>
              </div>
            </div>
          )}

          <div>
            <button className="fx-btn primary" onClick={handleSave} disabled={saving}>
              {saved ? <><IconCheckFilled size={14} /> Saved</> : <><IconCheckFilled size={14} /> Save</>}
            </button>
          </div>
        </div>
      )}
      {!enabled && (
        // When OFF we still expose Save so the user can persist "turn this off."
        // Otherwise toggling off + closing the panel leaves saved state at on.
        <div style={{ marginTop: 'var(--fx-2)' }}>
          <button className="fx-btn" onClick={handleSave} disabled={saving}>
            {saved ? <><IconCheckFilled size={14} /> Saved</> : 'Save'}
          </button>
        </div>
      )}
    </div>
  )
}

/**
 * Advanced Settings — DAC overlay + external volume controller. Collapsed by
 * default because a wrong overlay choice can leave the Pi without audio until
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
    <div className="fx-device-advanced-section">
      <div
        className="fx-section-label fx-section-label-clickable"
        role="button"
        tabIndex={0}
        onClick={() => setOpen(v => !v)}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpen(v => !v) } }}
        aria-expanded={open}
      >
        <span>Advanced settings</span>
        <button
          className="fx-icon-btn sm"
          onClick={(e) => { e.stopPropagation(); setOpen(!open) }}
          aria-expanded={open}
          title={open ? 'Collapse' : 'Expand'}
        >
          {open ? <IconChevronDownFilled size={14} /> : <IconChevronRightFilled size={14} />}
        </button>
      </div>
      {open && (
        <div className="fx-panel-card fx-device-advanced-card">
          <RemoteControlSection client={client} />
          <div className="fx-advanced-title">Choose audio hat</div>
          <select
            className="fx-select fx-audio-hat-select"
            value={selectedOverlay || ''}
            disabled={overlayLocked || applying || isRebooting}
            onChange={e => setSelectedOverlay(e.target.value)}
            title={overlayLocked
              ? "Server hardware overlay is locked (analog-input detection in install.sh keys off this exact value)."
              : "Pick the matching DAC HAT and press Apply to reboot."
            }
            style={{ width: '100%', minWidth: 0 }}
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
            style={{ alignSelf: 'flex-start' }}
          >
            {applying ? 'Applying…' : isRebooting ? 'Rebooting…' : (overlayDirty ? 'Apply + reboot' : 'Re-apply')}
          </button>
          {applyMessage && (
            <div className="fx-small" style={{ color: applyMessage.startsWith('Failed') ? 'var(--fx-err)' : 'var(--fx-text-2)' }}>
              {applyMessage}
            </div>
          )}
          {overlayLocked && (
            <p className="fx-small fx-mute">
              Locked: install.sh's analog-input detection keys off this exact value.
            </p>
          )}
          <ExternalVolumeControllerSection client={client} onRefresh={onRefresh} />
        </div>
      )}
    </div>
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
// Sibling of AdvancedSettings — independent collapsible "Equalizer"
// section in the device panel. Mirrors the look of AdvancedSettings
// (fx-section-label header + chevron + fx-panel-card body).
//
// The 10 ISO graphic-EQ bands match modules/eq_controller.py BANDS_HZ
// and api_server.py EQ_BANDS_HZ — keep in sync if the layout changes.
const EQ_BANDS_HZ = [31, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]

// Pretty-print band frequency for the slider labels: "31" → "31",
// "1000" → "1k", "16000" → "16k". Saves horizontal space in the strip.
function fmtBand(hz) {
  return hz >= 1000 ? `${hz / 1000}k` : `${hz}`
}

// Pretty-print preset name (snake_case → Title Case).
function fmtPreset(name) {
  if (!name) return ''
  return name.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
}

// Did the user's current band vector exactly match one of the named
// presets? Returns the matching name or null. Float tolerance is 0.05 dB
// so rounding noise in MQTT round-trips doesn't flip the label.
function findMatchingPreset(presets, bands) {
  if (!presets || !bands) return null
  for (const [name, presetBands] of Object.entries(presets)) {
    let allMatch = true
    for (const hz of EQ_BANDS_HZ) {
      const cur = bands[String(hz)] ?? 0
      const target = presetBands[String(hz)] ?? 0
      if (Math.abs(cur - target) > 0.05) { allMatch = false; break }
    }
    if (allMatch) return name
  }
  return null
}

// Shallow {enabled, bands} comparison with float tolerance so MQTT
// round-trip noise (e.g. 4 vs 4.0) doesn't trip the dirty flag.
function eqEquals(a, b) {
  if (!a || !b) return false
  if (!!a.enabled !== !!b.enabled) return false
  for (const hz of EQ_BANDS_HZ) {
    const av = a.bands?.[String(hz)] ?? 0
    const bv = b.bands?.[String(hz)] ?? 0
    if (Math.abs(av - bv) > 0.05) return false
  }
  return true
}

function EqualizerSection({ client }) {
  const [open, setOpen] = useState(false)
  // Two views of state: what the device has (saved) and what the user
  // is staging (pending). Apply flushes pending → saved via one PUT.
  // Reset reverts pending to saved.
  const [savedEq, setSavedEq] = useState({ enabled: false, bands: {} })
  const [pendingEq, setPendingEq] = useState({ enabled: false, bands: {} })
  const [presets, setPresets] = useState({})
  const [loading, setLoading] = useState(true)
  const [applying, setApplying] = useState(false)
  const [errorMsg, setErrorMsg] = useState(null)

  // Initial fetch — parallel GET of the device's current EQ state AND
  // the static preset catalog. Both are tiny; one round-trip each.
  useEffect(() => {
    if (!client.client_id) return
    let cancelled = false
    Promise.all([
      apiFetch(`/api/clients/${client.client_id}/eq`),
      apiFetch('/api/eq/presets'),
    ]).then(([eqResp, presetResp]) => {
      if (cancelled) return
      const eq = eqResp?.eq || {}
      const next = {
        enabled: !!eq.enabled,
        bands: eq.bands || {},
      }
      setSavedEq(next)
      setPendingEq(next)
      setPresets(presetResp?.presets || {})
    })
      .catch(e => { if (!cancelled) setErrorMsg(e.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [client.client_id])

  const isDirty = !eqEquals(savedEq, pendingEq)

  const toggleEnabled = useCallback(() => {
    setPendingEq(prev => ({ ...prev, enabled: !prev.enabled }))
    setErrorMsg(null)
  }, [])

  const selectPreset = useCallback((name) => {
    if (!presets[name]) return
    const presetBands = presets[name]
    setPendingEq(prev => ({ ...prev, bands: { ...presetBands } }))
    setErrorMsg(null)
  }, [presets])

  const onBandChange = useCallback((hz, newGain) => {
    setPendingEq(prev => ({
      ...prev,
      bands: { ...prev.bands, [String(hz)]: newGain },
    }))
    setErrorMsg(null)
  }, [])

  const applyChanges = useCallback(async () => {
    setApplying(true)
    setErrorMsg(null)
    // Snapshot the values we're about to send so further user edits
    // during the in-flight PUT don't get prematurely "saved" below.
    const committed = pendingEq
    try {
      await apiFetch(`/api/clients/${client.client_id}/eq`, {
        method: 'PUT',
        body: JSON.stringify({
          enabled: committed.enabled,
          bands: committed.bands,
        }),
      })
      // Don't trust the PUT response body — the server returns the
      // *pre-echo* server-side mirror (the route fires an MQTT publish
      // and returns immediately). The client applies asynchronously
      // and echoes via status/.../eq a few hundred ms later. Using
      // the response would clobber pendingEq back to the old gains
      // and make Apply look like a no-op even when the audio changed.
      setSavedEq(committed)
    } catch (e) {
      setErrorMsg(`Apply failed: ${e.message}`)
    } finally {
      setApplying(false)
    }
  }, [client.client_id, pendingEq])

  const resetChanges = useCallback(() => {
    setPendingEq(savedEq)
    setErrorMsg(null)
  }, [savedEq])

  // Which preset (if any) does pendingEq match? Drives the dropdown's
  // displayed value + the synthetic "Custom" option.
  const matchedPreset = findMatchingPreset(presets, pendingEq.bands)
  const dropdownValue = matchedPreset || '__custom__'

  return (
    <>
      <div
        className="fx-section-label fx-section-label-clickable"
        role="button"
        tabIndex={0}
        onClick={() => setOpen(v => !v)}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpen(v => !v) } }}
        aria-expanded={open}
      >
        <span>Equalizer</span>
        <button
          className="fx-icon-btn sm"
          onClick={(e) => { e.stopPropagation(); setOpen(!open) }}
          aria-expanded={open}
          title={open ? 'Collapse' : 'Expand'}
        >
          {open ? <IconChevronDownFilled size={14} /> : <IconChevronRightFilled size={14} />}
        </button>
      </div>
      {open && (
        <div className="fx-panel-card fx-advanced-body">
          {loading && <div className="fx-muted">Loading…</div>}
          {errorMsg && <div className="fx-error">{errorMsg}</div>}
          {!loading && (
            <>
              <div className="fx-eq-header">
                <label className="fx-eq-enable">
                  <input
                    type="checkbox"
                    checked={pendingEq.enabled}
                    onChange={toggleEnabled}
                  />
                  <span>Enabled</span>
                </label>
                <select
                  className="fx-select fx-eq-preset"
                  value={dropdownValue}
                  onChange={e => selectPreset(e.target.value)}
                  disabled={!pendingEq.enabled}
                  title={pendingEq.enabled ? 'Pick a starting EQ shape' : 'Enable the EQ to choose a preset'}
                >
                  {/* "Custom" is the synthetic option shown when bands
                      don't match any preset. It's unselectable from the
                      menu — picking a real preset replaces it. */}
                  {!matchedPreset && (
                    <option key="__custom__" value="__custom__" disabled>Custom</option>
                  )}
                  {Object.keys(presets).map(name => (
                    <option key={name} value={name}>
                      {fmtPreset(name)}
                    </option>
                  ))}
                </select>
              </div>

              <div className="fx-eq-strip">
                {EQ_BANDS_HZ.map(hz => {
                  const gain = pendingEq.bands[String(hz)] ?? 0
                  return (
                    <div key={hz} className="fx-eq-band">
                      <span className="fx-eq-gain">
                        {gain > 0 ? '+' : ''}{gain.toFixed(1)}
                      </span>
                      <input
                        type="range"
                        className="fx-eq-slider"
                        min={-12}
                        max={12}
                        step={0.5}
                        value={gain}
                        disabled={!pendingEq.enabled}
                        onChange={e => onBandChange(hz, parseFloat(e.target.value))}
                        onDoubleClick={() => onBandChange(hz, 0)}
                        aria-label={`${fmtBand(hz)} Hz`}
                        title={`${fmtBand(hz)} Hz — double-click to zero`}
                      />
                      <span className="fx-eq-freq">{fmtBand(hz)}</span>
                    </div>
                  )
                })}
              </div>

              {/* Apply / Reset row. Only render when there are unsaved
                  changes — otherwise it collapses out of view and
                  doesn't visually compete with the slider strip. */}
              {isDirty && (
                <div className="fx-eq-actions">
                  <button
                    type="button"
                    className="fx-btn"
                    onClick={resetChanges}
                    disabled={applying}
                  >
                    Reset
                  </button>
                  <button
                    type="button"
                    className="fx-btn primary"
                    onClick={applyChanges}
                    disabled={applying}
                  >
                    {applying ? 'Applying…' : 'Apply'}
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </>
  )
}

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
    <div className="fx-remote-control">
      <div className="fx-ir-header-row">
        <div className="fx-ir-label-group">
          <label htmlFor={`ir-remote-${client.client_id}`} className="fx-advanced-title" style={{ margin: 0, cursor: 'pointer' }}>
            Remote control
          </label>
          <HelpPopover>
            Wire a 38 kHz IR receiver (e.g. VS1838B) to GPIO17 / 3V3 / GND and enable
            to teach this device a remote.
          </HelpPopover>
        </div>
        <input
          id={`ir-remote-${client.client_id}`}
          className="fx-checkbox"
          type="checkbox"
          checked={enabled}
          disabled={loading}
          onChange={toggleEnabled}
        />
      </div>
      {enabled && (
        <div className="fx-ir-card">
          <div className="fx-source-setting">
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
          <hr className="fx-ir-divider" />
          <div className="fx-ir-section-title">Learn commands from your remote control</div>
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
        </div>
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
          <button
            className="fx-btn fx-ir-action-stop"
            onClick={onCancel}
            aria-label="Cancel learning"
            title="Cancel"
          >
            <IconPlayerStopFilled size={14} />
          </button>
        ) : (
          <>
            {mapping && (
              <button
                className="fx-icon-btn sm"
                onClick={onClear}
                disabled={disabled}
                title="Forget this mapping"
                aria-label="Forget this mapping"
              >
                <IconXFilled size={14} />
              </button>
            )}
            <button
              className="fx-btn fx-ir-action-record"
              onClick={onLearn}
              disabled={disabled}
              title={disabled ? 'Cancel the in-flight learn first' : (mapping ? 'Re-learn — press a button on your remote' : 'Learn — press a button on your remote')}
              aria-label={mapping ? 'Re-learn' : 'Learn'}
            >
              <IconPlayerRecordFilled size={14} />
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
      <IconTrashFilled size={14} /> Remove device
    </button>
  )
}
