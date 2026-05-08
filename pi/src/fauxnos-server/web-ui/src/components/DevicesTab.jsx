import { useState, useCallback } from 'react'
import { apiFetch } from '../api'

export default function DevicesTab({ clients, onRefresh }) {
  if (clients.length === 0) {
    return (
      <div>
        <div className="panel-header">
          <h2>Devices</h2>
          <button className="btn-secondary" onClick={onRefresh}>Refresh</button>
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
        <button className="btn-secondary" onClick={onRefresh}>Refresh</button>
      </div>
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Device ID</th>
            <th>Status</th>
            <th title="Toggle on for devices with an analog input (e.g. HiFiBerry DAC+ADC). Adds the 'Analog In' source to the device's Sources panel.">Analog&nbsp;In</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {clients.map(c => (
            <DeviceRow key={c.client_id} client={c} onRefresh={onRefresh} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function DeviceRow({ client, onRefresh }) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(client.name)
  // Optimistic local state for the has_adc checkbox so the toggle feels
  // instant while the PUT is in flight. We re-sync from the prop on every
  // render via the boolean coercion below; the backend is the source of
  // truth and onRefresh() will reconcile after the request completes.
  const [hasAdc, setHasAdc] = useState(!!client.has_adc)
  const [savingAdc, setSavingAdc] = useState(false)

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
        <button className="btn-danger" onClick={handleRemove}>Remove</button>
      </td>
    </tr>
  )
}
