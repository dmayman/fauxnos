import { useEffect, useState } from 'react'
import { apiFetch } from '../api'
import InstallTimeline from './InstallTimeline'

/**
 * Add Device wizard.
 *
 * Flow:
 *   1. Prerequisites checklist — what you need before flashing the Pi. Includes
 *      a copy-to-clipboard block of the server's install pubkey, fetched from
 *      /api/install/server-pubkey. The user pastes that + their personal
 *      1Password key into Pi Imager's "Allow public-key authentication only"
 *      field.
 *   2. Display name input.
 *   3. "Install" button → POST /api/install/start → renders <InstallTimeline />.
 *
 * The timeline replaces the action area for the duration of the install. On
 * completion we show a success/failure banner and an "Install another" button
 * that resets to the prerequisites view.
 */
export default function AddDeviceTab({ onDeviceAdded }) {
  const [pubkey, setPubkey] = useState('')
  const [pubkeyError, setPubkeyError] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [targetHost, setTargetHost] = useState('fauxnos-client.local')
  const [running, setRunning] = useState(false)
  const [submitError, setSubmitError] = useState('')
  const [completed, setCompleted] = useState(null)
  const [resetTick, setResetTick] = useState(0)  // bump to force-remount InstallTimeline

  // Hydrate: fetch pubkey, and check whether an install is already running
  // (e.g. user reloaded the page mid-install).
  useEffect(() => {
    let alive = true
    fetch('/api/install/server-pubkey')
      .then(async (r) => {
        const text = await r.text()
        if (!alive) return
        if (!r.ok) { setPubkeyError(text || `${r.status}`); return }
        setPubkey(text.trim())
      })
      .catch((e) => { if (alive) setPubkeyError(String(e)) })

    apiFetch('/api/install/status').then((s) => {
      if (!alive) return
      if (s && s.status === 'running') {
        setRunning(true)
      }
    }).catch(() => {})

    return () => { alive = false }
  }, [])

  const start = async () => {
    setSubmitError('')
    if (!displayName.trim()) {
      setSubmitError('Enter a device name')
      return
    }
    try {
      await apiFetch('/api/install/start', {
        method: 'POST',
        body: JSON.stringify({ display_name: displayName.trim(), target_host: targetHost.trim() }),
      })
      setRunning(true)
      setCompleted(null)
    } catch (e) {
      // 409 means another install is in flight — we still want to show its
      // timeline, so flip running on but surface the message.
      const msg = String(e.message || e)
      if (msg.startsWith('409')) {
        setRunning(true)
        setSubmitError('Another install is already running. Showing its progress.')
      } else {
        setSubmitError(msg)
      }
    }
  }

  const onDone = (snap) => {
    setCompleted(snap)
    if (snap?.status === 'succeeded' && onDeviceAdded) onDeviceAdded()
  }

  const reset = () => {
    setRunning(false)
    setCompleted(null)
    setDisplayName('')
    setSubmitError('')
    setResetTick((n) => n + 1)
  }

  return (
    <div>
      <div className="panel-header"><h2>Add Device</h2></div>

      {!running && !completed && (
        <PreInstallView
          pubkey={pubkey}
          pubkeyError={pubkeyError}
          displayName={displayName}
          setDisplayName={setDisplayName}
          targetHost={targetHost}
          setTargetHost={setTargetHost}
          onStart={start}
          submitError={submitError}
        />
      )}

      {(running || completed) && (
        <div className="card">
          <h3>{completed?.status === 'succeeded' ? 'Install complete' : 'Installing'}</h3>
          <InstallTimeline key={resetTick} onDone={onDone} />
          {completed && (
            <button className="btn-secondary" onClick={reset} style={{ marginTop: 12 }}>
              {completed.status === 'succeeded' ? 'Install another' : 'Try again'}
            </button>
          )}
        </div>
      )}
    </div>
  )
}

function PreInstallView({ pubkey, pubkeyError, displayName, setDisplayName, targetHost, setTargetHost, onStart, submitError }) {
  const [copied, setCopied] = useState(false)

  const copyPubkey = async () => {
    if (!pubkey) return
    try {
      await navigator.clipboard.writeText(pubkey)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Fallback: select the <pre> contents
      window.prompt('Copy this key:', pubkey)
    }
  }

  return (
    <>
      <div className="card">
        <h3>Prerequisites</h3>
        <ul className="prereq-list">
          <li>Flash <strong>Raspberry Pi OS Lite (64-bit, Bookworm)</strong> with Pi Imager — <em>not</em> Trixie, not Desktop.</li>
          <li>In Pi Imager, set hostname <code>fauxnos-client</code>, username <code>user</code>, a per-Pi password (save in 1Password).</li>
          <li>Configure WiFi credentials and locale.</li>
          <li>Enable SSH → "Allow public-key authentication only" → paste <strong>both</strong> keys below.</li>
        </ul>
      </div>

      <div className="card">
        <h3>SSH keys to paste in Pi Imager</h3>
        <p style={{ marginTop: 4 }}>1) Your personal public key (from 1Password — the one you use to SSH into other fauxnos Pis).</p>
        <p style={{ marginTop: 8 }}>2) This server's install key — needed so the wizard can SSH in and run the install:</p>
        <div className="pubkey-block">
          {pubkeyError ? (
            <pre style={{ color: 'var(--red)' }}>{pubkeyError}</pre>
          ) : (
            <>
              <pre>{pubkey || 'Loading…'}</pre>
              {pubkey && (
                <button className={`pubkey-copy ${copied ? 'copied' : ''}`} onClick={copyPubkey}>
                  {copied ? '✓ Copied' : '📋 Copy'}
                </button>
              )}
            </>
          )}
        </div>
      </div>

      <div className="card">
        <h3>Install</h3>
        <label htmlFor="display-name-input">
          Device name <span className="hint">(e.g. "Kitchen")</span>
        </label>
        <input
          type="text"
          id="display-name-input"
          placeholder="Kitchen"
          maxLength={64}
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
        />

        <label htmlFor="target-host-input" style={{ marginTop: 12 }}>
          Target hostname <span className="hint">(default: <code>fauxnos-client.local</code>)</span>
        </label>
        <input
          type="text"
          id="target-host-input"
          value={targetHost}
          onChange={(e) => setTargetHost(e.target.value)}
        />

        <button
          className="btn-primary"
          onClick={onStart}
          disabled={!displayName.trim() || !targetHost.trim()}
          style={{ marginTop: 12 }}
        >
          Install on {targetHost.trim() || 'fauxnos-client.local'}
        </button>
        {submitError && (
          <div style={{ color: 'var(--red)', marginTop: 8, fontSize: 13 }}>{submitError}</div>
        )}
      </div>
    </>
  )
}
