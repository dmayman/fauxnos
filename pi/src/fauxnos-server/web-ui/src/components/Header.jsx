export default function Header({ status, mqttConnected }) {
  const statusClass = status?.status === 'running' ? 'ok' : 'error'
  const label = status?.status === 'running'
    ? `running · ${status.total_clients} device${status.total_clients !== 1 ? 's' : ''}`
    : 'offline'

  return (
    <header>
      <span className="wordmark">fauxnos</span>
      <span className="server-status">
        <span className={`status-dot ${statusClass}`} />
        <span>{label}</span>
      </span>
    </header>
  )
}
