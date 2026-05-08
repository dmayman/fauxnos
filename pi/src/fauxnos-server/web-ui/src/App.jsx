import { useState, useEffect, useCallback } from 'react'
import Header from './components/Header'
import GroupsTab from './components/GroupsTab'
import DevicesTab from './components/DevicesTab'
import AddDeviceTab from './components/AddDeviceTab'
import SourcesPanel from './components/SourcesPanel'
import { useMqtt } from './hooks/useMqtt'
import { apiFetch } from './api'

export default function App() {
  const [activeTab, setActiveTab] = useState('groups')
  const [clients, setClients] = useState([])
  const [groups, setGroups] = useState([])
  const [streams, setStreams] = useState([])
  const [serverStatus, setServerStatus] = useState(null)
  const [sourcesPanel, setSourcesPanel] = useState({ open: false, clientId: null, clientName: null })

  const mqtt = useMqtt()

  const loadClients = useCallback(async () => {
    try {
      const data = await apiFetch('/api/clients')
      setClients(data.clients || [])
    } catch { /* ignore */ }
  }, [])

  const loadGroups = useCallback(async () => {
    try {
      const [groupsData, clientsData] = await Promise.all([
        apiFetch('/api/groups'),
        apiFetch('/api/clients'),
      ])
      setGroups(groupsData.groups || [])
      setStreams(groupsData.streams || [])
      setClients(clientsData.clients || [])
    } catch { /* ignore */ }
  }, [])

  const loadStatus = useCallback(async () => {
    try {
      const data = await apiFetch('/api/status')
      setServerStatus(data)
    } catch {
      setServerStatus(null)
    }
  }, [])

  // Initial load
  useEffect(() => {
    loadStatus()
    loadGroups()
  }, [loadStatus, loadGroups])

  // Auto-refresh every 60s
  useEffect(() => {
    const id = setInterval(() => {
      loadStatus()
      if (activeTab === 'groups') loadGroups()
      else if (activeTab === 'devices') loadClients()
    }, 60000)
    return () => clearInterval(id)
  }, [activeTab, loadStatus, loadGroups, loadClients])

  // Reload when switching tabs
  useEffect(() => {
    if (activeTab === 'groups') loadGroups()
    else if (activeTab === 'devices') loadClients()
  }, [activeTab, loadGroups, loadClients])

  const openSources = useCallback((clientId, clientName) => {
    setSourcesPanel({ open: true, clientId, clientName })
  }, [])

  const closeSources = useCallback(() => {
    setSourcesPanel({ open: false, clientId: null, clientName: null })
  }, [])

  const tabs = [
    { id: 'groups', label: 'Groups' },
    { id: 'devices', label: 'Devices' },
    { id: 'add-device', label: 'Add Device' },
  ]

  return (
    <>
      <Header status={serverStatus} mqttConnected={mqtt.connected} />
      <nav>
        {tabs.map(t => (
          <button
            key={t.id}
            className={`tab-btn${activeTab === t.id ? ' active' : ''}`}
            onClick={() => setActiveTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>
      <main>
        {activeTab === 'groups' && (
          <GroupsTab
            groups={groups}
            clients={clients}
            streams={streams}
            mqtt={mqtt}
            onRefresh={loadGroups}
            onOpenSources={openSources}
          />
        )}
        {activeTab === 'devices' && (
          <DevicesTab
            clients={clients}
            onRefresh={loadClients}
          />
        )}
        {activeTab === 'add-device' && (
          <AddDeviceTab onDeviceAdded={() => { loadClients(); loadGroups() }} />
        )}
      </main>
      {sourcesPanel.open && (
        <>
          <div className="overlay" onClick={closeSources} />
          <SourcesPanel
            clientId={sourcesPanel.clientId}
            clientName={sourcesPanel.clientName}
            mqtt={mqtt}
            onClose={closeSources}
          />
        </>
      )}
    </>
  )
}
