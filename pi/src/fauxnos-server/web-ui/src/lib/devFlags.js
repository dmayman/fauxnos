/* Dev-only feature flags. Not user-facing.
 *
 * SHOW_COLOR_TUNING gates the color/theme tuning kit (the floating
 * TuningPanel + the inline ScaffoldGroupCard preview). It ships OFF so the
 * tool stays out of the merged UI, but the whole kit remains in the tree —
 * flip this to `true` to bring it back when colors/tokens need re-tuning.
 *
 * Gated by this one flag:
 *   - components/TuningPanel.jsx       (the floating panel)
 *   - components/ScaffoldGroupCard.jsx (the inline preview card)
 */
export const SHOW_COLOR_TUNING = false
