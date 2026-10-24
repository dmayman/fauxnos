import { useState } from 'react'
import { createPortal } from 'react-dom'
import { IconX } from '@tabler/icons-react'

/**
 * A small centred dialog with text fields and a submit button — new
 * playlist, rename playlist, edit a track's details.
 *
 *   <FormModal title="Rename playlist" submitLabel="Save"
 *     fields={[{ name: 'name', label: 'Name', value: p.name }]}
 *     onSubmit={async ({ name }) => ...} onClose={...} />
 *
 * onSubmit may throw; the dialog stays open and shows nothing extra (the
 * caller toasts the error).
 */
export default function FormModal({ title, fields, submitLabel = 'Save', onSubmit, onClose }) {
  const [values, setValues] = useState(() => Object.fromEntries(fields.map(f => [f.name, f.value || ''])))
  const [busy, setBusy] = useState(false)
  const required = fields.filter(f => f.required)
  const canSubmit = !busy && required.every(f => values[f.name].trim())

  const submit = async (e) => {
    e.preventDefault()
    if (!canSubmit) return
    setBusy(true)
    try {
      await onSubmit(values)
      onClose()
    } catch {
      setBusy(false)
    }
  }

  return createPortal(
    <div className="fx-modal-backdrop fx-form-modal-backdrop" onMouseDown={onClose}>
      <form
        className="fx-modal fx-form-modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onMouseDown={(e) => e.stopPropagation()}
        onSubmit={submit}
      >
        <div className="fx-form-modal-head">
          <span className="fx-h2">{title}</span>
          <button type="button" className="fx-icon-btn" aria-label="Close" onClick={onClose}>
            <IconX size={18} />
          </button>
        </div>
        {fields.map((f, i) => (
          <label key={f.name} className="fx-form-modal-field">
            <span>{f.label}</span>
            <input
              className="fx-input"
              value={values[f.name]}
              placeholder={f.placeholder}
              autoFocus={i === 0}
              onChange={(e) => setValues(v => ({ ...v, [f.name]: e.target.value }))}
            />
          </label>
        ))}
        <div className="fx-form-modal-actions">
          <button type="button" className="fx-btn ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="fx-btn primary" disabled={!canSubmit}>{submitLabel}</button>
        </div>
      </form>
    </div>,
    document.body,
  )
}
