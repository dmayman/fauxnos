import { useEffect, useState } from 'react'

/* ─────────────────────────────────────────────────────────────────────────────
 * The playing cover rendered full-bleed behind the whole page — scaled up,
 * blurred, and masked to fade out down the screen. The web port of iOS
 * BlurArtBackdrop.swift (FX-77); the look constants are its baked defaults
 * (scale 1.25, blur 52, opacity .79 dark / .74 light, fade to nothing at 82%
 * of the viewport). There's no glass/material layer — the blurred cover IS the
 * backdrop, and it shows through the cards via their translucent fills.
 *
 * On a track change the outgoing cover stays mounted and cross-fades, so the
 * ground never washes through mid-swap. The parallax slide iOS does on top of
 * that is not ported.
 * ────────────────────────────────────────────────────────────────────────── */

const XFADE_MS = 600

export default function ArtBackdrop({ url }) {
  const [current, setCurrent] = useState(url)
  const [outgoing, setOutgoing] = useState(null)

  useEffect(() => {
    if (url === current) return
    setOutgoing(current)
    setCurrent(url)
    const t = setTimeout(() => setOutgoing(null), XFADE_MS)
    return () => clearTimeout(t)
  }, [url, current])

  if (!current && !outgoing) return null
  return (
    <div className="fx-art-backdrop" aria-hidden>
      {/* Outgoing sits on top and fades away over the incoming, which is
          already opaque underneath — a plain cross-dissolve would dip
          coverage at the midpoint and flash the ground. */}
      {current && <img src={current} alt="" />}
      {outgoing && <img src={outgoing} alt="" className="is-outgoing" />}
    </div>
  )
}
