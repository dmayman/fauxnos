/* ─────────────────────────────────────────────────────────────────────────────
 * Generated "album art" for the Noise source: a gradient square in the
 * colour's shades, with soft highlights and shadows in the corners and the
 * wave-sine glyph in the middle. Drawn once per colour to a canvas and
 * returned as a data URL, so it runs through exactly the same path as a
 * Spotify cover: the card art tile, useAlbumArtColor's tint, and the blurred
 * page backdrop.
 * ────────────────────────────────────────────────────────────────────────── */

const SIZE = 256

// Tabler's outline wave-sine path (24×24 viewBox, stroke 2) — the same glyph
// the source uses everywhere else.
const WAVE_PATH = 'M21 12h-2c-.894 0 -1.662 -.857 -1.761 -2c-.296 -3.45 -.749 -6 -2.749 -6s-2.5 3.582 -2.5 8s-.5 8 -2.5 8s-2.452 -2.547 -2.749 -6c-.1 -1.147 -.867 -2 -1.763 -2h-2'

// from → to run top-left → bottom-right. Each corner glow is
// [corner, colour, strength]; corners are tl, tr, bl, br. White is a cool
// pearl rather than pure grey so the art tint has some hue to pick up
// (useAlbumArtColor skips near-grey pixels).
const LOOKS = {
  brown: {
    from: '#a8734a', to: '#3b2314',
    glows: [['tl', '#e6c39c', 0.65], ['br', '#160c06', 0.7], ['tr', '#c2652f', 0.35]],
    glyph: 'rgba(255, 244, 232, 0.92)',
  },
  pink: {
    from: '#f2a3c0', to: '#7e2b55',
    glows: [['tr', '#ffe2ec', 0.7], ['bl', '#3a0f25', 0.6], ['tl', '#e0607f', 0.3]],
    glyph: 'rgba(255, 245, 249, 0.94)',
  },
  white: {
    from: '#f4f6fc', to: '#9aa4c4',
    glows: [['tl', '#ffffff', 0.8], ['br', '#5e6786', 0.55], ['bl', '#c9cfe6', 0.4]],
    glyph: 'rgba(52, 58, 80, 0.85)',
  },
}

const CORNERS = { tl: [0, 0], tr: [SIZE, 0], bl: [0, SIZE], br: [SIZE, SIZE] }

const cache = new Map()

function withAlpha(hex, alpha) {
  const n = parseInt(hex.slice(1), 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`
}

function draw(color) {
  const look = LOOKS[color]
  const canvas = document.createElement('canvas')
  canvas.width = SIZE
  canvas.height = SIZE
  const ctx = canvas.getContext('2d')

  const base = ctx.createLinearGradient(0, 0, SIZE, SIZE)
  base.addColorStop(0, look.from)
  base.addColorStop(1, look.to)
  ctx.fillStyle = base
  ctx.fillRect(0, 0, SIZE, SIZE)

  for (const [corner, hex, strength] of look.glows) {
    const [x, y] = CORNERS[corner]
    const glow = ctx.createRadialGradient(x, y, 0, x, y, SIZE * 0.8)
    glow.addColorStop(0, withAlpha(hex, strength))
    glow.addColorStop(1, withAlpha(hex, 0))
    ctx.fillStyle = glow
    ctx.fillRect(0, 0, SIZE, SIZE)
  }

  // Glyph at ~40% of the tile, centred, with the icon's own stroke weight.
  const scale = (SIZE * 0.4) / 24
  ctx.save()
  ctx.translate(SIZE / 2 - 12 * scale, SIZE / 2 - 12 * scale)
  ctx.scale(scale, scale)
  ctx.strokeStyle = look.glyph
  ctx.lineWidth = 2
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  ctx.stroke(new Path2D(WAVE_PATH))
  ctx.restore()

  return canvas.toDataURL('image/png')
}

/** Data URL of the art for a noise colour ('white' | 'pink' | 'brown'). */
export function noiseArtUrl(color) {
  const c = LOOKS[color] ? color : 'brown'
  if (!cache.has(c)) cache.set(c, draw(c))
  return cache.get(c)
}
