/* ─────────────────────────────────────────────────────────────────────────────
 * Album-art token builder.
 *
 * Given a raw OKLCH source color { h, c, l } (from useAlbumArtColor or the
 * TuningPanel scaffold's manual H/C/L sliders), the active mode, and the
 * live tuning clamp values, return the `--art-*` CSS variables ready to
 * write as inline style on a `.fx-group-card-v2`.
 *
 * Extracted from GroupCard so the TuningPanel's preview can reuse the
 * exact same math.
 * ────────────────────────────────────────────────────────────────────────── */

const clamp = (lo, v, hi) => Math.max(lo, Math.min(hi, v))

/* Card fills are translucent so the blurred album-art backdrop reads through
   them (see ArtBackdrop). Alphas are iOS's baked media.opacity /
   device.opacity — light mode leaves the device sub-card opaque. */
const CARD_ALPHA = { dark: 0.40, light: 0.66 }
const ROWS_ALPHA_DARK = 0.29

export function buildArtTokens({ h, c, l }, isDark, t) {
  if (isDark) {
    const accentL = clamp(t.accentLmin_dark, l, t.accentLmax_dark)
    const accentC = clamp(t.accentCmin,      c, t.accentCmax)
    const tintC   = clamp(t.cardTintCmin_dark, c, t.cardTintCmax_dark)
    return {
      '--art-accent':            `oklch(${accentL} ${accentC} ${h})`,
      '--art-accent-soft':       `oklch(${accentL} ${accentC} ${h} / 0.18)`,
      '--art-card-tint':         `oklch(${t.cardTintL_dark} ${tintC} ${h} / ${CARD_ALPHA.dark})`,
      // Inner rows sub-card: same tone as the tint, darker — dark mode only.
      // Light mode omits this so the inner surface stays --fx-surface-1.
      '--art-inner-surface':     `oklch(${t.innerSurfaceL_dark} ${tintC} ${h} / ${ROWS_ALPHA_DARK})`,
      '--art-slider-fill':       `oklch(${accentL} ${accentC} ${h})`,
      '--art-slider-track-tint': `oklch(${accentL} ${accentC} ${h} / ${t.trackAlpha_dark})`,
      '--art-progress-tint':     `oklch(${accentL} ${accentC} ${h} / ${t.trackAlpha_dark})`,
    }
  }
  const accentL = clamp(t.accentLmin_light, l, t.accentLmax_light)
  const accentC = clamp(t.accentCmin,       c, t.accentCmax)
  const tintC   = clamp(t.cardTintCmin_light, c, t.cardTintCmax_light)
  return {
    '--art-accent':            `oklch(${accentL} ${accentC} ${h})`,
    '--art-accent-soft':       `oklch(${accentL} ${accentC} ${h} / 0.10)`,
    '--art-card-tint':         `oklch(${t.cardTintL_light} ${tintC} ${h} / ${CARD_ALPHA.light})`,
    '--art-slider-fill':       `oklch(${accentL} ${accentC} ${h})`,
    '--art-slider-track-tint': `oklch(${accentL} ${accentC} ${h} / ${t.trackAlpha_light})`,
    '--art-progress-tint':     `oklch(${accentL} ${accentC} ${h} / ${t.trackAlpha_light})`,
  }
}
