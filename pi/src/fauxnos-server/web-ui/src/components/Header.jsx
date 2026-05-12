import { forwardRef } from 'react'
import { ChevronDown, ArrowDownToLine, GitBranch } from 'lucide-react'

/**
 * Page header — fauxnos wordmark on the left (sits at the same x as the
 * group cards below, indented past the drag-handle gutter), version chip
 * + devices pill on the right. The devices pill is the entrypoint for the
 * Devices popover; its ref is forwarded so App can wire outside-click
 * detection without bouncing close→open on the same click.
 *
 * The version chip sits left of the devices pill. It shows the server's
 * short SHA and, when origin/main is ahead, becomes an "Update server"
 * action button. Hidden entirely when serverVersion is null (loading).
 */
const Header = forwardRef(function Header(
  { status, mqttConnected, onToggleDevices, popoverOpen, serverVersion, onUpdateServer },
  ref,
) {
  const ok = status?.status === 'running'
  const label = ok
    ? `${status.total_clients} device${status.total_clients !== 1 ? 's' : ''}`
    : 'offline'

  return (
    <header className="fx-header">
      <h1 className="fx-header-wordmark">fauxnos</h1>
      <div className="fx-row" style={{ gap: 'var(--fx-2)', alignItems: 'center' }}>
        <VersionChip serverVersion={serverVersion} onUpdateServer={onUpdateServer} />
        <button
          ref={ref}
          type="button"
          className={`fx-btn ghost sm fx-header-pill${popoverOpen ? ' active' : ''}`}
          onClick={onToggleDevices}
          title="Show devices"
          aria-haspopup="menu"
          aria-expanded={popoverOpen}
        >
          <span className={`fx-dot ${ok ? 'ok' : 'err'}`} />
          <span>{label}</span>
          <ChevronDown size={14} aria-hidden />
        </button>
      </div>
    </header>
  )
})

/**
 * Version state pill — shows the server's deployed git SHA, with action
 * affordance when an update is available.
 *
 * Visual states (matches the design language we use elsewhere):
 *   up-to-date / clean  → ghost button, just shows short SHA
 *   behind > 0          → primary "Update" button, "N behind" badge
 *   dirty (no force)    → ghost with warn-dot, tooltip explains why no button
 *   ahead-only          → ghost, neutral
 *   fetch failed        → ghost with err-dot, tooltip "(offline)"
 *
 * Click only fires `onUpdateServer` when `behind > 0` and not dirty; the
 * dirty case requires explicit force=true which we surface as a tooltip
 * for now (could become a confirm dialog later if needed).
 */
function VersionChip({ serverVersion, onUpdateServer }) {
  if (!serverVersion) return null

  const { short_sha, dirty, behind, ahead, fetch_failed } = serverVersion
  const offline = fetch_failed
  // Three buttonized cases:
  //   clean + behind     → "Update server" (plain pull)
  //   dirty + behind     → "Force update"  (reset --hard + clean, for dev
  //                       iteration cleanup)
  //   ahead-without-behind, fetch-failed, or zero drift → ghost chip, no
  //                       button (tooltip explains why)
  const tooltip = buildVersionTooltip(serverVersion)

  if (behind > 0 && !dirty) {
    return (
      <button
        type="button"
        className="fx-btn sm fx-header-version-pill update"
        onClick={() => onUpdateServer({ force: false })}
        title={tooltip}
      >
        <ArrowDownToLine size={13} />
        <span>Update server</span>
        <span className="fx-badge sm">{behind}</span>
      </button>
    )
  }

  if (behind > 0 && dirty && ahead === 0) {
    // The dev-iteration cleanup case: we rsync'd locally, then committed
    // + pushed, so the working tree has changes that ARE on origin/main
    // anyway. force=true does reset --hard + clean to converge.
    return (
      <button
        type="button"
        className="fx-btn sm fx-header-version-pill update warn"
        onClick={() => onUpdateServer({ force: true })}
        title={`${tooltip}\n\nClicking will discard local working-tree changes (force=true).`}
      >
        <ArrowDownToLine size={13} />
        <span>Force update</span>
        <span className="fx-badge sm warn">{behind}</span>
      </button>
    )
  }

  return (
    <span
      className={`fx-header-version-pill ghost${dirty ? ' dirty' : ''}${offline ? ' offline' : ''}`}
      title={tooltip}
    >
      <GitBranch size={12} />
      <span className="fx-mono">{short_sha}</span>
      {dirty && <span className="fx-badge sm">dirty</span>}
      {!dirty && ahead > 0 && <span className="fx-badge sm">+{ahead}</span>}
    </span>
  )
}

function buildVersionTooltip(v) {
  const parts = [`Server at ${v.short_sha} on ${v.branch}`]
  if (v.fetch_failed) parts.push('(could not reach github)')
  if (v.dirty) parts.push('working tree has local changes — use force update via API')
  else if (v.behind > 0) parts.push(`${v.behind} commit${v.behind !== 1 ? 's' : ''} behind origin/main — click to update`)
  else if (v.ahead > 0) parts.push(`${v.ahead} local commit${v.ahead !== 1 ? 's' : ''} not on origin`)
  else parts.push('up to date with origin/main')
  return parts.join('\n')
}

export default Header
