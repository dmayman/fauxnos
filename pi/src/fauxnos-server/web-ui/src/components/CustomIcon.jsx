import { useState, useEffect } from 'react'

// The full icon catalog lives in iconData.js — a ~420 KB eager SVG glob of all
// 6,146 Tabler icons. CustomIcon is rendered by always-loaded components
// (SourcePopover, DevicePanel, IconPickerButton), so a *static* import of
// iconData here drags that whole catalog into the first-paint main bundle
// (the FX-56 leak). Instead we dynamic-import it on demand: Vite splits it into
// the same lazy chunk the IconPicker already uses, so it stays off the
// first-paint path and is fetched once, shared, and cached.
let iconDataPromise = null
function loadIconData() {
  if (!iconDataPromise) iconDataPromise = import('../icons/iconData')
  return iconDataPromise
}

export default function CustomIcon({ name, size = 16, ariaHidden = true }) {
  const [resolved, setResolved] = useState({ name: undefined, svg: null })

  useEffect(() => {
    if (!name) return undefined
    let alive = true
    loadIconData().then(({ getIconSvg }) => {
      if (alive) setResolved({ name, svg: getIconSvg(name) })
    })
    return () => { alive = false }
  }, [name])

  if (!name) return null

  const done = resolved.name === name
  // Resolved, but the name didn't map to an SVG → render nothing (matches the
  // old synchronous getIconSvg→null behavior).
  if (done && !resolved.svg) return null

  // Either still loading the catalog, or resolved with an SVG. Render the sized
  // span either way — reserving the footprint while loading avoids card reflow
  // when the SVG pops in.
  return (
    <span
      className="fx-custom-icon"
      style={{ width: size, height: size }}
      aria-hidden={ariaHidden}
      dangerouslySetInnerHTML={done ? { __html: resolved.svg } : undefined}
    />
  )
}
