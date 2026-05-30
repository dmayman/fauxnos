/* ─────────────────────────────────────────────────────────────────────────────
 * GroupsSkeleton — the loading state for the groups list.
 *
 * Shown until the first /api/groups response lands, so the genuine "no
 * devices" empty state never flashes during the load window (FX-27).
 *
 * Visual: a column of placeholder cards that share the device card's outer
 * shape (full width, 36px radius, idle single-card height) but carry no
 * stroke or shadow — exactly the drop-placeholder treatment
 * (.is-drag-placeholder). Each card runs a shimmer sweep; the sweep is
 * staggered card-to-card so the animation visibly cascades down the page.
 * Cards also step down in opacity, fading toward 0 by the last one, so the
 * list reads as "continuing off the page" rather than a hard-edged stack.
 * ────────────────────────────────────────────────────────────────────────── */

// Render enough rows that opacity reaches 0 on the last one — leaving ~5
// perceptibly-visible cards above the fade-out (per the FX-27 spec).
const SKELETON_COUNT = 6

export default function GroupsSkeleton() {
  return (
    <div className="fx-groups-grid fx-skeleton-grid" aria-hidden="true">
      {Array.from({ length: SKELETON_COUNT }, (_, i) => (
        <div
          key={i}
          className="fx-skeleton-card"
          style={{
            // Linear fade: card 0 fully opaque, last card at 0.
            opacity: 1 - i / (SKELETON_COUNT - 1),
            // Stagger the shimmer so it ripples top-to-bottom.
            animationDelay: `${i * 140}ms`,
          }}
        />
      ))}
    </div>
  )
}
