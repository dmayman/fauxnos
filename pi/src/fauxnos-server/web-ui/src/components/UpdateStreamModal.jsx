import { useEffect, useRef, useState } from 'react'
import { X, CheckCircle2, XCircle, Loader2, Server, Cpu } from 'lucide-react'
import { sseFetch } from '../api'

/**
 * Combined "Update fauxnos" modal — also reused for single-device updates
 * from the DevicePanel. Walks a queue of `steps` (server self-update,
 * then one per client) and streams the SSE response of each step into
 * a single scrolling log.
 *
 * Step shape (built by App.jsx):
 *
 *   {
 *     kind: 'server' | 'client',
 *     label: 'Update Garage',          // shown in the step header
 *     url:   '/api/server/update',
 *     body:  { force: true },          // POSTed as JSON
 *     icon:  'server' | 'device',
 *     clientId?: 'fauxnos002',         // for client steps, used for the
 *                                       //   completion hook
 *     clientName?: 'Garage',
 *   }
 *
 * `waitForServerRestartAfterServerStep`:
 *   When true, after a `kind: 'server'` step's `done` event we poll
 *   /api/server/version until it responds again. That's our signal that
 *   the server's restart completed and we can safely SSH-push to clients
 *   (the per-client endpoint relies on the same server's record_deploy
 *   path, so it needs the server alive). Should be true when the queue
 *   contains both a server step AND client steps; false when only one
 *   leg is queued.
 *
 * Closing the modal mid-queue does NOT cancel the runner — the backend
 * keeps going. The user can reopen and the runner state will be picked
 * up via the GET-stream endpoint (not implemented here; a future
 * iteration could re-attach to in-flight runners).
 */
