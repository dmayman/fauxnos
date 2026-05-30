//
//  Models.swift
//  Fauxnos
//
//  Typed Swift mirrors of the Fauxnos server's wire formats. Shapes were
//  captured from the live server (`GET /api/groups`, `GET /api/status`) and
//  the MQTT payloads the web `useMqtt` hook consumes, so the iOS client is a
//  parallel reader of the exact same contract — not a new protocol.
//
//  All of these decode with `JSONDecoder.keyDecodingStrategy = .convertFromSnakeCase`
//  (see APIClient / FauxnosStore), so `stream_id` → `streamId`, `home_client_id`
//  → `homeClientId`, `art_url` → `artUrl`, and so on. Optional-heavy by design:
//  the server omits fields (group `name` is often "", `sources` is empty when
//  the home device is offline), and a foundation client should degrade rather
//  than fail to decode.
//

import Foundation

// MARK: - REST: GET /api/groups

struct GroupsResponse: Decodable {
    let groups: [SpeakerGroup]
    let streams: [StreamInfo]
}

/// One snapcast group, enriched server-side with `homeClientId`, `sources`,
/// and `availableStreams`. The server already filters offline clients and
/// drops empty groups, so every group here has at least one connected client.
struct SpeakerGroup: Decodable, Identifiable {
    let id: String
    let name: String?
    let streamId: String?
    let muted: Bool?
    let homeClientId: String?
    let clients: [SnapClient]
    let sources: [Source]?
    let availableStreams: [StreamInfo]?
}

extension SpeakerGroup {
    /// Rebuild this group with a different member list — used for optimistic
    /// join/return-home moves (the struct is otherwise immutable). Mirrors the
    /// web's functional `{ ...g, clients }` group remapping.
    func replacingClients(_ clients: [SnapClient]) -> SpeakerGroup {
        SpeakerGroup(id: id, name: name, streamId: streamId, muted: muted,
                     homeClientId: homeClientId, clients: clients,
                     sources: sources, availableStreams: availableStreams)
    }
}

struct StreamInfo: Decodable, Identifiable {
    let id: String
    let status: String
}

struct SnapClient: Decodable, Identifiable {
    let id: String
    let connected: Bool
    let host: SnapHost
    let config: SnapClientConfig
}

struct SnapHost: Decodable {
    let name: String
    let ip: String?
    let mac: String?
}

struct SnapClientConfig: Decodable {
    let volume: SnapVolume
}

struct SnapVolume: Decodable {
    let percent: Int
    let muted: Bool
}

/// A selectable source on a device. M1 only renders `id`/`label`; the rest of
/// the source schema (sink, external_switch, control_api, …) is intentionally
/// not modelled until a control milestone needs it.
struct Source: Decodable, Identifiable {
    let id: String
    let label: String?
    let type: String?
}

// MARK: - REST: GET /api/clients

/// One entry from `GET /api/clients` — the server's registry of known devices,
/// carrying the friendly display `name` ("Living Room") keyed by `client_id`.
/// The endpoint returns many more fields (deploy, dac_overlay, external volume…)
/// that we don't model yet; Decodable ignores them.
struct ClientsResponse: Decodable {
    let clients: [ClientInfo]
}

struct ClientInfo: Decodable {
    let clientId: String
    let name: String?
}

// MARK: - REST: GET /api/status

struct ServerStatus: Decodable {
    let status: String
    let testMode: Bool?
    let totalClients: Int?
    let serverVersion: String?
}

// MARK: - MQTT payloads (status/clients/<id>/track and /playback)

/// Published (retained) by the server's PlaybackManager on `status/clients/<id>/track`.
/// A retained *empty* payload means the session went inactive — handled in the
/// store by clearing the entry rather than decoding.
struct Track: Decodable {
    let source: String?
    let title: String?
    let artist: String?
    let album: String?
    let artUrl: String?
    let durationMs: Int?
    let uri: String?

    /// Whether there's enough metadata to render a "now playing" row, matching
    /// the web hook's `hasTrackMeta` check (title or artist present).
    var hasMeta: Bool { (title?.isEmpty == false) || (artist?.isEmpty == false) }
}

/// Published (retained) on `status/clients/<id>/playback`.
struct Playback: Decodable {
    let isPlaying: Bool?
    let positionMs: Int?
    let updatedAt: Double?
}

/// Payload of `status/clients/<id>/hello`. We only care about the calibration
/// snapshot it may carry; everything else is ignored for M1.
struct Hello: Decodable {
    let paCalibrations: [String: Int]?
}
