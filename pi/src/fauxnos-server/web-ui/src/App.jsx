import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { X } from 'lucide-react'
import Header from './components/Header'
import GroupsTab from './components/GroupsTab'
import AddDeviceTab from './components/AddDeviceTab'
import DevicesPopover from './components/DevicesPopover'
import DevicePanel from './components/DevicePanel'
import { useMqtt } from './hooks/useMqtt'
import { apiFetch } from './api'

/**
 * Top-level layout.
 *
 * Tabs are gone — Groups is the only main view. Devices live in a popover
 * anchored to the header's status pill; clicking a device row opens a
 * side panel (DevicePanel) with status + sources + advanced settings.
 * The Add Device wizard now opens as a wider side panel from the popover
 * footer.
 *
 * Side panels are mutually exclusive (open one closes any other) so the
 * z-index/overlay accounting stays simple.
 */
export default function App() {
  const [clients, setClients] = useState([])
  const [groups, setGroups] = useState([])
  const [streams, setStreams] = useState([])
  const [serverStatus, setServerStatus] = useState(null)
  const [devicePanelClientId, setDevicePanelClientId] = useState(null)
  const [popoverOpen, setPopoverOpen] = useState(false)
  const [addDeviceOpen, setAddDeviceOpen] = useState(false)
  const headerStatusRef = useRef(null)

  const mqtt = useMqtt()

  const loadAll = useCallback(async () => {
    try {
      const [groupsData, clientsData, statusData] = await Promise.all([
        apiFetch('/api/groups').catch(() => null),
        apiFetch('/api/clients').catch(() => null),
        apiFetch('/api/status').catch(() => null),
      ])
      if (groupsData) {
        setGroups(groupsData.groups || [])
        setStreams(groupsData.streams || [])
      }
      if (clientsData) setClients(clientsData.clients || [])
      if (statusData) setServerStatus(statusData)
    } catch { /* ignore */ }
  }, [])

  // Initial + 60s background refresh. The popover always wants fresh
  // client state, so we fetch everything together regardless of which
  // panels are open.
  useEffect(() => { loadAll() }, [loadAll])
  useEffect(() => {
    const id = setInterval(loadAll, 60000)
    return () => clearInterval(id)
  }, [loadAll])

  const openDevice = useCallback((clientId) => {
    setAddDeviceOpen(false)
    setDevicePanelClientId(clientId)
  }, [])

  const closeDevice = useCallback(() => setDevicePanelClientId(null), [])

  const openAddDevice = useCallback(() => {
    setDevicePanelClientId(null)
    setAddDeviceOpen(true)
  }, [])

  const closeAddDevice = useCallback(() => setAddDeviceOpen(false), [])

  // Resolve the currently-open device by id so the panel re-renders with
  // fresh data after a refresh tick — pulling from state instead of a
  // captured prop means a rename or status flip shows up immediately.
  const activeDeviceClient = useMemo(
    () => clients.find(c => c.client_id === devicePanelClientId) || null,
    [clients, devicePanelClientId]
  )

  // If the panel's target device vanishes (e.g. user removed it),
  // close the panel instead of rendering a stale shell.
  useEffect(() => {
    if (devicePanelClientId && !activeDeviceClient) {
      setDevicePanelClientId(null)
    }
  }, [devicePanelClientId, activeDeviceClient])

  const sidePanelOpen = !!activeDeviceClient || addDeviceOpen

  return (
    <div className="fx-root">
      {popoverOpen && (
        <DevicesPopover
          clients={clients}
          anchorRef={headerStatusRef}
          onClose={() => setPopoverOpen(false)}
          onOpenDevice={openDevice}
          onAddDevice={openAddDevice}
        />
      )}
      <main className="fx-main">
        <Header
          ref={headerStatusRef}
          status={serverStatus}
          mqttConnected={mqtt.connected}
          popoverOpen={popoverOpen}
          onToggleDevices={() => setPopoverOpen(v => !v)}
        />
        <GroupsTab
          groups={groups}
          clients={clients}
          streams={streams}
          mqtt={mqtt}
          onRefresh={loadAll}
          onOpenDevice={openDevice}
          onAddDevice={openAddDevice}
        />
      </main>

      {sidePanelOpen && <div className="fx-overlay" onClick={() => {
        closeDevice()
        closeAddDevice()
      }} />}

      {activeDeviceClient && (
        <DevicePanel
          client={activeDeviceClient}
          mqtt={mqtt}
          onClose={closeDevice}
          onRefresh={loadAll}
        />
      )}

      {addDeviceOpen && (
        <div className="fx-side-panel wide fx-add-device-panel">
          <div className="fx-device-panel-head">
            <span className="fx-h2">Add device</span>
            <button className="fx-icon-btn" onClick={closeAddDevice} aria-label="Close">
              <X size={18} />
            </button>
          </div>
          <AddDeviceTab onDeviceAdded={loadAll} />
        </div>
      )}
    </div>
  )
}
