import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { X } from 'lucide-react'
import Header from './components/Header'
import GroupsTab from './components/GroupsTab'
import AddDeviceTab from './components/AddDeviceTab'
import DevicesPopover from './components/DevicesPopover'
import DevicePanel from './components/DevicePanel'
import UpdateStreamModal from './components/UpdateStreamModal'
import { useMqtt } from './hooks/useMqtt'
import { apiFetch, getServerVersion } from './api'

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
  const [serverVersion, setServerVersion] = useState(null)
  const [devicePanelClientId, setDevicePanelClientId] = useState(null)
  const [popoverOpen, setPopoverOpen] = useState(false)
  const [addDeviceOpen, setAddDeviceOpen] = useState(false)
  // Update-pipeline modal: a single modal we reuse for both server-self-
  // update and per-client update. `null` = closed; otherwise the shape
  // `{ title, icon, url, body }` parameterizes the SSE stream.
  const [updateModal, setUpdateModal] = useState(null)
  const headerStatusRef = useRef(null)

  const mqtt = useMqtt()

  const loadAll = useCallback(async () => {
    try {
      // Server version is in its own request because it includes a
      // `git fetch` round-trip (~500ms) and we don't want that to block
      // /api/clients rendering. Caught so a github outage doesn't break
      // the rest of the UI.
      const [groupsData, clientsData, statusData, versionData] = await Promise.all([
        apiFetch('/api/groups').catch(() => null),
        apiFetch('/api/clients').catch(() => null),
        apiFetch('/api/status').catch(() => null),
        getServerVersion().catch(() => null),
      ])
      if (groupsData) {
        setGroups(groupsData.groups || [])
        setStreams(groupsData.streams || [])
      }
      if (clientsData) setClients(clientsData.clients || [])
      if (statusData) setServerStatus(statusData)
      if (versionData) setServerVersion(versionData)
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

  // ── Update orchestration ───────────────────────────────────────────────
  //
  // The header's "Update fauxnos" button runs a sequence: server first
  // (if behind origin/main), then each client that's behind the server
  // (after the server pull). Each step is its own SSE stream; the modal
  // walks the queue.
  //
  // The DevicePanel's per-device "Update this device" button runs just
  // one step: that single client. Same modal, same SSE consumption logic,
  // just a one-item queue.

  const openUpdateFauxnos = useCallback((opts = {}) => {
    const { force = false } = opts
    const steps = []
    if (serverVersion?.behind > 0 || force) {
      steps.push({
        kind: 'server',
        label: force ? 'Force-update server from GitHub' : 'Update server from GitHub',
        url: '/api/server/update',
        body: force ? { force: true } : {},
        icon: 'server',
      })
    }
    // After a server update, every connected client will be behind. If
    // there's no server update needed, only target clients that are
    // already behind (or never deployed). fauxnos000 included — it's
    // a client like the others now (UpdateRunner uses local subprocess
    // for it, not SSH).
    const candidates = (clients || []).filter(c => c.connected)
    const filtered = (steps.length > 0)
      ? candidates  // server is updating → all connected clients lag after
      : candidates.filter(c => {
          const d = c.deploy
          return d && (d.deployed_client_sha === null || (d.commits_behind !== null && d.commits_behind > 0))
        })
    for (const c of filtered) {
      steps.push({
        kind: 'client',
        label: `Update ${c.name || c.client_id}`,
        url: `/api/clients/${c.client_id}/update`,
        body: {},
        icon: 'device',
        clientId: c.client_id,
        clientName: c.name || c.client_id,
      })
    }
    if (steps.length === 0) return  // nothing to do — defensive

    setUpdateModal({
      title: 'Update fauxnos',
      icon: 'server',
      steps,
      // Wait for server restart before the first client step. The SSE
      // `done` event for /api/server/update fires before the actual
      // restart, so we poll /api/server/version until it responds
      // again on a new (or same) SHA, which is the signal that flask
      // is back up. Modal handles this internally.
      waitForServerRestartAfterServerStep: true,
    })
  }, [serverVersion, clients])

  const openSingleClientUpdate = useCallback((client) => {
    const name = client?.name || client?.client_id || 'client'
    setUpdateModal({
      title: `Update ${name}`,
      icon: 'device',
      steps: [{
        kind: 'client',
        label: `Update ${name}`,
        url: `/api/clients/${client.client_id}/update`,
        body: {},
        icon: 'device',
        clientId: client.client_id,
        clientName: name,
      }],
      waitForServerRestartAfterServerStep: false,
    })
  }, [])

  const closeUpdateModal = useCallback(() => setUpdateModal(null), [])

  // When an update finishes, refresh everything so the chip + per-device
  // badges reflect the new state. Cheap enough; loadAll already runs in
  // parallel.
  const onUpdateDone = useCallback(() => { loadAll() }, [loadAll])

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
          serverVersion={serverVersion}
          clients={clients}
          onUpdateFauxnos={openUpdateFauxnos}
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
          onUpdateClient={openSingleClientUpdate}
          serverVersion={serverVersion}
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

      {updateModal && (
        <UpdateStreamModal
          open={true}
          onClose={closeUpdateModal}
          title={updateModal.title}
          steps={updateModal.steps}
          waitForServerRestartAfterServerStep={updateModal.waitForServerRestartAfterServerStep}
          onDone={onUpdateDone}
        />
      )}
    </div>
  )
}
