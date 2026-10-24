import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { IconX } from '@tabler/icons-react'

/* ─────────────────────────────────────────────────────────────────────────────
 * Toasts — short messages stacked at the bottom of the screen.
 *
 *   const toast = useToast()
 *   const id = toast.show('Uploading 3 files', { progress: 0 })
 *   toast.update(id, { progress: 0.5 })
 *   toast.update(id, { message: 'Added 3 songs', progress: null, kind: 'success' })
 *
 * A toast closes itself after a few seconds unless it shows progress or a
 * spinner (`busy`), which stay until updated.
 * ────────────────────────────────────────────────────────────────────────── */

const ToastContext = createContext(null)
export const useToast = () => useContext(ToastContext)

const LIFETIME_MS = 4000

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const timers = useRef({})
  const nextId = useRef(1)

  const dismiss = useCallback((id) => {
    clearTimeout(timers.current[id])
    delete timers.current[id]
    setToasts(prev => prev.filter(t => t.id !== id))
  }, [])

  const schedule = useCallback((t) => {
    clearTimeout(timers.current[t.id])
    if (t.progress == null && !t.busy) {
      timers.current[t.id] = setTimeout(() => dismiss(t.id), t.kind === 'error' ? LIFETIME_MS * 2 : LIFETIME_MS)
    }
  }, [dismiss])

  const show = useCallback((message, opts = {}) => {
    const t = { id: nextId.current++, message, kind: 'info', progress: null, busy: false, ...opts }
    setToasts(prev => [...prev, t])
    schedule(t)
    return t.id
  }, [schedule])

  const update = useCallback((id, patch) => {
    setToasts(prev => prev.map(t => {
      if (t.id !== id) return t
      const next = { ...t, ...patch }
      schedule(next)
      return next
    }))
  }, [schedule])

  const api = useMemo(() => ({
    show,
    update,
    dismiss,
    error: (message) => show(message, { kind: 'error' }),
    success: (message) => show(message, { kind: 'success' }),
  }), [show, update, dismiss])

  return (
    <ToastContext.Provider value={api}>
      {children}
      {createPortal(
        <div className="fx-toasts" role="status" aria-live="polite">
          {toasts.map(t => (
            <div key={t.id} className={`fx-toast ${t.kind}`}>
              {t.busy && <span className="fx-spinner" />}
              <span className="fx-toast-text">{t.message}</span>
              {t.progress != null && (
                <span className="fx-toast-progress"><span style={{ width: `${Math.round(t.progress * 100)}%` }} /></span>
              )}
              <button type="button" className="fx-icon-btn sm" aria-label="Dismiss" onClick={() => dismiss(t.id)}>
                <IconX size={14} />
              </button>
            </div>
          ))}
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  )
}
