import { forwardRef } from 'react'
import { ChevronDown, ArrowDownToLine, GitBranch } from 'lucide-react'

/**
 * Page header — fauxnos wordmark on the left (sits at the same x as the
 * group cards below, indented past the drag-handle gutter), update chip
 * + devices pill on the right.
 *
 * The update chip is ONE button that does ALL the things: server self-
 * update from github, then sequential per-client update for any client
 * that lags. Per-device specifics (which SHA each device is on, last
 * update timestamp, per-device update button) live in the DevicePanel.
 * Click a device row to open it.
 */
const Header = forwardRef(function Header(
  { status, mqttConnected, onToggleDevices, popoverOpen, serverVersion, clients, onUpdateFauxnos },
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
        <UpdateChip
          serverVersion={serverVersion}
          clients={clients}
          onUpdateFauxnos={onUpdateFauxnos}
        />
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
 * One-button update affordance.
 *
 * Computes a combined "is anything stale?" signal across the server-vs-
 * github gap AND every connected client's deployed_sha-vs-server gap.
 * When stale: orange "Update fauxnos" button. When clean: small ghost
 * chip showing the server's short SHA + branch. Tooltip exposes the
 * specifics for anyone curious — the panels surface the per-device
 * detail.
 */
function UpdateChip({ serverVersion, clients, onUpdateFauxnos }) {
  if (!serverVersion) return null

  const { short_sha, dirty, behind, ahead, fetch_failed } = serverVersion
  const serverNeedsUpdate = behind > 0
  // A client needs an update if it's connected AND either (a) never
  // deployed via the pipeline (deployed_sha === null), or (b) behind
  // the server. fauxnos000 is excluded — it updates via the server
  // self-update leg, not via SSH-to-self.
  const clientsNeedingUpdate = (clients || []).filter(c => {
    if (c.client_id === 'fauxnos000') return false
    if (!c.connected) return false
    const d = c.deploy
    if (!d) return false
    return d.deployed_sha === null || (d.behind_server !== null && d.behind_server > 0)
  })
  // Even if no client is behind THIS server, if the server itself is
  // behind origin/main, those clients will be behind after the server
  // updates. We surface them in the count so the user sees the full
  // scope of what "Update fauxnos" will do.
  const willBeBehindAfterServerUpdate = serverNeedsUpdate
    ? (clients || []).filter(c => c.client_id !== 'fauxnos000' && c.connected).length
    : 0
  const clientsToUpdate = Math.max(clientsNeedingUpdate.length, willBeBehindAfterServerUpdate)
  const totalNeedsUpdate = serverNeedsUpdate || clientsNeedingUpdate.length > 0
  const force = dirty && serverNeedsUpdate

  const tooltip = buildTooltip(serverVersion, clientsNeedingUpdate, clientsToUpdate, force)

  if (totalNeedsUpdate) {
    const totalUnits = (serverNeedsUpdate ? 1 : 0) + clientsToUpdate
    return (
      <button
        type="button"
        className={`fx-btn sm fx-header-version-pill update${force ? ' warn' : ''}`}
        onClick={() => onUpdateFauxnos({ force })}
        title={tooltip}
      >
        <ArrowDownToLine size={13} />
        <span>{force ? 'Force update fauxnos' : 'Update fauxnos'}</span>
        {totalUnits > 0 && <span className={`fx-badge sm${force ? ' warn' : ''}`}>{totalUnits}</span>}
      </button>
    )
  }

  return (
    <span
      className={`fx-header-version-pill ghost${dirty ? ' dirty' : ''}${fetch_failed ? ' offline' : ''}`}
      title={tooltip}
    >
      <GitBranch size={12} />
      <span className="fx-mono">{short_sha}</span>
      {dirty && <span className="fx-badge sm">dirty</span>}
      {!dirty && ahead > 0 && <span className="fx-badge sm">+{ahead}</span>}
    </span>
  )
}

function buildTooltip(v, clientsNeedingUpdate, clientsToUpdate, force) {
  const lines = []
  if (v.fetch_failed) lines.push('(github unreachable — counts may be stale)')
  lines.push(`Server: ${v.short_sha} on ${v.branch}`)
  if (v.dirty) lines.push('Working tree: dirty (local changes)')
  if (v.behind > 0) lines.push(`Server is ${v.behind} commit${v.behind !== 1 ? 's' : ''} behind origin/main`)
  else if (v.ahead > 0) lines.push(`Server is ${v.ahead} commit${v.ahead !== 1 ? 's' : ''} ahead of origin/main`)
  else lines.push('Server is up to date with origin/main')
  if (clientsToUpdate > 0) {
    lines.push(`${clientsToUpdate} client${clientsToUpdate !== 1 ? 's' : ''} will be updated`)
  }
  if (force) {
    lines.push('Click will force-update (discards local changes on server)')
  }
  return lines.join('\n')
}

export default Header
