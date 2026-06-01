//
//  FauxnosStore.swift
//  Fauxnos
//
//  The single source of truth the UI binds to. It owns the REST snapshot of
//  groups plus the live MQTT-derived overlay (per-client volume / mode / track
//  / playback), keyed by client id exactly like the web `useMqtt` hook. Views
//  read `groups` for membership and the overlay dictionaries for live state.
//
//  Group *membership* changes (join/leave/source) still come from /api/groups —
//  M1 refreshes it on a timer and on demand. Live *state* (a room going
//  active/idle, a volume moved elsewhere) arrives over MQTT with no refetch.
//

import Foundation
import Combine

@MainActor
final class FauxnosStore: ObservableObject {
    // REST snapshot
    @Published private(set) var groups: [SpeakerGroup] = []
    @Published private(set) var status: ServerStatus?
    @Published private(set) var apiError: String?
    @Published private(set) var isLoading = false
    @Published private(set) var lastUpdated: Date?

    // Friendly display names from /api/clients, keyed by client id (web nameMap).
    @Published private(set) var clientNames: [String: String] = [:]

    // Connection
    @Published private(set) var mqttConnected = false

    // Live MQTT overlay, keyed by client id
    @Published private(set) var volumes: [String: Int] = [:]
    @Published private(set) var modes: [String: String] = [:]
    @Published private(set) var tracks: [String: Track] = [:]
    @Published private(set) var playback: [String: Playback] = [:]

    let config: ServerConfig
    private let api: APIClient
    private var mqtt: MQTTClient?
    private var refreshTask: Task<Void, Never>?

    // Outbound volume state (FX-18). Mirrors web `useMqtt`: optimistic write,
    // a per-client throttle so a drag sends at most every THROTTLE, and an
    // echo-suppression window so the slow inbound status echo doesn't fight
    // the optimistic value mid-drag.
    private static let echoSuppress: TimeInterval = 2.0     // ECHO_SUPPRESS_MS
    private static let throttle: UInt64 = 100_000_000       // THROTTLE_MS (ns)
    private var lastVolumePublish: [String: Date] = [:]
    private var volumeThrottleTask: [String: Task<Void, Never>] = [:]
    private var volumePending: [String: Int] = [:]

    /// Topics mirror the set the web `useMqtt` hook subscribes to. The 5-part
    /// calibration topic carries `source_id` in its tail.
    private let subscriptions = [
        "status/clients/+/hello",
        "status/clients/+/mode",
        "status/clients/+/volume",
        "status/clients/+/track",
        "status/clients/+/playback",
        "status/clients/+/calibration/+",
    ]

    private static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    init(config: ServerConfig = .load()) {
        self.config = config
        self.api = APIClient(config: config)
    }

    // MARK: - Lifecycle

    func start() {
        connectMQTT()
        Task { await refresh() }
        startAutoRefresh()
    }

    func refresh() async {
        isLoading = true
        defer { isLoading = false }
        do {
            async let groupsResult = api.fetchGroups()
            async let statusResult = api.fetchStatus()
            let (g, s) = try await (groupsResult, statusResult)
            groups = g.groups
            status = s
            apiError = nil
            lastUpdated = Date()
            // Display names are best-effort — a failure here must not blank the
            // group list, so it's fetched outside the required groups/status set.
            if let cs = try? await api.fetchClients() {
                clientNames = Dictionary(
                    uniqueKeysWithValues: cs.compactMap { c in
                        guard let n = c.name, !n.isEmpty else { return nil }
                        return (c.clientId, n)
                    }
                )
            }
        } catch {
            apiError = (error as? APIError)?.errorDescription ?? error.localizedDescription
        }
    }

