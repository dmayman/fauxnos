import { useEffect, useState } from 'react'

/* Light/dark theme controller.
 *
 * - Reads/writes `data-theme` on `<html>` so the same attribute the CSS
 *   tokens key off of is the source of truth.
 * - Persists the user's explicit choice to localStorage as `system|light|dark`.
 *   `system` means "follow OS preference"; switching to it removes the
 *   attribute and lets the existing `@media (prefers-color-scheme)` rules
 *   take over.
 * - Returns { theme, effective, setTheme } so the UI can show the user's
 *   pick (theme) while still reacting to the resolved mode (effective).
 *
 * Backed by a SHARED module-level store (same pattern as useTuning/useTokens).
 * This matters: `--fx-*` tokens flip via the `data-theme` attribute on <html>,
 * but the per-card `--art-*` tokens are computed in JS from `effective` and
 * written as inline style. With per-component useState, toggling the theme
 * only updated the toggling component's `effective`, leaving every GroupCard's
 * art tokens stale. A single store means one setTheme re-renders every
 * consumer, so the art tokens recompute too.
 */

const STORAGE_KEY = 'fauxnos.theme'

function readStored() {
  if (typeof window === 'undefined') return 'system'
  const v = window.localStorage.getItem(STORAGE_KEY)
  return v === 'light' || v === 'dark' || v === 'system' ? v : 'system'
}

function osDark() {
  if (typeof window === 'undefined') return true
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

function applyAttr(theme) {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  if (theme === 'light' || theme === 'dark') {
    root.setAttribute('data-theme', theme)
  } else {
    root.removeAttribute('data-theme')
  }
}

function resolve(theme) {
  return theme === 'system' ? (osDark() ? 'dark' : 'light') : theme
}

let theme = readStored()
let effective = resolve(theme)
const listeners = new Set()

applyAttr(theme)

function notify() {
  listeners.forEach((l) => l())
}

export function setTheme(t) {
  theme = t
  effective = resolve(t)
  try { window.localStorage.setItem(STORAGE_KEY, t) } catch { /* ignore */ }
  applyAttr(t)
  notify()
}

// OS preference flips only matter while following the system theme.
if (typeof window !== 'undefined') {
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (theme !== 'system') return
    effective = resolve(theme)
    notify()
  })
}

export function useTheme() {
  const [, forceRender] = useState(0)
  useEffect(() => {
    const l = () => forceRender((n) => n + 1)
    listeners.add(l)
    return () => { listeners.delete(l) }
  }, [])
  return { theme, effective, setTheme }
}
