import { useEffect, useState } from 'react'

/* ─────────────────────────────────────────────────────────────────────────────
 * Token store — TEMPORARY.
 *
 * Companion to useTuning. Lets the user override any of the `--fx-*` color
 * tokens for either theme (dark/light) via the TuningPanel "Tokens" tab.
 * Overrides are injected into a single <style id="fx-token-overrides"> tag
 * appended to <head>, scoped to the same selectors the base tokens use so
 * the cascade order is preserved.
 *
 * Once values lock, paste the JSON back into index.css and delete this
 * hook + the Tokens tab.
 * ────────────────────────────────────────────────────────────────────────── */

// Defaults mirror :root,[data-theme="dark"] and [data-theme="light"] in
// index.css. Update both places if a token is added/renamed.
export const TOKEN_DEFAULTS = {
  dark: {
    '--fx-bg':          '#060606',
    '--fx-surface-1':   '#141414',
    '--fx-surface-2':   '#1C1C1C',
    '--fx-surface-3':   '#262626',
    '--fx-line':        'rgba(255, 255, 255, 0.06)',
    '--fx-line-strong': 'rgba(255, 255, 255, 0.12)',
    '--fx-text':        '#F2F2F2',
    '--fx-text-2':      '#A0A0A0',
    '--fx-text-3':      '#6A6A6A',
    '--fx-accent':       '#F2F2F2',
    '--fx-accent-hover': '#FFFFFF',
    '--fx-accent-soft':  'rgba(255, 255, 255, 0.08)',
    '--fx-accent-ring':  'rgba(255, 255, 255, 0.24)',
    '--fx-on-accent':    '#0A0A0A',
    '--fx-ok':           '#7BB186',
    '--fx-warn':         '#D6A85F',
    '--fx-err':          '#D4736B',
    '--fx-ok-soft':      'rgba(123, 177, 134, 0.14)',
    '--fx-warn-soft':    'rgba(214, 168, 95, 0.14)',
    '--fx-err-soft':     'rgba(212, 115, 107, 0.14)',
    '--fx-scrim':        'rgba(0, 0, 0, 0.55)',
    '--fx-shadow-1':     '0 1px 2px rgba(0, 0, 0, 0.45)',
    '--fx-shadow-2':     '0 10px 28px rgba(0, 0, 0, 0.45), 0 1px 2px rgba(0, 0, 0, 0.35)',
    '--fx-shadow-3':     '0 24px 72px rgba(0, 0, 0, 0.55), 0 2px 4px rgba(0, 0, 0, 0.4)',
  },
  light: {
    '--fx-bg':          '#F9F9F9',
    '--fx-surface-1':   '#FFFFFF',
    '--fx-surface-2':   '#F5F5F5',
    '--fx-surface-3':   '#EAEAEA',
    '--fx-line':        'rgba(0, 0, 0, 0.08)',
    '--fx-line-strong': 'rgba(0, 0, 0, 0.16)',
    '--fx-text':        '#4A4A4A',
    '--fx-text-2':      '#7A7A7A',
    '--fx-text-3':      '#A0A0A0',
    '--fx-accent':       '#1A1A1A',
    '--fx-accent-hover': '#000000',
    '--fx-accent-soft':  'rgba(0, 0, 0, 0.06)',
    '--fx-accent-ring':  'rgba(0, 0, 0, 0.18)',
    '--fx-on-accent':    '#FFFFFF',
    '--fx-ok':           '#3E7A4D',
    '--fx-warn':         '#8E6618',
    '--fx-err':          '#9E443C',
    '--fx-ok-soft':      'rgba(62, 122, 77, 0.10)',
    '--fx-warn-soft':    'rgba(142, 102, 24, 0.10)',
    '--fx-err-soft':     'rgba(158, 68, 60, 0.10)',
    '--fx-scrim':        'rgba(0, 0, 0, 0.32)',
    '--fx-shadow-1':     '0 1px 4px rgba(0, 0, 0, 0.04)',
    '--fx-shadow-2':     '0 4px 24px rgba(0, 0, 0, 0.06), 0 1px 2px rgba(0, 0, 0, 0.03)',
    '--fx-shadow-3':     '0 12px 48px rgba(0, 0, 0, 0.12), 0 2px 4px rgba(0, 0, 0, 0.04)',
  },
}

