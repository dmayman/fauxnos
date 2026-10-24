import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

/**
 * Popover portaled to <body> (cards and panels clip overflow), hung below its
 * anchor on whichever side keeps it on screen. Closes on an outside click.
 * It copies the anchor's --art-* tokens so it matches a tinted card.
 */
export default function AnchoredPopover({ anchorRef, onClose, className = '', role, children }) {
  const ref = useRef(null)
  const [style, setStyle] = useState(null)
  useEffect(() => {
    const place = () => {
      const el = anchorRef.current
      if (!el) return
      const r = el.getBoundingClientRect()
      const cs = getComputedStyle(el)
      const tokens = {}
      for (const t of ['--art-accent', '--art-accent-soft']) {
        const v = cs.getPropertyValue(t).trim()
        if (v) tokens[t] = v
      }
      const side = r.left > window.innerWidth / 2
        ? { right: Math.max(8, window.innerWidth - r.right), left: 'auto' }
        : { left: Math.max(8, r.left), right: 'auto' }
      // Open upward when there's no room below.
      const vertical = r.bottom + 240 > window.innerHeight && r.top > 240
        ? { bottom: window.innerHeight - r.top + 8, top: 'auto' }
        : { top: r.bottom + 8, bottom: 'auto' }
      setStyle({ ...vertical, ...side, ...tokens })
    }
    place()
    const onDown = (e) => {
      if (ref.current?.contains(e.target) || anchorRef.current?.contains(e.target)) return
      onClose()
    }
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
    }
  }, [anchorRef, onClose])
  if (!style) return null
  return createPortal(
    <div ref={ref} className={`fx-popover fx-source-popover ${className}`} role={role} style={style}>
      {children}
    </div>,
    document.body,
  )
}
