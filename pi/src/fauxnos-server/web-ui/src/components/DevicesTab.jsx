import { useState, useCallback, useEffect } from 'react'
import { apiFetch, cleanupSnapcastOrphans } from '../api'

// Mirrors modules/dac_overlays.py DAC_OVERLAYS. Hardcoded here so the
// dropdown renders before /api/dac_overlays returns; the API endpoint is
// the source of truth and we re-fetch on mount to pick up any new entries
// without a UI rebuild.
const FALLBACK_DAC_OVERLAYS = [
  { id: 'allo-boss-dac-pcm512x-audio', label: 'Allo Boss / INNO-MAKER PCM5122' },
  { id: 'hifiberry-dac',               label: 'HiFiBerry DAC+ Light / MiniAmp / generic PCM5102' },
  { id: 'hifiberry-dacplus',           label: 'HiFiBerry DAC+ Standard / Pro' },
  { id: 'hifiberry-dacplusadc',        label: 'HiFiBerry DAC+ ADC (line-in)' },
  { id: 'iqaudio-dacplus',             label: 'IQaudIO Pi-DAC+' },
]

// Sweep snapserver of registrations that aren't tied to any registered
// fauxnos device. Used by both the empty-state and populated views — the
// install runner already auto-fires this on success, but exposing it as
// a button lets the user reconcile after a manual snapclient invocation
// or any other corner case that produced an orphan.
function CleanupOrphansButton({ onRefresh }) {
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(null)
  const onClick = useCallback(async () => {
    setRunning(true)
    setResult(null)
    try {
      const r = await cleanupSnapcastOrphans()
      setResult(r)
      onRefresh()
    } catch (e) {
      setResult({ error: String(e.message || e) })
    } finally {
      setRunning(false)
    }
  }, [onRefresh])
  return (
    <>
      <button
        className="btn-secondary"
        onClick={onClick}
        disabled={running}
        title="Delete snapcast registrations that aren't tied to a registered device. Used to clear orphan entries left behind by an install or a wiped Pi."
      >
        {running ? 'Cleaning…' : 'Clean up snapcast'}
      </button>
      {result && !result.error && (
        <span style={{ marginLeft: 4, color: 'var(--muted, #888)', fontSize: 12 }}>
          Removed {result.deleted?.length || 0} orphan{result.deleted?.length === 1 ? '' : 's'}
        </span>
      )}
      {result?.error && (
        <span style={{ marginLeft: 4, color: 'var(--danger, #c33)', fontSize: 12 }}>{result.error}</span>
      )}
    </>
  )
}

