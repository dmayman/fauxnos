import { useEffect, useState } from 'react'
import { Copy, Check, Play } from 'lucide-react'
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

  // Re-run the install with the same display_name + target_host we already
  // have in state — used by the InstallTimeline's auth-failure recovery
  // panel after the user manually authorizes the server's key on the Pi.
  // Keeps the wizard on the timeline view instead of bouncing back to
  // PreInstallView (where the user would have to re-type the device name).
  const retry = async () => {
    setSubmitError('')
    try {
      await apiFetch('/api/install/start', {
        method: 'POST',
        body: JSON.stringify({ display_name: displayName.trim(), target_host: targetHost.trim() }),
      })
      setCompleted(null)
      setResetTick((n) => n + 1)
    } catch (e) {
      setSubmitError(String(e.message || e))
    }
  }

  return (
    <div className="fx-add-device">
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
        <div className="fx-card">
          <h3 className="fx-h2" style={{ marginBottom: 'var(--fx-3)' }}>
            {completed?.status === 'succeeded' ? 'Install complete' : 'Installing'}
          </h3>
          <InstallTimeline key={resetTick} onDone={onDone} onRetry={retry} />
          {completed && (
            <div style={{ marginTop: 'var(--fx-4)' }}>
              <button className="fx-btn" onClick={reset}>
                {completed.status === 'succeeded' ? 'Install another' : 'Try again'}
              </button>
            </div>
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
    <div className="fx-stack" style={{ gap: 'var(--fx-4)' }}>
      <div className="fx-card">
        <h3 className="fx-h3" style={{ marginBottom: 'var(--fx-2)' }}>Prerequisites</h3>
        <ul className="fx-prereq-list">
          <li>Flash <strong>Raspberry Pi OS Lite (64-bit, Bookworm)</strong> with Pi Imager — <em>not</em> Trixie, not Desktop.</li>
          <li>In Pi Imager, set hostname <code className="fx-mono">fauxnos-client</code>, username <code className="fx-mono">user</code>, a per-Pi password (save in 1Password).</li>
          <li>Configure WiFi credentials and locale.</li>
          <li>Enable SSH → "Allow public-key authentication only" → paste <strong>both</strong> keys below.</li>
        </ul>
      </div>

      <div className="fx-card">
        <h3 className="fx-h3" style={{ marginBottom: 'var(--fx-2)' }}>SSH keys to paste in Pi Imager</h3>
        <p className="fx-small">1) Your personal public key (from 1Password — the one you use to SSH into other fauxnos Pis).</p>
        <p className="fx-small" style={{ marginTop: 'var(--fx-2)' }}>
          2) This server's install key — needed so the wizard can SSH in and run the install:
        </p>
        <div className="fx-codeblock" style={{ marginTop: 'var(--fx-2)' }}>
          {pubkeyError ? (
            <pre style={{ color: 'var(--fx-err)' }}>{pubkeyError}</pre>
          ) : (
            <>
              <pre>{pubkey || 'Loading…'}</pre>
              {pubkey && (
                <button className={`fx-codeblock-copy${copied ? ' copied' : ''}`} onClick={copyPubkey}>
                  {copied ? <><Check size={12} /> Copied</> : <><Copy size={12} /> Copy</>}
                </button>
              )}
            </>
          )}
        </div>
      </div>

      <div className="fx-card">
        <h3 className="fx-h3" style={{ marginBottom: 'var(--fx-3)' }}>Install</h3>
        <div className="fx-stack" style={{ gap: 'var(--fx-3)' }}>
          <div>
            <label className="fx-label" htmlFor="display-name-input">
              Device name <span className="fx-mute-2">(e.g. "Kitchen")</span>
            </label>
            <input
              type="text"
              id="display-name-input"
              className="fx-input"
              placeholder="Kitchen"
              maxLength={64}
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
            />
          </div>
          <div>
            <label className="fx-label" htmlFor="target-host-input">
              Target hostname <span className="fx-mute-2">(default: <code className="fx-mono">fauxnos-client.local</code>)</span>
            </label>
            <input
              type="text"
              id="target-host-input"
              className="fx-input"
              value={targetHost}
              onChange={(e) => setTargetHost(e.target.value)}
            />
          </div>
          <div>
            <button
              className="fx-btn primary"
              onClick={onStart}
              disabled={!displayName.trim() || !targetHost.trim()}
            >
              <Play size={14} /> Install on {targetHost.trim() || 'fauxnos-client.local'}
            </button>
          </div>
          {submitError && (
            <div className="fx-banner err">
              <span>{submitError}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
