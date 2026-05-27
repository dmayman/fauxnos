import { useCallback, useRef } from 'react'

/**
 * Track cursor position over a slider track and expose it via the
 * `--hover-pct` CSS variable + a `data-hovering` attribute on the
 * element. The preview overlay's width and visibility key off those,
 * so dragging the cursor doesn't trigger a React re-render per move.
 *
 * Usage:
 *   const hover = useSliderHover()
 *   <div ref={hover.ref} onPointerMove={hover.onPointerMove} onPointerLeave={hover.onPointerLeave}>
 *     <div className="…-hover" />   {/* width: var(--hover-pct, 0%) }
 *     …
 *   </div>
 */
export function useSliderHover() {
  const ref = useRef(null)
  const onPointerMove = useCallback((e) => {
    const el = ref.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    if (rect.width <= 0) return
    const pct = ((e.clientX - rect.left) / rect.width) * 100
    el.style.setProperty('--hover-pct', `${Math.max(0, Math.min(100, pct))}%`)
    el.dataset.hovering = 'true'
  }, [])
  const onPointerLeave = useCallback(() => {
    const el = ref.current
    if (!el) return
    delete el.dataset.hovering
  }, [])
  return { ref, onPointerMove, onPointerLeave }
}
