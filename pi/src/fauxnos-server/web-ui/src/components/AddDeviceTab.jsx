import { useState, useRef, useEffect } from 'react'
import { apiFetch } from '../api'

export default function AddDeviceTab({ onDeviceAdded }) {
  const [waiting, setWaiting] = useState(false)
  const [waitResult, setWaitResult] = useState(null)
  const pollRef = useRef(null)
  const knownRef = useRef(null)

  // Clean up polling on unmount
  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  const downloadFirstrun = async () => {
    const name = document.getElementById('display-name-input')?.value?.trim() || ''
    const query = name ? `?display_name=${encodeURIComponent(name)}` : ''
    try {
      const res = await fetch(`/api/install/firstrun.sh${query}`)
      if (!res.ok) throw new Error(`Server returned ${res.status}`)
      const text = await res.text()
      const blob = new Blob([text], { type: 'text/plain' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = 'firstrun.sh'; a.click()
      setTimeout(() => URL.revokeObjectURL(url), 100)
    } catch (e) {
      alert(`Download failed: ${e.message}`)
    }
  }

  const startWaiting = async () => {
    setWaiting(true)
    setWaitResult(null)
    try {
      const data = await apiFetch('/api/clients')
      knownRef.current = new Set((data.clients || []).map(c => c.client_id))
    } catch {
      knownRef.current = new Set()
    }

    pollRef.current = setInterval(async () => {
      try {
        const data = await apiFetch('/api/clients')
        const newClient = (data.clients || []).find(c => !knownRef.current.has(c.client_id))
        if (newClient) {
          clearInterval(pollRef.current)
          pollRef.current = null
          setWaiting(false)
          setWaitResult(newClient.name || newClient.client_id)
          onDeviceAdded?.()
        }
      } catch { /* keep polling */ }
    }, 5000)
  }

  return (
    <div>
      <div className="panel-header"><h2>Add Device</h2></div>

      <div className="card">
        <h3>Step 1 — Flash Pi OS</h3>
        <p>
          Download{' '}
          <a href="https://www.raspberrypi.com/software/" target="_blank" rel="noopener">
            Raspberry Pi Imager
          </a>
          , choose <strong>Raspberry Pi OS Lite (64-bit, Bookworm)</strong>, and in Advanced
          Options set your WiFi credentials and add your SSH public key.
        </p>
      </div>

      <div className="card">
        <h3>Step 2 — Generate setup file</h3>
        <label htmlFor="display-name-input">
          Device name <span className="hint">(optional, e.g. "Kitchen")</span>
        </label>
        <input type="text" id="display-name-input" placeholder="Kitchen" maxLength={64} />
        <button className="btn-primary" onClick={downloadFirstrun} style={{ marginTop: 8 }}>
          Download firstrun.sh
        </button>
      </div>

      <div className="card">
        <h3>Step 3 — Copy to SD card</h3>
        <p>
          After flashing, the SD card boot partition (FAT32) will be visible on your computer.
          Copy <code>firstrun.sh</code> to the root of that partition.
        </p>
        <pre className="code-block">cp ~/Downloads/firstrun.sh /Volumes/bootfs/</pre>
      </div>

      <div className="card">
        <h3>Step 4 — Boot the Pi</h3>
        <p>Insert the SD card, power on the Pi, and wait. It will auto-install and register.</p>
        {waiting && (
          <div className="waiting">
            <span className="spinner" /> Waiting for new device...
          </div>
        )}
        {waitResult && (
          <div className="waiting" style={{ color: 'var(--green)' }}>
            &#10003; {waitResult} registered!
          </div>
        )}
        {!waiting && (
          <button className="btn-secondary" onClick={startWaiting} style={{ marginTop: 8 }}>
            Watch for new device
          </button>
        )}
      </div>
    </div>
  )
}
