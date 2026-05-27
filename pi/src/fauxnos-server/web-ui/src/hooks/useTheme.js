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

function apply(theme) {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  if (theme === 'light' || theme === 'dark') {
    root.setAttribute('data-theme', theme)
  } else {
    root.removeAttribute('data-theme')
  }
}

export function useTheme() {
  const [theme, setThemeState] = useState(() => {
    const t = readStored()
    apply(t)
    return t
  })
  const [effective, setEffective] = useState(() =>
    theme === 'system' ? (osDark() ? 'dark' : 'light') : theme,
  )

  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const recompute = () => {
      setEffective(theme === 'system' ? (mq.matches ? 'dark' : 'light') : theme)
    }
    recompute()
    mq.addEventListener('change', recompute)
    return () => mq.removeEventListener('change', recompute)
  }, [theme])

  const setTheme = (t) => {
    try { window.localStorage.setItem(STORAGE_KEY, t) } catch { /* ignore */ }
    apply(t)
    setThemeState(t)
  }

  return { theme, effective, setTheme }
}