// Logical groupings, rendered as collapsible sections in the editor.
export const TOKEN_GROUPS = [
  { title: 'Surfaces', names: ['--fx-bg', '--fx-surface-1', '--fx-surface-2', '--fx-surface-3', '--fx-line', '--fx-line-strong'] },
  { title: 'Text',     names: ['--fx-text', '--fx-text-2', '--fx-text-3'] },
  { title: 'Accent',   names: ['--fx-accent', '--fx-accent-hover', '--fx-accent-soft', '--fx-accent-ring', '--fx-on-accent'] },
  { title: 'Status',   names: ['--fx-ok', '--fx-warn', '--fx-err', '--fx-ok-soft', '--fx-warn-soft', '--fx-err-soft'] },
  { title: 'Misc',     names: ['--fx-scrim'] },
  { title: 'Shadows',  names: ['--fx-shadow-1', '--fx-shadow-2', '--fx-shadow-3'] },
]

const STORAGE_KEY = 'fauxnos.tokens.v1'

// Names of every token we manage. Apply/clear walks this list to keep
// inline styles in sync with the active overrides map.
const ALL_TOKEN_NAMES = Object.keys(TOKEN_DEFAULTS.dark)

function loadInitial() {
  if (typeof window === 'undefined') return { dark: {}, light: {} }
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return { dark: {}, light: {} }
    const parsed = JSON.parse(raw)
    return {
      dark:  { ...(parsed.dark  || {}) },
      light: { ...(parsed.light || {}) },
    }
  } catch {
    return { dark: {}, light: {} }
  }
}

// Read the currently-effective theme from the DOM + OS preference. This
// is the same logic useTheme uses, but as a plain function so the
// module-level apply path doesn't need a React hook.
function getActiveMode() {
  if (typeof document === 'undefined') return 'dark'
  const attr = document.documentElement.getAttribute('data-theme')
  if (attr === 'dark' || attr === 'light') return attr
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

// Inline application: write the active mode's overrides directly onto
// `<html style="...">`. Inline beats stylesheet specificity in all
// cases — including the @media (prefers-color-scheme: light) :root:not([data-theme])
// rule in index.css that otherwise out-specified our injected <style>.
function applyOverrides(state) {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  const mode = getActiveMode()
  const active = state[mode] || {}
  for (const name of ALL_TOKEN_NAMES) {
    if (name in active) {
      root.style.setProperty(name, active[name])
    } else {
      root.style.removeProperty(name)
    }
  }
}

let state = loadInitial()
const listeners = new Set()
applyOverrides(state)

// Re-apply when the theme changes (explicit `data-theme` toggle or OS
// preference flip while in `system` mode). Without this, switching from
// dark to light leaves the inline dark-overrides stranded on root.
if (typeof window !== 'undefined') {
  const reApply = () => applyOverrides(state)
  const mo = new MutationObserver(reApply)
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', reApply)
}

export function getTokens() {
  return state
}

/** Merge a single mode's overrides. Pass value=null to clear that token. */
export function setToken(mode, name, value) {
  const next = { ...state, [mode]: { ...state[mode] } }
  if (value == null || value === '') {
    delete next[mode][name]
  } else {
    next[mode][name] = value
  }
  state = next
  try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state)) } catch { /* ignore */ }
  applyOverrides(state)
  listeners.forEach(l => l(state))
}

export function resetTokens() {
  state = { dark: {}, light: {} }
  try { window.localStorage.removeItem(STORAGE_KEY) } catch { /* ignore */ }
  applyOverrides(state)
  listeners.forEach(l => l(state))
}

/** Effective value for a given (mode, name) — override if present, else default. */
export function getTokenValue(mode, name) {
  const v = state[mode]?.[name]
  return (v == null || v === '') ? TOKEN_DEFAULTS[mode][name] : v
}

export function useTokens() {
  const [val, setVal] = useState(state)
  useEffect(() => {
    listeners.add(setVal)
    return () => { listeners.delete(setVal) }
  }, [])
  return val
}
