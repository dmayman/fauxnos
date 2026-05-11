import { forwardRef } from 'react'
import { ChevronDown } from 'lucide-react'

/**
 * Page header — fauxnos wordmark on the left (sits at the same x as the
 * group cards below, indented past the drag-handle gutter), devices pill
 * on the right. The pill is the entrypoint for the Devices popover; its
 * ref is forwarded so App can wire outside-click detection without
 * bouncing close→open on the same click.
 */
const Header = forwardRef(function Header({ status, mqttConnected, onToggleDevices, popoverOpen }, ref) {
  const ok = status?.status === 'running'
  const label = ok
    ? `${status.total_clients} device${status.total_clients !== 1 ? 's' : ''}`
    : 'offline'

  return (
    <header className="fx-header">
      <h1 className="fx-header-wordmark">fauxnos</h1>
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
