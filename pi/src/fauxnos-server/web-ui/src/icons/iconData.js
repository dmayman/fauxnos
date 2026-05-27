// Eager-load every Tabler SVG (outline + filled) as a raw string. The
// icon `name` is `${style}:${base}` (e.g. "outline:home", "filled:disc")
// so the two styles never collide and the same base name can appear in
// both forms in the picker.
//
// This module is heavy (~6,100 SVGs, ~2.5 MB raw). Always import it
// lazily (React.lazy or dynamic import) so it stays out of the main bundle.

const outlineModules = import.meta.glob(
  '/node_modules/@tabler/icons/icons/outline/*.svg',
  { eager: true, query: '?raw', import: 'default' }
)
const filledModules = import.meta.glob(
  '/node_modules/@tabler/icons/icons/filled/*.svg',
  { eager: true, query: '?raw', import: 'default' }
)

const ICON_MAP = new Map()
const ICON_LIST = []

function addIcons(modules, style) {
  for (const [path, svg] of Object.entries(modules)) {
    const m = path.match(/\/([^/]+)\.svg$/)
    if (!m) continue
    const base = m[1]
    const name = `${style}:${base}`
    const tokens = base.split('-').filter(Boolean)
    const entry = {
      name,           // canonical id (e.g. "outline:home" or "filled:disc")
      style,          // "outline" | "filled"
      base,           // bare kebab name
      svg,            // raw SVG string
      search: base + ' ' + tokens.join(' ') + ' ' + style,
    }
    ICON_MAP.set(name, entry)
    ICON_LIST.push(entry)
  }
}

addIcons(outlineModules, 'outline')
addIcons(filledModules, 'filled')

// Sort by base name; within a base, filled before outline (so picking
// the filled variant when both exist is visually adjacent).
ICON_LIST.sort((a, b) => {
  const byBase = a.base.localeCompare(b.base)
  if (byBase !== 0) return byBase
  return a.style === b.style ? 0 : (a.style === 'filled' ? -1 : 1)
})

export { ICON_LIST }
export function getIconSvg(name) {
  if (!name) return null
  if (ICON_MAP.has(name)) return ICON_MAP.get(name).svg
  // Back-compat: legacy values stored without a style prefix default to outline.
  if (!name.includes(':')) {
    const e = ICON_MAP.get(`outline:${name}`) || ICON_MAP.get(`filled:${name}`)
    return e?.svg || null
  }
  return null
}
