import { useState, useRef, useEffect, Suspense, lazy } from 'react'
import { IconPlusFilled } from '@tabler/icons-react'
import CustomIcon from './CustomIcon'

// IconPicker stays lazy — it's the heavy component (full icon grid + search).
// CustomIcon is tiny (renders one inline SVG via iconData lookup), so eager-
// importing it avoids the flash-of-fallback when source rows first paint.
const IconPicker = lazy(() => import('./IconPicker'))

export default function IconPickerButton({ value, onChange }) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const handle = (e) => {
      if (!wrapRef.current?.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handle)
    return () => document.removeEventListener('mousedown', handle)
  }, [open])

  return (
    <div className="fx-icon-picker-trigger-wrap" ref={wrapRef}>
      <button
        type="button"
        className="fx-icon-picker-trigger"
        onClick={() => setOpen(v => !v)}
        title={value ? `Icon: ${value.replace(/-/g, ' ')}` : 'Pick an icon'}
        aria-label="Pick an icon"
        aria-expanded={open}
      >
        {value ? (
          <CustomIcon name={value} size={18} />
        ) : (
          <IconPlusFilled size={18} aria-hidden />
        )}
      </button>
      {open && (
        <div className="fx-popover fx-icon-picker-popover" onMouseDown={e => e.stopPropagation()}>
          <Suspense fallback={<div className="fx-icon-picker-loading fx-mute">Loading icons…</div>}>
            <IconPicker
              value={value}
              onSelect={(name) => { onChange(name); setOpen(false) }}
            />
          </Suspense>
        </div>
      )}
    </div>
  )
}
