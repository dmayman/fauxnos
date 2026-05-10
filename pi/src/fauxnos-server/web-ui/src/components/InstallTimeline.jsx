import { useEffect, useMemo, useState } from 'react'
import { apiFetch, subscribeInstallStream } from '../api'

/**
 * Vertical timeline rendered while an install is running (or terminal).
 *
 * Subscribes to /api/install/stream on mount and merges incoming `step`/`tail`
 * events into local state. Hydrates from /api/install/status first so a
 * mid-install reload re-renders the in-progress timeline immediately.
 */
export default function InstallTimeline({ onDone, onRetry }) {
  const [snapshot, setSnapshot] = useState(null)
  const [showLog, setShowLog] = useState(false)
  const [, forceTick] = useState(0)

  // Re-render once a second so durations on active steps tick up.
  useEffect(() => {
    const t = setInterval(() => forceTick((n) => n + 1), 1000)
    return () => clearInterval(t)
  }, [])

  // Hydrate + subscribe to the stream.
  useEffect(() => {
    let alive = true
    apiFetch('/api/install/status').then((s) => {
      if (alive && s && s.steps) setSnapshot(s)
    }).catch(() => {})

    const unsub = subscribeInstallStream(({ type, data }) => {
      if (!alive) return
      if (type === 'snapshot' || type === 'done') {
        setSnapshot(data)
        if (type === 'done' && onDone) onDone(data)
        return
      }
      if (type === 'step') {
        setSnapshot((prev) => mergeStep(prev, data))
        return
      }
      if (type === 'tail') {
        setSnapshot((prev) => appendTail(prev, data))
        return
      }
    })

    return () => { alive = false; unsub() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (!snapshot || !snapshot.steps) {
    return (
      <div className="waiting"><span className="spinner" /> Connecting…</div>
    )
  }

  const terminal = snapshot.status === 'succeeded' || snapshot.status === 'failed' || snapshot.status === 'cancelled'

  // A failed step can carry a `fallback_kind` marker the runner attached when
  // the failure has a known one-shot fix. The only one today is
  // "auth_key_missing" (server's install key isn't in the Pi's
  // authorized_keys). Surface it inline so the user can recover without
  // bouncing back through PreInstallView.
  const fallbackStep = snapshot.steps.find((s) => s.fallback_kind)

  return (
    <div>
      <div className="timeline">
        {snapshot.steps.map((step) => (
          <TimelineStep key={step.id} step={step} active={snapshot.current_step === step.id && !terminal} />
        ))}
      </div>

      {snapshot.status === 'succeeded' && (
        <div className="timeline-banner success">
          ✓ Installed{snapshot.client_id ? ` as ${snapshot.client_id}` : ''}
          {snapshot.display_name ? ` — ${snapshot.display_name}` : ''}
        </div>
      )}
      {snapshot.status === 'failed' && (
        <div className="timeline-banner failure">
          ✗ Install failed{snapshot.error ? `: ${snapshot.error}` : ''}
        </div>
      )}
      {snapshot.status === 'cancelled' && (
        <div className="timeline-banner failure">Install cancelled</div>
      )}

      {fallbackStep && fallbackStep.fallback_kind === 'auth_key_missing' && (
        <AuthKeyMissingFallback
          targetHost={snapshot.target_host}
          onRetry={onRetry}
        />
      )}

      <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
        {!terminal && (
          <button
            className="btn-secondary"
            onClick={() => apiFetch('/api/install/cancel', { method: 'POST' }).catch(() => {})}
          >
            Cancel install
          </button>
        )}
        <button className="btn-secondary" onClick={() => setShowLog((s) => !s)}>
          {showLog ? 'Hide install log' : 'Show install log'}
        </button>
      </div>

      {showLog && <InstallLog steps={snapshot.steps} />}
    </div>
  )
}

function TimelineStep({ step, active }) {
  const dotClass = useMemo(() => {
    if (step.status === 'succeeded') return 'done'
    if (step.status === 'active') return 'active'
    if (step.status === 'stalled') return 'stalled'
    if (step.status === 'failed') return 'failed'
    if (step.status === 'skipped') return 'skipped'
    return ''
  }, [step.status])

  // Only show the running tail line for the active/stalled step.
  const showTail = step.status === 'active' || step.status === 'stalled' || step.status === 'failed'
  const tailLine = showTail && step.log_tail && step.log_tail.length
    ? step.log_tail[step.log_tail.length - 1]
    : null

  const duration = formatDuration(step)

  return (
    <div className={`timeline-step ${step.status === 'succeeded' ? 'done' : ''} ${step.status}`}>
      <div className="timeline-rail">
        <div className={`timeline-dot ${dotClass}`} />
        <div className="timeline-connector" />
      </div>
      <div className="timeline-body">
        <div className="timeline-label">{step.label}</div>
        {step.note && <div className="timeline-note">{step.note}</div>}
        {tailLine && <div className="timeline-tail">{tailLine}</div>}
      </div>
      <div className="timeline-duration">{duration}</div>
    </div>
  )
}

/**
 * Inline recovery panel for the "server's install key isn't authorized on the
 * target Pi" failure. Renders the exact two-step Mac command (with the user's
 * target_host baked in) plus a Retry button that re-POSTs /api/install/start
 * via the parent's onRetry callback.
 */
function AuthKeyMissingFallback({ targetHost, onRetry }) {
  const [copied, setCopied] = useState(false)
  // The wizard is served by the same Flask process that hosts
  // /api/install/server-pubkey, so window.location.host already points at the
  // right server:port for the curl call.
  const serverOrigin = window.location.host
  const command = [
    `# 1. Drop the stale host key from your Mac's known_hosts (harmless if absent)`,
    `ssh-keygen -R ${targetHost}`,
    ``,
    `# 2. Append the server's install pubkey to the fresh Pi's authorized_keys`,
    `curl -sS http://${serverOrigin}/api/install/server-pubkey | \\`,
    `  ssh -o StrictHostKeyChecking=accept-new user@${targetHost} \\`,
    `  'mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat - >> ~/.ssh/authorized_keys && sort -u ~/.ssh/authorized_keys -o ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys'`,
  ].join('\n')

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      window.prompt('Copy this command:', command)
    }
  }

  return (
    <div className="card" style={{ marginTop: 12 }}>
      <h4 style={{ marginTop: 0 }}>Authorize the server's key from your workstation</h4>
      <p style={{ marginTop: 4, fontSize: 13, lineHeight: 1.5 }}>
        The server reached <code>{targetHost}</code> but its install key isn't in{' '}
        <code>~/.ssh/authorized_keys</code> on the Pi (Pi Imager may only have kept your
        personal key). Run this on the workstation that can already SSH to the Pi, then
        click Retry:
      </p>
      <div className="pubkey-block">
        <pre>{command}</pre>
        <button className={`pubkey-copy ${copied ? 'copied' : ''}`} onClick={copy}>
          {copied ? '✓ Copied' : '📋 Copy'}
        </button>
      </div>
      {onRetry && (
        <button className="btn-primary" onClick={onRetry} style={{ marginTop: 8 }}>
          Retry SSH
        </button>
      )}
    </div>
  )
}

function InstallLog({ steps }) {
  // Concatenate every step's tail buffer with headers — useful for failure
  // post-mortem and for the "Show install log" toggle on a successful run.
  const text = steps.map((s) => {
    const head = `── ${s.label} (${s.status}) ──`
    const body = (s.log_tail || []).join('\n')
    return `${head}\n${body || '(no output captured)'}`
  }).join('\n\n')
  return <pre className="timeline-log">{text}</pre>
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function mergeStep(snapshot, stepData) {
  if (!snapshot) return snapshot
  // The runner emits a partial-payload step event when only client_id is
  // known (no step.id). Treat that as a top-level merge.
  if (stepData && stepData.client_id && !stepData.id) {
    return { ...snapshot, client_id: stepData.client_id }
  }
  if (!stepData || !stepData.id) return snapshot
  const steps = snapshot.steps.map((s) => s.id === stepData.id ? { ...s, ...stepData } : s)
  const current = stepData.status === 'active' || stepData.status === 'stalled'
    ? stepData.id
    : snapshot.current_step
  return { ...snapshot, steps, current_step: current }
}

function appendTail(snapshot, tailData) {
  if (!snapshot || !tailData || !tailData.step_id) return snapshot
  const steps = snapshot.steps.map((s) => {
    if (s.id !== tailData.step_id) return s
    const tail = (s.log_tail || []).slice(-19)  // keep last 19, append → 20
    tail.push(tailData.line)
    return { ...s, log_tail: tail }
  })
  return { ...snapshot, steps }
}

function formatDuration(step) {
  if (!step.started_at) return ''
  const start = Date.parse(step.started_at)
  const end = step.ended_at ? Date.parse(step.ended_at) : Date.now()
  const sec = Math.max(0, Math.round((end - start) / 1000))
  if (sec < 1) return '<1s'
  if (sec < 60) return `${sec}s`
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return s ? `${m}m ${s}s` : `${m}m`
}
