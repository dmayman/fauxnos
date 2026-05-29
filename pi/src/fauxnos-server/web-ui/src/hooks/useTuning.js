import { useEffect, useState } from 'react'

/* ─────────────────────────────────────────────────────────────────────────────
 * Tuning store — TEMPORARY.
 *
 * Lets the user dial in OKLCH clamp ranges for the album-art accent system
 * via a floating control panel. Once final values are settled they'll be
 * baked into `buildArtTokens` in GroupCard.jsx and this whole file
 * (+ TuningPanel.jsx) gets deleted.
 *
 * Defaults reflect the values dialed in 2026-05-25; the panel can still
 * iterate from there.
 * ────────────────────────────────────────────────────────────────────────── */

export const DEFAULT_TUNING = {
  cardTintL_dark:   0.33,
  cardTintCmin_dark: 0.005,
  cardTintCmax_dark: 0.035,
  // Inner device-rows sub-card bg (dark mode only): a darker shade of the
  // card tint, emulating a ~50% black overlay on the media bg. Light mode
  // leaves the inner surface white (--fx-surface-1), so there's no light value.
  innerSurfaceL_dark: 0.19,
  cardTintL_light:  0.95,
  cardTintCmin_light: 0,
  cardTintCmax_light: 0.025,
  accentLmin_dark: 0.77,
  accentLmax_dark: 0.85,
  accentLmin_light: 0.69,
  accentLmax_light: 0.70,
  accentCmin: 0.075,
  accentCmax: 0.11,
  trackAlpha_dark: 0.12,
  trackAlpha_light: 0.19,
  // Scaffold-card simulated source color (H/C/L). Lives here so the
  // inline scaffold in GroupsTab and the sliders in TuningPanel share
  // a single source of truth, and the scaffold survives reloads.
  scaffold_h: 28,
  scaffold_c: 0.16,
  scaffold_l: 0.58,
  // When set, the scaffold renders this real album cover and the panel
  // harvests its color into scaffold_h/c/l. null = synthetic swatch
  // mode (sliders drive the color directly).
  scaffold_art_url: null,
  scaffold_art_title: null,
  scaffold_art_subtitle: null,
}

const STORAGE_KEY = 'fauxnos.tuning.v1'

function loadInitial() {
  if (typeof window === 'undefined') return DEFAULT_TUNING
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULT_TUNING
    return { ...DEFAULT_TUNING, ...JSON.parse(raw) }
  } catch {
    return DEFAULT_TUNING
  }
}

let state = loadInitial()
const listeners = new Set()

export function getTuning() {
  return state
}

export function setTuning(updates) {
  state = { ...state, ...updates }
  try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state)) } catch { /* ignore */ }
  listeners.forEach(l => l(state))
}

export function resetTuning() {
  state = { ...DEFAULT_TUNING }
  try { window.localStorage.removeItem(STORAGE_KEY) } catch { /* ignore */ }
  listeners.forEach(l => l(state))
}

export function useTuning() {
  const [val, setVal] = useState(state)
  useEffect(() => {
    listeners.add(setVal)
    return () => { listeners.delete(setVal) }
  }, [])
  return val
}
