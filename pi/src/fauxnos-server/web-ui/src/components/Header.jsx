import { forwardRef } from 'react'
import { ChevronDown } from 'lucide-react'

/**
 * Header with clickable status indicator.
 *
 * Floating, backdrop-blurred bar. The wordmark carries a pulsing amber
 * dot whenever the server is running — the brand cue that doubles as
 * the heartbeat. The status pill is the entrypoint for the Devices
 * popover (which replaces the old top-level Devices tab); anchorRef is
 * forwarded out so App can wire it into outside-click detection
 * without bouncing close→open on the same click.
 */
const Header = forwardRef(function Header({ status, mqttConnected, onToggleDevices, popoverOpen }, ref) {
  const ok = status?.status === 'running'
  const label = ok
    ? `${status.total_clients} device${status.total_clients !== 1 ? 's' : ''}`
    : 'offline'

  return (
    <header className="fx-header">
      <span className="fx-header-brand">
        <span
          className={`fx-dot ${ok ? 'accent pulse' : 'err'}`}
          style={ok ? { color: 'var(--fx-accent)' } : undefined}
        />
        <span className="fx-header-wordmark">fauxnos</span>
      </span>
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
    </header>
  )
})

export default Header