    /// Light background refresh of group membership (matches the web UI's 60s
    /// auto-refresh). Live per-device state doesn't depend on this.
    private func startAutoRefresh() {
        refreshTask?.cancel()
        refreshTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 60 * 1_000_000_000)
                if Task.isCancelled { break }
                await self?.refresh()
            }
        }
    }

    // MARK: - MQTT

    private func connectMQTT() {
        let client = MQTTClient(url: config.mqttWebSocketURL, topics: subscriptions)
        client.onConnectedChange = { [weak self] connected in
            // MQTTClient guarantees main-thread delivery, so we're already on
            // the MainActor and can touch published state directly.
            MainActor.assumeIsolated { self?.mqttConnected = connected }
        }
        client.onMessage = { [weak self] topic, payload in
            MainActor.assumeIsolated { self?.handle(topic: topic, payload: payload) }
        }
        mqtt = client
        client.connect()
    }

    /// Route an inbound retained/live MQTT message into the overlay. Topic shape
    /// is `status/clients/<deviceId>/<action>[/<sourceId>]`.
    private func handle(topic: String, payload: Data) {
        let parts = topic.split(separator: "/", omittingEmptySubsequences: false).map(String.init)
        guard parts.count >= 4 else { return }
        let deviceId = parts[2]
        let action = parts[3]

        switch action {
        case "volume":
            if let v = Int(String(decoding: payload, as: UTF8.self)) {
                // Echo suppression: while a publish to this client is still
                // "fresh", our optimistic value wins and we drop the echo
                // (avoids the slider snapping back mid-drag).
                if let last = lastVolumePublish[deviceId],
                   Date().timeIntervalSince(last) < Self.echoSuppress {
                    return
                }
                volumes[deviceId] = v
            }
        case "mode":
            // A mode change = new source context; the client republishes the
            // new source's stored volume right after. Clear the suppression
            // window so that volume echo isn't dropped (mirror web).
            lastVolumePublish[deviceId] = nil
            modes[deviceId] = String(decoding: payload, as: UTF8.self)
        case "track":
            // Retained empty payload = session inactive → drop the track.
            if payload.isEmpty {
                tracks[deviceId] = nil
            } else if let track = try? Self.decoder.decode(Track.self, from: payload) {
                tracks[deviceId] = track
            }
        case "playback":
            if payload.isEmpty {
                playback[deviceId] = nil
            } else if let pb = try? Self.decoder.decode(Playback.self, from: payload) {
                playback[deviceId] = pb
            }
        case "hello":
            // Hello can carry an initial volume-ish snapshot; M1 only mines it
            // for nothing required, but decode defensively so a future field
            // (pa_calibrations) is one line away.
            _ = try? Self.decoder.decode(Hello.self, from: payload)
        default:
            break   // calibration/<source> etc. — not surfaced in M1
        }
    }

    // MARK: - Derived helpers for the view

    /// Mirror of the web's home-client resolution: explicit field, else the
    /// lone client, else parse the `source_<id>_…` stream name, else first client.
    func homeClientId(of group: SpeakerGroup) -> String? {
        if let explicit = group.homeClientId { return explicit }
        if group.clients.count == 1 { return group.clients.first?.id }
        if let sid = group.streamId,
           let match = sid.range(of: #"source_(fauxnos\d+)_"#, options: .regularExpression) {
            let token = String(sid[match])               // "source_fauxnosNNN_"
            return token.replacingOccurrences(of: "source_", with: "")
                        .replacingOccurrences(of: "_", with: "")
        }
        return group.clients.first?.id
    }

    /// Friendly display name for a client ("Living Room"), falling back to the
    /// device hostname ("fauxnos000") until /api/clients lands. Mirrors the web
    /// `nameMap[id] || host.name`.
    func displayName(for client: SnapClient) -> String {
        clientNames[client.id] ?? client.host.name
    }
    func displayName(forId id: String, fallback: String) -> String {
        clientNames[id] ?? fallback
    }

    /// Live volume for a client: MQTT overlay wins, else the REST snapshot value.
    func volume(for client: SnapClient) -> Int {
        volumes[client.id] ?? client.config.volume.percent
    }

    /// Whether a device's volume is owned outside fauxnos (AirPlay / iPhone is
    /// the authority). The web detects this via the live `airplay` mode and
    /// shows a "Volume controlled by iPhone" caption instead of a slider.
    func isExternalVolume(_ clientId: String) -> Bool {
        modes[clientId] == "airplay"
    }

    // MARK: - Volume control (FX-18)

    /// Set one device's volume: optimistic overlay + throttled QoS-0 publish to
    /// `set/clients/<id>/volume`. The resulting status echoes back over MQTT but
    /// is suppressed for `echoSuppress` so the optimistic value stays stable
    /// while dragging. Mirrors web `useMqtt.publishVolume`.
    func publishVolume(_ value: Int, clientId: String) {
        let v = max(0, min(100, value))
        volumes[clientId] = v                       // optimistic
        lastVolumePublish[clientId] = Date()        // open echo-suppress window

        // Throttle: if a window is already running, just stash the latest value
        // for the trailing-edge send.
        if volumeThrottleTask[clientId] != nil {
            volumePending[clientId] = v
            return
        }
        sendVolume(v, clientId: clientId)
        volumeThrottleTask[clientId] = Task { [weak self] in
            try? await Task.sleep(nanoseconds: Self.throttle)
            guard let self else { return }
            if let pending = self.volumePending[clientId] {
                self.sendVolume(pending, clientId: clientId)
                self.lastVolumePublish[clientId] = Date()
                self.volumePending[clientId] = nil
            }
            self.volumeThrottleTask[clientId] = nil
        }
    }

    private func sendVolume(_ v: Int, clientId: String) {
        mqtt?.publish(topic: "set/clients/\(clientId)/volume", payload: Data(String(v).utf8))
    }

    /// Current source id for a group: live mode wins, else the stream-name suffix.
    func currentSource(of group: SpeakerGroup) -> String? {
        if let home = homeClientId(of: group), let mode = modes[home] { return mode }
        guard let sid = group.streamId else { return nil }
        return sid.replacingOccurrences(of: #"^source_fauxnos\d+_"#, with: "", options: .regularExpression)
    }

    func isPlaying(_ group: SpeakerGroup) -> Bool {
        guard let home = homeClientId(of: group) else { return false }
        if tracks[home]?.hasMeta == true { return true }
        return playback[home]?.isPlaying == true
    }

    func track(for group: SpeakerGroup) -> Track? {
        guard let home = homeClientId(of: group) else { return nil }
        return tracks[home]
    }

    func playback(for group: SpeakerGroup) -> Playback? {
        guard let home = homeClientId(of: group) else { return nil }
        return playback[home]
    }

    // MARK: - Transport (FX-17)

    /// Send a transport command to a group's home device. REST-write only —
    /// the resulting playback state arrives over MQTT (`status/clients/<id>/
    /// playback`), which remains the source of truth. Errors are surfaced via
    /// `apiError`; callers can drive optimistic UI and let the MQTT echo
    /// reconcile.
    func sendPlayback(_ action: PlaybackAction, for group: SpeakerGroup) async {
        guard let home = homeClientId(of: group) else { return }
        do {
            try await api.sendPlayback(home, action)
        } catch {
            apiError = (error as? APIError)?.errorDescription ?? error.localizedDescription
        }
    }

    /// Seek a group's playback to `positionMs`. Optimistically re-bases the
    /// playback overlay (new position + fresh `updatedAt`, preserving the
    /// play/pause state) so interpolation continues smoothly from the seeked
    /// point; the MQTT echo then confirms. Mirrors web `MediaCard.onSeek`.
    func seek(_ positionMs: Int, for group: SpeakerGroup) async {
        guard let home = homeClientId(of: group) else { return }
        let wasPlaying = playback[home]?.isPlaying ?? true
        playback[home] = Playback(isPlaying: wasPlaying,
                                  positionMs: positionMs,
                                  updatedAt: Date().timeIntervalSince1970 * 1000)
        do {
            try await api.seek(home, positionMs: positionMs)
        } catch {
            apiError = (error as? APIError)?.errorDescription ?? error.localizedDescription
        }
    }

    // MARK: - Source switching (FX-19)

    /// Sources offerable for a group, mirroring the web popover: the server
    /// enriches `/api/groups` with each group's `sources`, and multi-room
    /// groups can only run Spotify (the lone snapcast-routed source) — others
    /// are local-per-device and would silence the rest of the group.
    func availableSources(for group: SpeakerGroup) -> [Source] {
        let all = group.sources ?? []
        return group.clients.count > 1 ? all.filter { $0.id == "spotify" } : all
    }

    /// Switch a group's active source via `POST /api/groups/source`. We set the
    /// `mode` overlay optimistically so the UI reflects the choice immediately;
    /// the MQTT `status/clients/<home>/mode` echo then confirms the same value,
    /// so the selection sticks rather than bouncing back (the web reversion bug).
    func switchSource(_ sourceId: String, in group: SpeakerGroup) async {
        guard let home = homeClientId(of: group) else { return }
        modes[home] = sourceId                       // optimistic; echo confirms
        do {
            try await api.setGroupSource(groupId: group.id, homeClientId: home, sourceId: sourceId)
        } catch {
            apiError = (error as? APIError)?.errorDescription ?? error.localizedDescription
            // Let the next /api/groups refresh or mode echo reconcile the
            // optimistic value if the switch was rejected (e.g. 409).
        }
    }

    // MARK: - Grouping (FX-20)

    private func findClient(_ id: String) -> SnapClient? {
        for g in groups { if let c = g.clients.first(where: { $0.id == id }) { return c } }
        return nil
    }

    /// Move a device into a target group (whose home is `targetHomeClientId`).
    /// Optimistically remaps membership — pulling the device from its current
    /// group and appending it to the target, dropping any group it leaves empty
    /// — then POSTs and refreshes to reconcile with server reality. Mirrors web
    /// `handleJoinGroup`. No-op if it's already in the target group.
    func joinGroup(clientId: String, targetHomeClientId: String) async {
        guard clientId != targetHomeClientId else { return }
        if let target = groups.first(where: { homeClientId(of: $0) == targetHomeClientId }),
           target.clients.contains(where: { $0.id == clientId }) {
            return  // already a member
        }
        guard let moving = findClient(clientId) else { return }
        groups = groups.compactMap { g in
            let without = g.clients.filter { $0.id != clientId }
            if homeClientId(of: g) == targetHomeClientId {
                return g.replacingClients(without + [moving])
            }
            return without.isEmpty ? nil : g.replacingClients(without)
        }
        do {
            try await api.joinGroup(clientId: clientId, targetClientId: targetHomeClientId)
        } catch {
            apiError = (error as? APIError)?.errorDescription ?? error.localizedDescription
        }
        await refresh()
    }

    /// Return a device to its own home group (ungroup). Optimistically pulls it
    /// from its current group into its home group, synthesizing that home group
    /// if the server had dropped it while empty. Mirrors web `handleReturnHome`.
    func returnHome(clientId: String) async {
        if let moving = findClient(clientId) {
            var foundHome = false
            var updated: [SpeakerGroup] = groups.compactMap { g in
                let without = g.clients.filter { $0.id != clientId }
                if homeClientId(of: g) == clientId {
                    foundHome = true
                    return g.replacingClients(without + [moving])
                }
                return without.isEmpty ? nil : g.replacingClients(without)
            }
            if !foundHome {
                updated.append(SpeakerGroup(
                    id: "optimistic_\(clientId)_home", name: nil,
                    streamId: "source_\(clientId)_spotify", muted: false,
                    homeClientId: clientId, clients: [moving],
                    sources: [], availableStreams: []))
            }
            groups = updated
        }
        do {
            try await api.returnHome(clientId: clientId)
        } catch {
            apiError = (error as? APIError)?.errorDescription ?? error.localizedDescription
        }
        await refresh()
    }
}

#if DEBUG
extension FauxnosStore {
    /// Build a store pre-seeded with static fixtures for Xcode Previews / the
    /// canvas — no `start()`, so no network and no MQTT connection. Lives here
    /// (not in the Preview file) because the overlay properties are
    /// `private(set)`; only same-file code may seed them. Fixtures: `PreviewData`.
    static func preview(groups: [SpeakerGroup] = PreviewData.groups,
                        connected: Bool = true) -> FauxnosStore {
        // Seed art-tint colors up front so cards theme on first render rather
        // than flashing neutral while async extraction runs (which never does
        // in previews — `ensure(_:)` no-ops on a pre-seeded URL).
        AlbumArtColorStore.shared.preloadForPreview(PreviewData.artColors)
        let store = FauxnosStore()
        store.groups = groups
        store.volumes = PreviewData.volumes
        store.modes = PreviewData.modes
        store.tracks = PreviewData.tracks
        store.playback = PreviewData.playback
        store.clientNames = PreviewData.names
        store.mqttConnected = connected
        store.lastUpdated = Date()
        return store
    }
}
#endif
