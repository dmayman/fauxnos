import { useEffect, useRef, useState } from 'react'
import { X, CheckCircle2, XCircle, Loader2, Server, Cpu } from 'lucide-react'
import { sseFetch } from '../api'

/**
 * SSE-streaming modal used by both the "Update server" pill (server self-
 * update via git pull) and the per-device "Update" buttons in the Devices
 * popover (client update via SSH + install.sh).
 *
 * Props:
 *   open       — boolean, render when true
 *   onClose    — close handler
 *   title      — string, header label ("Update server", "Update Garage", …)
 *   icon       — 'server' | 'device' — header glyph
 *   url        — POST endpoint to stream
 *   body       — optional request body (will be JSON-stringified)
 *   onDone     — optional callback (data) when a `done` event arrives;
 *                useful for refreshing version state after a successful run
 *
 * Renders a sticky header with current phase + status, an auto-scrolling
 * output log, and a single close button. Closing mid-stream does NOT
 * cancel the runner — the backend keeps going; the user can re-open later
 * to attach to the stream endpoint (server side preserves recent state).
 */
export default function UpdateStreamModal({
  open,
  onClose,
  title,
  icon = 'server',
  url,
  body = {},
  onDone,
}) {
  const [phase, setPhase] = useState(null)        // {name, message, …}
  const [status, setStatus] = useState('starting') // starting|running|succeeded|failed|already_up_to_date|error
  const [lines, setLines] = useState([])           // output log
  const [errorMessage, setErrorMessage] = useState(null)
  const [doneData, setDoneData] = useState(null)
  const logRef = useRef(null)
  const cancelledRef = useRef(false)

  // Auto-scroll log to bottom when new lines arrive. `behavior: 'instant'`
  // (default) keeps the cursor pinned during fast streaming.
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [lines])

  // Kick off the SSE stream when the modal opens. Re-running this effect
  // when `url` changes lets the parent reuse the same modal for different
  // updates (close + reopen with new url).
  useEffect(() => {
    if (!open) return
    // Reset state for a fresh run.
    cancelledRef.current = false
    setPhase(null)
    setStatus('starting')
    setLines([])
    setErrorMessage(null)
    setDoneData(null)

    let active = true
    ;(async () => {
      try {
        for await (const ev of sseFetch(url, {
          method: 'POST',
          body: JSON.stringify(body),
        })) {
          if (!active || cancelledRef.current) break
          if (ev.type === 'phase') {
            setPhase(ev.data)
            setStatus('running')
          } else if (ev.type === 'output') {
            setLines((prev) => [...prev, ev.data.line])
          } else if (ev.type === 'snapshot') {
            // Client-update endpoint sends a snapshot first; surface its
            // status so the UI doesn't show "starting" for the whole run.
            if (ev.data?.status) setStatus(ev.data.status)
            if (Array.isArray(ev.data?.log_tail)) {
              setLines(ev.data.log_tail)
            }
          } else if (ev.type === 'done') {
            const s = ev.data?.status || 'succeeded'
            setStatus(s)
            setDoneData(ev.data)
            if (onDone) onDone(ev.data)
            break
          }
        }
      } catch (err) {
        if (!active) return
        // 200 up_to_date isn't an error — the JSON body comes back instead
        // of an SSE stream. sseFetch treats !res.ok as error, so 200s
        // without a stream body fall through to here.
        if (err?.status === 200 && err?.body?.status === 'up_to_date') {
          setStatus('already_up_to_date')
          setErrorMessage(err.body.message || null)
          return
        }
        setStatus('error')
        setErrorMessage(err?.body?.message || err?.message || String(err))
      }
    })()

    return () => {
      active = false
      cancelledRef.current = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, url])

  if (!open) return null

  const Icon = icon === 'device' ? Cpu : Server
  const terminal = status === 'succeeded' || status === 'failed' || status === 'error' || status === 'already_up_to_date'

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
            {phaseLabel(phase, status, errorMessage)}
          </span>
        </div>

        <div className="fx-update-modal-log" ref={logRef}>
          {lines.length === 0 ? (
            <div className="fx-mute">Waiting for output…</div>
          ) : (
            lines.map((line, i) => (
              <div key={i} className="fx-update-log-line fx-mono">{line || ' '}</div>
            ))
          )}
        </div>

        {terminal && (
          <div className="fx-update-modal-footer">
            {doneData?.new_short_sha && (
              <span className="fx-mute fx-mono">
                {doneData.new_short_sha}
              </span>
            )}
            {doneData?.deployed_sha && (
              <span className="fx-mute fx-mono">
                deployed → {doneData.deployed_sha.slice(0, 7)}
              </span>
            )}
            <button type="button" className="fx-btn" onClick={onClose}>
              Close
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

function StatusBadge({ status }) {
  if (status === 'succeeded' || status === 'already_up_to_date') {
    return <span className="fx-badge ok"><CheckCircle2 size={12} /> {status === 'already_up_to_date' ? 'Up to date' : 'Succeeded'}</span>
  }
  if (status === 'failed' || status === 'error') {
    return <span className="fx-badge err"><XCircle size={12} /> Failed</span>
  }
  return <span className="fx-badge"><Loader2 size={12} className="fx-spin" /> Running</span>
}

function phaseLabel(phase, status, errorMessage) {
  if (status === 'already_up_to_date') {
    return errorMessage || 'Already at origin/main.'
  }
  if (status === 'error') {
    return errorMessage || 'Update failed.'
  }
  if (phase?.message) return phase.message
  if (status === 'starting') return 'Starting…'
  if (status === 'running') return 'Running…'
  return null
}
