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

/* SHOW_BRANCH_INDICATOR gates a tiny label in the bottom-left footer
 * showing the git branch of the *local checkout that built/served this
 * UI* — i.e. the worktree you're developing in. With concurrent dev
 * sessions living in separate worktrees (../fauxnos-worktrees/<branch>),
 * it makes obvious which checkout produced the page you're looking at.
 * (It is NOT the backend's branch: in `npm run dev` the /api proxy points
 * at the remote server, which always runs main — that mismatch is exactly
 * what made a server-sourced label unhelpful here.)
 *
 * Tied to `import.meta.env.DEV` on purpose: this is a LOCAL-DEV-ONLY
 * affordance. Vite sets DEV=true under `npm run dev` and false for
 * `npm run build` — so the production bundle (the only thing that ever
 * ships to the remote device, which only ever runs main) never includes
 * it, with no boolean to remember to flip back. Unlike SHOW_COLOR_TUNING
 * (a manual toggle for an occasional task), this wants to be on for all
 * local dev and off everywhere else — which is exactly what DEV means.
 *
 * Source: import.meta.env.VITE_GIT_BRANCH, injected at vite config-eval
 * time (see vite.config.js `define`). No backend involvement. Gated where
 * rendered:
 *   - App.jsx (the .fx-branch-indicator footer span)
 */
export const SHOW_BRANCH_INDICATOR = import.meta.env.DEV