export default function DevicesTab({ clients, onRefresh }) {
  // Pull the canonical overlay list from the server; fall back to the
  // hardcoded copy on first paint (or if the endpoint is unreachable).
  const [overlays, setOverlays] = useState(FALLBACK_DAC_OVERLAYS)
  useEffect(() => {
    let cancelled = false
    apiFetch('/api/dac_overlays')
      .then(j => {
        if (!cancelled && Array.isArray(j?.overlays) && j.overlays.length) {
          setOverlays(j.overlays)
        }
      })
      .catch(() => { /* fall back to FALLBACK_DAC_OVERLAYS */ })
    return () => { cancelled = true }
  }, [])

  if (clients.length === 0) {
    return (
      <div>
        <div className="panel-header">
          <h2>Devices</h2>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <CleanupOrphansButton onRefresh={onRefresh} />
            <button className="btn-secondary" onClick={onRefresh}>Refresh</button>
          </div>
        </div>
        <div className="empty-state">
          No devices registered yet. Use the <strong>Add Device</strong> tab to add your first device.
        </div>
      </div>
    )
  }

  return (
    <div>
      <div className="panel-header">
        <h2>Devices</h2>
        <div className="panel-actions">
          <CleanupOrphansButton onRefresh={onRefresh} />
          <button className="btn-secondary" onClick={onRefresh}>Refresh</button>
        </div>
      </div>
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Device ID</th>
            <th>Status</th>
            <th title="Toggle on for devices with an analog input (e.g. HiFiBerry DAC+ADC). Adds the 'Analog In' source to the device's Sources panel.">Analog&nbsp;In</th>
            <th title="dt-overlay written to /boot/firmware/config.txt. Apply pushes the change live and reboots the device.">DAC&nbsp;overlay</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {clients.map(c => (
            <DeviceRow key={c.client_id} client={c} onRefresh={onRefresh} overlays={overlays} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function DeviceRow({ client, onRefresh, overlays }) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(client.name)
  // Optimistic local state for the has_adc checkbox so the toggle feels
  // instant while the PUT is in flight. We re-sync from the prop on every
  // render via the boolean coercion below; the backend is the source of
  // truth and onRefresh() will reconcile after the request completes.
  const [hasAdc, setHasAdc] = useState(!!client.has_adc)
  const [savingAdc, setSavingAdc] = useState(false)
  // DAC overlay state. `selected` is what the dropdown shows (may differ
  // from `client.dac_overlay` while the user is choosing pre-Apply).
  // `appliedAt` is set when an Apply request goes out — used to render
  // the "Rebooting…" state for ~60s before reverting to the normal UI.
  const [selectedOverlay, setSelectedOverlay] = useState(client.dac_overlay || '')
  useEffect(() => {
    setSelectedOverlay(client.dac_overlay || '')
  }, [client.dac_overlay])
  const [applying, setApplying] = useState(false)
  const [applyMessage, setApplyMessage] = useState(null)
  const [rebootingUntil, setRebootingUntil] = useState(0)
  const overlayLocked = !!client.dac_overlay_locked
  const overlayDirty = selectedOverlay && selectedOverlay !== client.dac_overlay
  const isRebooting = rebootingUntil > Date.now()

  // While we're in the "rebooting" window, poll the device list every few
  // seconds so connectivity flips back to green automatically once the Pi
  // reappears. Tear down on unmount or when the window expires.
  useEffect(() => {
    if (!isRebooting) return undefined
    const t = setInterval(onRefresh, 5000)
    const stop = setTimeout(() => setRebootingUntil(0), Math.max(rebootingUntil - Date.now(), 0))
    return () => { clearInterval(t); clearTimeout(stop) }
  }, [isRebooting, rebootingUntil, onRefresh])

  const saveRename = useCallback(async () => {
    setEditing(false)
    if (!name.trim() || name === client.name) {
      setName(client.name)
      return
    }
    try {
      await apiFetch(`/api/clients/${client.client_id}`, {
        method: 'PUT',
        body: JSON.stringify({ name: name.trim() }),
      })
      onRefresh()
    } catch {
      setName(client.name)
    }
  }, [name, client, onRefresh])

  const handleAdcToggle = useCallback(async (e) => {
    const next = e.target.checked
    setHasAdc(next)            // optimistic
    setSavingAdc(true)
    try {
      await apiFetch(`/api/clients/${client.client_id}`, {
        method: 'PUT',
        body: JSON.stringify({ has_adc: next }),
      })
      onRefresh()
    } catch (err) {
      setHasAdc(!next)         // rollback
      alert(`Failed to update analog input flag: ${err.message}`)
    } finally {
      setSavingAdc(false)
    }
  }, [client.client_id, onRefresh])

  const handleRemove = useCallback(async () => {
    if (!confirm(`Remove device ${client.client_id}? This cannot be undone.`)) return
    try {
      await apiFetch(`/api/clients/${client.client_id}`, { method: 'DELETE' })
      onRefresh()
    } catch (e) {
      alert(`Remove failed: ${e.message}`)
    }
  }, [client.client_id, onRefresh])

  // Apply: sends the (possibly-changed) selected overlay AND triggers the
  // remote rewrite + reboot in one call. Backend saves first then SSHes,
  // so a partial failure ends with the new value persisted but unapplied
  // — refresh will show that, and the user can hit Apply again.
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
      onRefresh()
    } catch (e) {
      setApplyMessage(`Failed: ${e.message}`)
    } finally {
      setApplying(false)
    }
  }, [client.client_id, selectedOverlay, overlayLocked, onRefresh])

  return (
    <tr>
      <td>
        <input
          className={`device-name-edit${editing ? ' editing' : ''}`}
          value={name}
          readOnly={!editing}
          onDoubleClick={() => setEditing(true)}
          onChange={e => setName(e.target.value)}
          onBlur={saveRename}
          onKeyDown={e => {
            if (e.key === 'Enter') e.target.blur()
            if (e.key === 'Escape') { setEditing(false); setName(client.name) }
          }}
        />
      </td>
      <td><code>{client.client_id}</code></td>
      <td>
        <span className={`badge ${client.connected ? 'badge-green' : 'badge-grey'}`}>
          {client.connected ? 'connected' : 'offline'}
        </span>
      </td>
      <td style={{ textAlign: 'center' }}>
        <input
          type="checkbox"
          checked={hasAdc}
          disabled={savingAdc}
          onChange={handleAdcToggle}
          title="This device has an analog input (e.g. HiFiBerry DAC+ADC). Enables the 'Analog In' source."
        />
      </td>
      <td>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          <select
            value={selectedOverlay || ''}
            disabled={overlayLocked || applying || isRebooting}
            onChange={e => setSelectedOverlay(e.target.value)}
            title={overlayLocked
              ? "Server hardware overlay is locked (analog-input detection in install.sh keys off this exact value)."
              : "dt-overlay written to /boot/firmware/config.txt. Pick the matching DAC HAT and press Apply to reboot."
            }
            style={{ minWidth: 240 }}
          >
            {(overlays || []).map(o => (
              <option key={o.id} value={o.id}>{o.label}</option>
            ))}
            {/* Render whatever's saved even if the server's allowlist
                was trimmed since — the user shouldn't see a blank box. */}
            {selectedOverlay && !overlays?.some(o => o.id === selectedOverlay) && (
              <option value={selectedOverlay}>{selectedOverlay} (custom)</option>
            )}
          </select>
          <button
            className={overlayDirty ? 'btn-primary' : 'btn-secondary'}
            disabled={overlayLocked || applying || isRebooting || !selectedOverlay}
            onClick={handleApplyOverlay}
            title="Rewrite /boot/firmware/config.txt on the device and reboot it. Device will be offline for ~60s."
          >
            {applying ? 'Applying…' : isRebooting ? 'Rebooting…' : (overlayDirty ? 'Apply + reboot' : 'Re-apply')}
          </button>
          {applyMessage && (
            <span
              style={{
                fontSize: 12,
                color: applyMessage.startsWith('Failed') ? 'var(--danger, #c33)' : 'var(--muted, #888)',
              }}
            >
              {applyMessage}
            </span>
          )}
        </div>
      </td>
      <td>
        <button className="btn-danger" onClick={handleRemove}>Remove</button>
      </td>
    </tr>
  )
}
