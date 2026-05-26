import { forwardRef } from 'react'
import { ChevronDown, ArrowDownToLine, GitBranch } from 'lucide-react'
import { IconSun, IconMoon, IconDeviceDesktop } from '@tabler/icons-react'
import { useTheme } from '../hooks/useTheme'

/**
 * Page header — fauxnos wordmark on the left, two update pills + devices
 * pill on the right.
 *
 * Phase F1 (2026-05-13): server and client updates are independent
 * concerns. Two pills surface them separately, each visible only when
 * that component is actually behind:
 *
 *   "Update server"      → /api/server/update (git pull + restart
 *                          fauxnos-server). Visible when server_path_behind
 *                          > 0. Force variant when the working tree is
 *                          dirty (discards local changes).
 *   "Update clients (N)" → per-client install.sh runs. Visible when any
 *                          connected client's commits_behind > 0 (path-
 *                          filtered to pi/src/fauxnos-client/). Clicking
 *                          implicitly does a server git pull first when
 *                          there's anything to pull — clients install.sh-
 *                          download files from fauxnos000's checkout, so
 *                          the pull needs to land on disk before they run.
 *
 * Per-device detail (which SHA each device is at, last-update timestamp,
 * per-device update button) lives in DevicePanel.
 */
const Header = forwardRef(function Header(
  { status, mqttConnected, onToggleDevices, popoverOpen, serverVersion, clients, onUpdateServer, onUpdateClients },
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
        <ThemeToggle />
        <UpdatePills
          serverVersion={serverVersion}
          clients={clients}
          onUpdateServer={onUpdateServer}
          onUpdateClients={onUpdateClients}
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
 * Two independent pills + a fallback ghost chip.
 *
 *   Server pill visible: server_path_behind > 0 (server-subtree commits
 *                        unmerged into the running fauxnos-server)
 *   Client pill visible: any connected client with commits_behind > 0 or
 *                        never-deployed
 *
 * If neither is set: render the small ghost SHA chip (existing behavior
 * when everything is up to date).
 */
function UpdatePills({ serverVersion, clients, onUpdateServer, onUpdateClients }) {
  if (!serverVersion) return null

  const {
    short_sha, dirty, behind, ahead, fetch_failed,
    server_path_behind,
    server_path_tip,
    server_deployed_sha,
  } = serverVersion

  // Server-side drift signal. server_path_behind is the authoritative
  // count (commits touching pi/src/fauxnos-server/ between
  // server_deployed_sha and server_path_tip). Fallback to the whole-repo
  // `behind` if the per-component signal isn't available yet (e.g. older
  // server build returning the legacy shape).
  const serverBehindCount = (server_path_behind ?? null) !== null
    ? server_path_behind
    : (behind > 0 ? behind : 0)
  const serverNeedsUpdate = serverBehindCount > 0
  const force = dirty && serverNeedsUpdate

  const clientsNeedingUpdate = (clients || []).filter(c => {
    if (!c.connected) return false
    const d = c.deploy
    if (!d) return false
    return d.deployed_client_sha === null || (d.commits_behind !== null && d.commits_behind > 0)
  })

  // When the local checkout is behind github (whole-repo `behind > 0`),
  // the client install.sh runs will download stale files unless we git
  // pull first. So if ANYTHING needs pulling, every connected client
  // becomes a candidate after the pull. Surfaced as part of the client
  // pill's count.
  const repoNeedsPull = behind > 0
  const willBeBehindAfterPull = repoNeedsPull
    ? (clients || []).filter(c => c.connected).length
    : 0
  const clientsToUpdate = Math.max(clientsNeedingUpdate.length, willBeBehindAfterPull)
  const clientsNeedUpdate = clientsToUpdate > 0

  const tooltipServer = buildServerTooltip(serverVersion, force)
  const tooltipClients = buildClientsTooltip(clientsNeedingUpdate, clientsToUpdate, repoNeedsPull)

  // All-clean state: small ghost chip showing branch + short_sha.
  if (!serverNeedsUpdate && !clientsNeedUpdate) {
    return (
      <span
        className={`fx-header-version-pill ghost${dirty ? ' dirty' : ''}${fetch_failed ? ' offline' : ''}`}
        title={tooltipServer}
      >
        <GitBranch size={12} />
        <span className="fx-mono">{short_sha}</span>
        {dirty && <span className="fx-badge sm">dirty</span>}
        {!dirty && ahead > 0 && <span className="fx-badge sm">+{ahead}</span>}
      </span>
    )
  }

  return (
    <>
      {serverNeedsUpdate && (
        <button
          type="button"
          className={`fx-btn sm fx-header-version-pill update${force ? ' warn' : ''}`}
          onClick={() => onUpdateServer({ force })}
          title={tooltipServer}
        >
          <ArrowDownToLine size={13} />
          <span>{force ? 'Force update server' : 'Update server'}</span>
          {serverBehindCount > 0 && (
            <span className={`fx-badge sm${force ? ' warn' : ''}`}>{serverBehindCount}</span>
          )}
        </button>
      )}
      {clientsNeedUpdate && (
        <button
          type="button"
          className="fx-btn sm fx-header-version-pill update"
          onClick={() => onUpdateClients()}
          title={tooltipClients}
        >
          <ArrowDownToLine size={13} />
          <span>
            Update {clientsToUpdate === 1 ? 'client' : 'clients'}
          </span>
          <span className="fx-badge sm">{clientsToUpdate}</span>
        </button>
      )}
    </>
  )
}

function buildServerTooltip(v, force) {
  const lines = []
  if (v.fetch_failed) lines.push('(github unreachable — counts may be stale)')
  lines.push(`Server: ${v.short_sha} on ${v.branch}`)
  if (v.dirty) lines.push('Working tree: dirty (local changes)')
  const sBehind = v.server_path_behind
  if (sBehind !== null && sBehind !== undefined && sBehind > 0) {
    lines.push(`${sBehind} server-side commit${sBehind !== 1 ? 's' : ''} not yet running`)
  } else if (v.behind > 0) {
    // Fallback messaging when the per-component field isn't populated.
    lines.push(`${v.behind} commit${v.behind !== 1 ? 's' : ''} behind origin/main`)
  } else if (v.ahead > 0) {
    lines.push(`Server is ${v.ahead} commit${v.ahead !== 1 ? 's' : ''} ahead of origin/main`)
  } else {
    lines.push('Server is up to date with origin/main')
  }
  if (force) {
    lines.push('Click will force-update (discards local changes on server)')
  }
  return lines.join('\n')
}

function buildClientsTooltip(clientsNeedingUpdate, total, repoNeedsPull) {
  const lines = []
  if (total === 0) return ''
  const names = clientsNeedingUpdate.map(c => c.name || c.client_id).join(', ')
  if (names) lines.push(`Behind: ${names}`)
  if (repoNeedsPull && clientsNeedingUpdate.length < total) {
    lines.push('(server will pull from github first so clients get fresh files)')
  }
  return lines.join('\n')
}

/* Three-state segmented toggle: system / light / dark. Sits in the header
   next to the devices pill. Persists via useTheme. */
function ThemeToggle() {
  const { theme, setTheme } = useTheme()
  const options = [
    { id: 'light',  Icon: IconSun,           label: 'Light' },
    { id: 'system', Icon: IconDeviceDesktop, label: 'Follow system' },
    { id: 'dark',   Icon: IconMoon,          label: 'Dark' },
  ]
  return (
    <div className="fx-theme-toggle" role="radiogroup" aria-label="Theme">
      {options.map(o => (
        <button
          key={o.id}
          type="button"
          role="radio"
          aria-checked={theme === o.id}
          className={theme === o.id ? 'active' : ''}
          title={o.label}
          aria-label={o.label}
          onClick={() => setTheme(o.id)}
        >
          <o.Icon size={14} stroke={2} />
        </button>
      ))}
    </div>
  )
}

export default Header
