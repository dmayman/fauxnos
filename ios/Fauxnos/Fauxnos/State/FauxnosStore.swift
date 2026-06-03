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
import SwiftUI   // withAnimation for optimistic group remaps (drop-to-accept)
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
    private var subscriptions: [String] {
        var topics = [
            "status/clients/+/hello",
            "status/clients/+/mode",
            "status/clients/+/volume",
            "status/clients/+/track",
            "status/clients/+/playback",
            "status/clients/+/calibration/+",
        ]
        #if DEBUG
        // FX-77 dev control bus: a Mac tuning page publishes here; never shipped.
        topics.append("dev/control/state")
        #endif
        return topics
    }

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
            // All three fire in parallel so display names land alongside the
            // group list on cold launch rather than a round-trip after it (FX-76).
            async let groupsResult = api.fetchGroups()
            async let statusResult = api.fetchStatus()
            async let clientsResult = api.fetchClients()
            let (g, s) = try await (groupsResult, statusResult)
            groups = g.groups
            status = s
            apiError = nil
            lastUpdated = Date()
            // Display names are best-effort — a failure here must not blank the
            // group list, so it's awaited outside the required groups/status set.
            if let cs = try? await clientsResult {
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
        #if DEBUG
        // FX-77 dev control bus (`dev/control/state`) — merge the Mac tuning
        // snapshot, and apply a chosen demo album to the playing card so its
        // tint tracks too (the backdrop reads `demo.art` directly regardless).
        if parts.first == "dev" {
            if parts.count >= 3, parts[1] == "control", parts[2] == "state" {
                DevControlPayload.apply(payload, to: DevControl.shared)
                if let art = DevControl.shared.s("demo.art") {
                    applyDemoCover(art,
                                   title: DevControl.shared.s("demo.title"),
                                   artist: DevControl.shared.s("demo.artist"))
                }
            }
            return
        }
        #endif
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

    /// Groups ordered for display: any actively playing media floats to the top
    /// (then media-loaded-but-paused), everything else keeps its existing order.
    /// Stable, so a routine refresh / position tick never reshuffles peers.
    var displayGroups: [SpeakerGroup] {
        groups.enumerated()
            .sorted { a, b in
                let ra = mediaRank(a.element), rb = mediaRank(b.element)
                return ra == rb ? a.offset < b.offset : ra < rb
            }
            .map(\.element)
    }

    private func mediaRank(_ g: SpeakerGroup) -> Int {
        guard track(for: g)?.hasMeta == true else { return 2 }
        return playback(for: g)?.isPlaying == true ? 0 : 1
    }

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

    /// Set one device's volume: optimistic overlay + throttled POST to the
    /// server control plane (`POST /api/clients/<id>/volume`, FX-65). The
    /// server is the single routing authority — it publishes MQTT for internal
    /// devices and fires the external API for external-volume devices (Particle,
    /// etc.), which the old direct-MQTT publish silently skipped. The resulting
    /// status echoes back over MQTT but is suppressed for `echoSuppress` so the
    /// optimistic value stays stable while dragging. Mirrors web
    /// `useMqtt.publishVolume`.
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
        // Fire-and-forget — the optimistic overlay already moved the slider;
        // the authoritative value returns over MQTT status.
        Task { [weak self] in
            try? await self?.api.setVolume(clientId, value: v)
        }
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

    /// Every source offerable for a group. Multi-room groups list them all too:
    /// picking a non-Spotify (local-per-device) source ungroups the room first
    /// (see `switchSourceUngrouping`), so the picker shows the full set with a
    /// "changing source will ungroup" caption rather than hiding the others.
    func availableSources(for group: SpeakerGroup) -> [Source] {
        group.sources ?? []
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

    /// Pick a source on a multi-device group: only Spotify plays across grouped
    /// devices, so any other (local-per-device) source first ungroups the room —
    /// every member returns to its own home — then the now-single home group is
    /// pointed at the chosen source.
    func switchSourceUngrouping(_ sourceId: String, in group: SpeakerGroup) async {
        guard let home = homeClientId(of: group) else { return }
        modes[home] = sourceId                       // optimistic; echo confirms
        for c in group.clients where c.id != home {
            await returnHome(clientId: c.id)         // each awaits its own refresh
        }
        let homeGroupId = groups.first { homeClientId(of: $0) == home }?.id ?? group.id
        do {
            try await api.setGroupSource(groupId: homeGroupId, homeClientId: home, sourceId: sourceId)
        } catch {
            apiError = (error as? APIError)?.errorDescription ?? error.localizedDescription
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
        // Animate the optimistic remap so the destination card grows a row to
        // "accept" the dropped device (and the source card shrinks) smoothly.
        withAnimation(.fxEase) {
            groups = groups.compactMap { g in
                let without = g.clients.filter { $0.id != clientId }
                if homeClientId(of: g) == targetHomeClientId {
                    return g.replacingClients(without + [moving])
                }
                return without.isEmpty ? nil : g.replacingClients(without)
            }
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

    /// The whole fleet — every connected client across all groups, de-duped and
    /// sorted by display name. Backs the device-menu membership editor, which
    /// shows all devices (web `AddDevicesPopover` `devices`), not just one group.
    var allClients: [SnapClient] {
        var seen = Set<String>()
        var out: [SnapClient] = []
        for g in groups {
            for c in g.clients where seen.insert(c.id).inserted { out.append(c) }
        }
        return out.sorted {
            displayName(for: $0).localizedCaseInsensitiveCompare(displayName(for: $1)) == .orderedAscending
        }
    }

    /// Reconcile a group's membership against a desired set of device IDs — the
    /// commit path for the device menu (web `handleAddDevices`). Diffs desired vs
    /// the home group's live members, then joins the additions and returns the
    /// removals home. The home device always stays. Reuses the tested
    /// `joinGroup` / `returnHome` (each optimistic + refreshing).
    func setGroupMembership(desiredIds: Set<String>, homeClientId home: String) async {
        var desired = desiredIds
        desired.insert(home)  // home never leaves its own group
        let currentIds = Set(groups.first { homeClientId(of: $0) == home }?.clients.map(\.id) ?? [])
        let toAdd = desired.subtracting(currentIds)
        let toRemove = currentIds.subtracting(desired)
        for id in toAdd where id != home { await joinGroup(clientId: id, targetHomeClientId: home) }
        for id in toRemove where id != home { await returnHome(clientId: id) }
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

    /// FX-77 album chooser: swap the playing group's cover art so the backdrop +
    /// card tint can be judged against any artwork without live Spotify. Same-file
    /// because `tracks` is `private(set)`. No-op when nothing is playing — the
    /// backdrop still renders the chosen URL directly (GroupsListView's `demo.art`
    /// override), so backdrop tuning works regardless; only the card tint needs a
    /// live playing card to track along. Driven from the Mac dev-control page.
    func applyDemoCover(_ urlString: String, title: String? = nil, artist: String? = nil) {
        guard let g = groups.first(where: { currentSource(of: $0) == "spotify" }),
              let home = homeClientId(of: g) else { return }
        AlbumArtColorStore.shared.ensure(urlString)
        let t = tracks[home]
        tracks[home] = Track(source: "spotify",
                             title: title ?? t?.title ?? "Now Playing",
                             artist: artist ?? t?.artist ?? "Demo Artist",
                             album: t?.album,
                             artUrl: urlString,
                             durationMs: t?.durationMs ?? 240_000,
                             uri: nil)
    }
}
#endif
