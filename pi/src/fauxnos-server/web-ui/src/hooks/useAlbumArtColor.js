import { useEffect, useState } from 'react'

/* ─────────────────────────────────────────────────────────────────────────────
 * Album-art dominant color extraction (no deps, ~80 LOC).
 *
 * Load the art into an offscreen 32×32 canvas, run an OKLCH histogram by
 * hue (10° bins), pick the bucket with the highest sum-of-chroma. That's
 * "most-saturated dominant hue" — robust against near-gray covers and
 * single-pixel outliers.
 *
 * Returns { h, c, l } in raw OKLCH (h 0-360, c 0-~0.4, l 0-1) or null
 * when extraction fails / produces a near-grayscale result. Caller is
 * expected to apply mode-specific lightness/chroma clamps for legibility
 * against light vs dark surfaces.
 *
 * Memoized by URL via a module-level Map so identical art across multiple
 * cards extracts once.
 * ────────────────────────────────────────────────────────────────────────── */

const cache = new Map()

function srgb2linear(c) {
  c = c / 255
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
}

/* sRGB → OKLCH. Math from Björn Ottosson's OKLab post. */
function rgbToOklch(r, g, b) {
  const lr = srgb2linear(r), lg = srgb2linear(g), lb = srgb2linear(b)
  const l_ = Math.cbrt(0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb)
  const m_ = Math.cbrt(0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb)
  const s_ = Math.cbrt(0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb)
  const L  = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
  const a  = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
  const bb = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
  const C = Math.sqrt(a * a + bb * bb)
  let h = Math.atan2(bb, a) * 180 / Math.PI
  if (h < 0) h += 360
  return { L, C, h }
}

function extractDominantColor(img) {
  const sz = 32
  const cv = document.createElement('canvas')
  cv.width = sz; cv.height = sz
  const ctx = cv.getContext('2d', { willReadFrequently: true })
  ctx.drawImage(img, 0, 0, sz, sz)
  let data
  try {
    data = ctx.getImageData(0, 0, sz, sz).data
  } catch (e) {
    // Canvas tainted (CORS blocked) — extraction impossible.
    return null
  }

  const buckets = new Array(36)
  for (let i = 0; i < 36; i++) buckets[i] = { count: 0, sumC: 0, sumL: 0, sumH: 0 }

  for (let i = 0; i < data.length; i += 4) {
    if (data[i + 3] < 200) continue
    const r = data[i], g = data[i + 1], b = data[i + 2]
    const { L, C, h } = rgbToOklch(r, g, b)
    if (C < 0.04) continue          // skip near-grayscale
    if (L < 0.1 || L > 0.95) continue // skip near-black + near-white (cover edges)
    const bin = Math.floor(h / 10) % 36
    buckets[bin].count += 1
    buckets[bin].sumC += C
    buckets[bin].sumL += L
    buckets[bin].sumH += h
  }

  let bestIdx = -1, bestScore = 0
  for (let i = 0; i < 36; i++) {
    if (buckets[i].sumC > bestScore) {
      bestScore = buckets[i].sumC
      bestIdx = i
    }
  }
  if (bestIdx < 0) return null

  const b = buckets[bestIdx]
  return {
    h: b.sumH / b.count,
    c: b.sumC / b.count,
    l: b.sumL / b.count,
  }
}

export default function useAlbumArtColor(artUrl) {
  const [color, setColor] = useState(() => (artUrl && cache.has(artUrl)) ? cache.get(artUrl) : null)

  useEffect(() => {
    if (!artUrl) {
      setColor(null)
      return
    }
    if (cache.has(artUrl)) {
      setColor(cache.get(artUrl))
      return
    }
    let cancelled = false
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => {
      if (cancelled) return
      const result = extractDominantColor(img)
      cache.set(artUrl, result)
      setColor(result)
    }
    img.onerror = () => {
      if (cancelled) return
      cache.set(artUrl, null)
      setColor(null)
    }
    img.src = artUrl
    return () => { cancelled = true }
  }, [artUrl])

  return color
}
