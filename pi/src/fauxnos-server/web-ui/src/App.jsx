import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { X } from 'lucide-react'
import Header, { UpdatePills, ThemeMenu } from './components/Header'
import LibraryPanel, { LibraryJobToasts } from './components/LibraryPanel'
import { ToastProvider } from './components/Toasts'
import { LibraryContext, useLibraryState } from './hooks/useLibrary'
import GroupsTab from './components/GroupsTab'
import AddDeviceTab from './components/AddDeviceTab'
import DevicesPopover from './components/DevicesPopover'
import DevicePanel from './components/DevicePanel'
import UpdateStreamModal from './components/UpdateStreamModal'
import ArtBackdrop from './components/ArtBackdrop'
import TuningPanel from './components/TuningPanel'
import { useMqtt } from './hooks/useMqtt'
import { apiFetch, getServerVersion } from './api'
import { backdropArtUrl } from './lib/nowPlaying'
import { SHOW_BRANCH_INDICATOR } from './lib/devFlags'

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
  // False until the first loadAll() settles. Distinguishes "haven't fetched
  // yet" (show skeleton) from "fetched, genuinely zero devices" (empty
  // state) so the empty copy never flashes during the load window (FX-27).
  // Background 60s refreshes never flip this back, so the list stays put.
  const [firstLoadDone, setFirstLoadDone] = useState(false)
  const [serverStatus, setServerStatus] = useState(null)
  const [serverVersion, setServerVersion] = useState(null)
  const [devicePanelClientId, setDevicePanelClientId] = useState(null)
  const [libraryOpen, setLibraryOpen] = useState(false)
  const library = useLibraryState()
  const [popoverOpen, setPopoverOpen] = useState(false)
  const [addDeviceOpen, setAddDeviceOpen] = useState(false)
  // Update-pipeline modal: a single modal we reuse for both server-self-
  // update and per-client update. `null` = closed; otherwise the shape
  // `{ title, icon, url, body }` parameterizes the SSE stream.
  const [updateModal, setUpdateModal] = useState(null)
  const headerStatusRef = useRef(null)

  const mqtt = useMqtt()

  // Room presence comes from MQTT, not snapcast: snapserver keeps a dead
  // client "connected" until its TCP connection times out, so a room that
  // drops off the network kept a live card. mqtt.online only has rooms that
  // publish presence; the rest keep the server's `connected`.
  const liveClients = useMemo(() => clients.map(c => (
    c.client_id in mqtt.online ? { ...c, connected: mqtt.online[c.client_id] } : c
  )), [clients, mqtt.online])
  const liveGroups = useMemo(() => groups.map(g => ({
    ...g,
    clients: (g.clients || []).filter(c => mqtt.online[c.id] !== false),
  })), [groups, mqtt.online])

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
      if (clientsData) {
        const list = clientsData.clients || []
        setClients(list)
        // Volume routing lives entirely on the server now (FX-65) —
        // publishVolume POSTs to /api/clients/<id>/volume and the server
        // decides MQTT vs external dispatch. No client-side routing map.
      }
      if (statusData) setServerStatus(statusData)
      if (versionData) setServerVersion(versionData)
    } catch { /* ignore */ }
    finally { setFirstLoadDone(true) }
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

  // Server-only update: git pull + (conditional) fauxnos-server restart.
  // Force variant when the working tree is dirty — discards local edits
  // and syncs to origin/main.
  const openUpdateServer = useCallback((opts = {}) => {
    const { force = false } = opts
    const steps = [{
      kind: 'server',
      label: force ? 'Force-update server from GitHub' : 'Update server from GitHub',
      url: '/api/server/update',
      body: force ? { force: true } : {},
      icon: 'server',
    }]
    setUpdateModal({
      title: 'Update server',
      icon: 'server',
      steps,
      waitForServerRestartAfterServerStep: true,
    })
  }, [])

  // Clients update: server git pull FIRST when there's anything new on
  // origin/main, then per-client install.sh runs. The pull-first step is
  // necessary because clients install.sh-download files from fauxnos000's
  // checkout — if we skip the pull, they'd grab stale files. fauxnos000
  // is included in the per-client list (its UpdateRunner uses a local
  // subprocess for that case).
  const openUpdateClients = useCallback(() => {
    const steps = []
    const repoBehind = (serverVersion?.behind ?? 0) > 0
    if (repoBehind) {
      steps.push({
        kind: 'server',
        label: 'Pull latest from GitHub (clients need the new files)',
        url: '/api/server/update',
        body: {},
        icon: 'server',
      })
    }
    const candidates = (liveClients || []).filter(c => c.connected)
    // When we're pulling, every connected client will lag after — include
    // all of them. Otherwise just the ones already flagged behind.
    const filtered = repoBehind
      ? candidates
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
      title: filtered.length === 1 ? `Update ${filtered[0].name || filtered[0].client_id}` : 'Update clients',
      icon: 'server',
      steps,
      waitForServerRestartAfterServerStep: repoBehind,
    })
  }, [serverVersion, liveClients])

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
    setLibraryOpen(false)
    setDevicePanelClientId(clientId)
  }, [])

  const toggleLibrary = useCallback(() => {
    setAddDeviceOpen(false)
    setDevicePanelClientId(null)
    setLibraryOpen(v => !v)
  }, [])

  const closeDevice = useCallback(() => setDevicePanelClientId(null), [])

  const openAddDevice = useCallback(() => {
    setDevicePanelClientId(null)
    setLibraryOpen(false)
    setAddDeviceOpen(true)
  }, [])

  const closeAddDevice = useCallback(() => setAddDeviceOpen(false), [])

  // Resolve the currently-open device by id so the panel re-renders with
  // fresh data after a refresh tick — pulling from state instead of a
  // captured prop means a rename or status flip shows up immediately.
  const activeDeviceClient = useMemo(
    () => liveClients.find(c => c.client_id === devicePanelClientId) || null,
    [liveClients, devicePanelClientId]
  )

  // If the panel's target device vanishes (e.g. user removed it),
  // close the panel instead of rendering a stale shell.
  useEffect(() => {
    if (devicePanelClientId && !activeDeviceClient) {
      setDevicePanelClientId(null)
    }
  }, [devicePanelClientId, activeDeviceClient])

  const sidePanelOpen = !!activeDeviceClient || addDeviceOpen || libraryOpen

  return (
    <ToastProvider>
    <LibraryContext.Provider value={library}>
    <LibraryJobToasts />
    <div className="fx-root">
      <ArtBackdrop url={backdropArtUrl(liveGroups, mqtt, library)} />
      {popoverOpen && (
        <DevicesPopover
          clients={liveClients}
          anchorRef={headerStatusRef}
          onClose={() => setPopoverOpen(false)}
          onOpenDevice={openDevice}
          onAddDevice={openAddDevice}
        />
      )}
      <Header
        ref={headerStatusRef}
        status={serverStatus}
        mqttConnected={mqtt.connected}
        popoverOpen={popoverOpen}
        onToggleDevices={() => setPopoverOpen(v => !v)}
        onToggleLibrary={toggleLibrary}
        libraryOpen={libraryOpen}
      />
      <main className="fx-main">
        <GroupsTab
          groups={liveGroups}
          clients={liveClients}
          streams={streams}
          loading={!firstLoadDone}
          mqtt={mqtt}
          onRefresh={loadAll}
          onOpenDevice={openDevice}
          onAddDevice={openAddDevice}
        />
      </main>
      <div className="fx-version-tracker">
        <ThemeMenu />
        <UpdatePills
          serverVersion={serverVersion}
          clients={liveClients}
          onUpdateServer={openUpdateServer}
          onUpdateClients={openUpdateClients}
        />
        {/* Dev-only: which local checkout (worktree) produced this UI.
            Branch is injected at build time (vite.config.js); gated by
            SHOW_BRANCH_INDICATOR so production renders nothing. */}
        {SHOW_BRANCH_INDICATOR && import.meta.env.VITE_GIT_BRANCH && (
          <span className="fx-branch-indicator" title="Local web checkout branch (dev)">
            ⎇ {import.meta.env.VITE_GIT_BRANCH}
          </span>
        )}
      </div>

      {sidePanelOpen && <div className="fx-overlay" onClick={() => {
        closeDevice()
        closeAddDevice()
        setLibraryOpen(false)
      }} />}

      {libraryOpen && (
        <LibraryPanel
          groups={groups}
          clients={clients}
          mqtt={mqtt}
          onClose={() => setLibraryOpen(false)}
        />
      )}

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

      {/* Temporary OKLCH tuning panel — delete with useTuning.js once values lock. */}
      <TuningPanel />
    </div>
    </LibraryContext.Provider>
    </ToastProvider>
  )
}