export default function UpdateStreamModal({
  open,
  onClose,
  title,
  steps = [],
  waitForServerRestartAfterServerStep = false,
  onDone,
}) {
  const [currentStepIdx, setCurrentStepIdx] = useState(0)
  const [phase, setPhase] = useState(null)
  const [status, setStatus] = useState('starting')
  const [lines, setLines] = useState([])
  const [stepResults, setStepResults] = useState([])  // {label, status, error?}
  const [errorMessage, setErrorMessage] = useState(null)
  const logRef = useRef(null)
  const cancelledRef = useRef(false)

  // Auto-scroll log to bottom on new lines.
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [lines])

  // Walk the step queue when the modal opens. Each step runs to completion
  // (or failure) before the next starts.
  useEffect(() => {
    if (!open || steps.length === 0) return
    cancelledRef.current = false
    setCurrentStepIdx(0)
    setPhase(null)
    setStatus('starting')
    setLines([])
    setStepResults([])
    setErrorMessage(null)

    let active = true

    ;(async () => {
      try {
        for (let i = 0; i < steps.length; i++) {
          if (cancelledRef.current || !active) return
          const step = steps[i]
          setCurrentStepIdx(i)
          appendBoundary(setLines, `── ${step.label} (${i + 1}/${steps.length}) ──`)
          setPhase({ name: 'starting', message: step.label })
          setStatus('running')

          let stepStatus = 'failed'
          let stepError = null
          try {
            for await (const ev of sseFetch(step.url, {
              method: 'POST',
              body: JSON.stringify(step.body || {}),
            })) {
              if (cancelledRef.current || !active) return
              if (ev.type === 'phase') setPhase(ev.data)
              else if (ev.type === 'output') {
                setLines((prev) => [...prev, ev.data.line])
              } else if (ev.type === 'snapshot') {
                if (Array.isArray(ev.data?.log_tail)) {
                  // Don't replace the whole log — just append any tail
                  // lines we haven't seen yet. Cheap heuristic: append
                  // every tail line wholesale; duplicates are visible
                  // but acceptable in the rare reattach case.
                  setLines((prev) => [...prev, ...ev.data.log_tail])
                }
              } else if (ev.type === 'done') {
                stepStatus = ev.data?.status || 'succeeded'
                stepError = ev.data?.error || null
                break
              }
            }
          } catch (err) {
            if (err?.status === 200 && err?.body?.status === 'up_to_date') {
              stepStatus = 'up_to_date'
              appendBoundary(setLines, `(${step.label} → already up to date)`)
            } else {
              stepStatus = 'failed'
              stepError = err?.body?.message || err?.message || String(err)
              appendBoundary(setLines, `(${step.label} → error: ${stepError})`)
            }
          }

          setStepResults((prev) => [...prev, { label: step.label, status: stepStatus, error: stepError }])

          if (stepStatus === 'failed' || stepStatus === 'error') {
            setStatus('failed')
            setErrorMessage(stepError || `Step "${step.label}" failed`)
            return
          }

          // If we just finished a server-update step and there are more
          // steps queued, wait for the server's restart to complete.
          if (step.kind === 'server' && waitForServerRestartAfterServerStep && i < steps.length - 1) {
            appendBoundary(setLines, '(waiting for server to restart…)')
            const ok = await pollUntilServerBack(8000, 60_000, () => !cancelledRef.current && active)
            if (!ok) {
              setStatus('failed')
              setErrorMessage('Server did not come back online within 60s after restart.')
              return
            }
            appendBoundary(setLines, '(server back online)')
          }
        }

        setStatus('succeeded')
        if (onDone) onDone()
      } catch (err) {
        if (!active) return
        setStatus('failed')
        setErrorMessage(err?.message || String(err))
      }
    })()

    return () => {
      active = false
      cancelledRef.current = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  if (!open) return null

  const currentStep = steps[currentStepIdx]
  const Icon = currentStep?.icon === 'device' ? Cpu : Server
  const terminal = status === 'succeeded' || status === 'failed'

  return (
    <div className="fx-modal-backdrop" onClick={onClose}>
      <div
        className="fx-modal fx-update-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="fx-update-modal-header">
          <div className="fx-row" style={{ gap: 'var(--fx-2)', alignItems: 'center' }}>
            <Icon size={18} />
            <h2 className="fx-update-modal-title">{title}</h2>
            {steps.length > 1 && (
              <span className="fx-mute fx-update-step-counter">
                {currentStepIdx + 1} / {steps.length}
              </span>
            )}
          </div>
          <button
            type="button"
            className="fx-btn ghost sm"
            onClick={onClose}
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>

        <div className="fx-update-modal-statusbar">
          <StatusBadge status={status} />
          <span className="fx-mute fx-update-phase-text">
            {phaseLabel(phase, status, errorMessage, currentStep)}
          </span>
        </div>

        <div className="fx-update-modal-log" ref={logRef}>
          {lines.length === 0 ? (
            <div className="fx-mute">Waiting for output…</div>
          ) : (
            lines.map((line, i) => (
              <div key={i} className="fx-update-log-line fx-mono">{line || ' '}</div>
            ))
          )}
        </div>

        {terminal && (
          <div className="fx-update-modal-footer">
            <span className="fx-mute">
              {summarizeResults(stepResults)}
            </span>
            <button type="button" className="fx-btn" onClick={onClose}>
              Close
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

function appendBoundary(setLines, label) {
  setLines((prev) => [...prev, '', label, ''])
}

async function pollUntilServerBack(intervalMs, timeoutMs, stillActive) {
  // Two-phase wait that handles the offline-then-back transition without
  // hanging if either side races us.
  //
  // The restart is triggered by a detached `bash -c "sleep 2 && systemctl
  // --user restart fauxnos-server"`, which means the OLD server is still
  // up for ~2s after we receive the SSE `done` event. We need to wait
  // until the restart has actually happened OR confirm it was so fast
  // we missed it.
  //
  // Phase 1 (best-effort, 8s budget): poll for an offline response. If
  //   we see one, the restart is in progress — move to phase 2 immediately.
  //   If we never see offline, that means the whole restart happened
  //   within the 8s window (observed: a graceful systemctl --user
  //   restart fauxnos-server cycle can complete in under a second). Also
  //   valid — proceed to phase 2 to confirm the new server is healthy.
  //
  // Phase 2: poll until ONE successful response. We use AbortController
  //   with a short per-fetch timeout so a hung request can't eat the
  //   whole budget (which was a real bug — the browser's default fetch
  //   timeout is ~60s and would gobble the entire 60s budget in one
  //   stuck request).

  const deadline = Date.now() + timeoutMs

  // Phase 1 — wait for offline, but only briefly.
  await sleep(750)  // small initial buffer for the bash subprocess to fire
  const offlineDeadline = Date.now() + 8_000
  while (Date.now() < offlineDeadline) {
    if (!stillActive()) return false
    try {
      await fetchVersionWithTimeout(2000)
      // Still up. Keep waiting briefly.
      await sleep(400)
    } catch {
      // Saw offline — restart is in progress.
      break
    }
  }

  // Phase 2 — wait for ANY successful response. One is enough; the
  // existing server-update endpoint releases its lock before exiting,
  // and the SSE generator already left the `finally` block, so by the
  // time Flask is responding again all per-request resources are free.
  while (Date.now() < deadline) {
    if (!stillActive()) return false
    try {
      await fetchVersionWithTimeout(4000)
      return true
    } catch {
      // Still offline / still starting up.
    }
    await sleep(intervalMs)
  }
  return false
}

async function fetchVersionWithTimeout(timeoutMs) {
  // AbortController-bounded fetch so a hung request can't stall the
  // poll loop. `getServerVersion()` from api.js is a thin wrapper that
  // doesn't expose AbortSignal yet — inlining the fetch here keeps the
  // change scoped to the polling case.
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const res = await fetch('/api/server/version', { signal: ctrl.signal })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return await res.json()
  } finally {
    clearTimeout(timer)
  }
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms))
}

function StatusBadge({ status }) {
  if (status === 'succeeded') {
    return <span className="fx-badge ok"><CheckCircle2 size={12} /> Succeeded</span>
  }
  if (status === 'failed' || status === 'error') {
    return <span className="fx-badge err"><XCircle size={12} /> Failed</span>
  }
  return <span className="fx-badge"><Loader2 size={12} className="fx-spin" /> Running</span>
}

function phaseLabel(phase, status, errorMessage, currentStep) {
  if (status === 'failed' && errorMessage) return errorMessage
  if (phase?.message) return phase.message
  if (currentStep?.label) return currentStep.label
  if (status === 'starting') return 'Starting…'
  return null
}

function summarizeResults(results) {
  if (results.length === 0) return ''
  const ok = results.filter(r => r.status === 'succeeded' || r.status === 'up_to_date').length
  const fail = results.filter(r => r.status === 'failed' || r.status === 'error').length
  return `${ok}/${results.length} succeeded${fail > 0 ? `, ${fail} failed` : ''}`
}
