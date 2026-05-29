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
                volumes[deviceId] = v
            }
        case "mode":
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

    /// Live volume for a client: MQTT overlay wins, else the REST snapshot value.
    func volume(for client: SnapClient) -> Int {
        volumes[client.id] ?? client.config.volume.percent
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
}
