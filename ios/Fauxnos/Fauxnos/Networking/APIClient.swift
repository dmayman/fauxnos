//
//  APIClient.swift
//  Fauxnos
//
//  Thin async REST client. M1 needs only the two read endpoints below, but the
//  generic `get`/`post` core is here so feature milestones can add typed calls
//  without re-discovering decoding/error handling.
//

import Foundation

enum APIError: LocalizedError {
    case badURL
    case http(status: Int)
    case decoding(Error)
    case transport(Error)

    var errorDescription: String? {
        switch self {
        case .badURL: return "Bad URL"
        case .http(let status): return "Server returned HTTP \(status)"
        case .decoding(let e): return "Couldn't parse server response: \(e.localizedDescription)"
        case .transport(let e): return e.localizedDescription
        }
    }
}

struct APIClient {
    let config: ServerConfig
    private let session: URLSession

    init(config: ServerConfig, session: URLSession = .shared) {
        self.config = config
        self.session = session
    }

    private static func makeDecoder() -> JSONDecoder {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }

    /// GET `path` (e.g. "api/groups") and decode the JSON body as `T`.
    func get<T: Decodable>(_ path: String, as type: T.Type = T.self) async throws -> T {
        guard let url = URL(string: "\(config.apiBaseURL.absoluteString)/\(path)") else {
            throw APIError.badURL
        }
        var request = URLRequest(url: url)
        request.timeoutInterval = 10
        request.setValue("application/json", forHTTPHeaderField: "Accept")

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw APIError.transport(error)
        }
        if let http = response as? HTTPURLResponse, !(200...299).contains(http.statusCode) {
            throw APIError.http(status: http.statusCode)
        }
        do {
            return try Self.makeDecoder().decode(T.self, from: data)
        } catch {
            throw APIError.decoding(error)
        }
    }

    /// POST `path` with no body, ignoring the response payload. Transport
    /// commands return an empty body on success, so we only care that the
    /// status is 2xx — the resulting state arrives over MQTT, not here.
    func post(_ path: String) async throws {
        guard let url = URL(string: "\(config.apiBaseURL.absoluteString)/\(path)") else {
            throw APIError.badURL
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 10

        let response: URLResponse
        do {
            (_, response) = try await session.data(for: request)
        } catch {
            throw APIError.transport(error)
        }
        if let http = response as? HTTPURLResponse, !(200...299).contains(http.statusCode) {
            throw APIError.http(status: http.statusCode)
        }
    }

    /// POST `path` with a JSON object body, ignoring the response payload
    /// (2xx = success; resulting state arrives over MQTT). A non-2xx surfaces
    /// the status so callers can distinguish e.g. the server's 409
    /// `non_spotify_in_multiroom` ratchet. `body` values may be String or Int
    /// (e.g. seek's `{position_ms}`).
    func post(_ path: String, json body: [String: Any]) async throws {
        guard let url = URL(string: "\(config.apiBaseURL.absoluteString)/\(path)") else {
            throw APIError.badURL
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 10
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: body)

        let response: URLResponse
        do {
            (_, response) = try await session.data(for: request)
        } catch {
            throw APIError.transport(error)
        }
        if let http = response as? HTTPURLResponse, !(200...299).contains(http.statusCode) {
            throw APIError.http(status: http.statusCode)
        }
    }

    func fetchGroups() async throws -> GroupsResponse {
        try await get("api/groups")
    }

    func fetchStatus() async throws -> ServerStatus {
        try await get("api/status")
    }

    /// The device registry — used for friendly display names (`name`) keyed by
    /// `client_id`. Best-effort: callers degrade to the hostname if it fails.
    func fetchClients() async throws -> [ClientInfo] {
        try await get("api/clients", as: ClientsResponse.self).clients
    }

    /// Send a transport command to a client's player. The server proxies this
    /// to go-librespot; the resulting playback state echoes back over MQTT.
    func sendPlayback(_ clientId: String, _ action: PlaybackAction) async throws {
        try await post("api/clients/\(clientId)/playback/\(action.rawValue)")
    }

    /// Seek a client's player to an absolute position. `POST /api/clients/<id>/
    /// playback/seek {position_ms}` → go-librespot `/player/seek`. The new
    /// position echoes back over MQTT `playback`.
    /// Set a client's volume through the server control plane (FX-65). The
    /// server is the single routing authority — it publishes MQTT for internal
    /// devices and fires the external API (Particle, etc.) for external-volume
    /// devices, so the app holds no per-client routing logic. The resulting
    /// value echoes back over MQTT `status/clients/<id>/volume`. Mirrors web's
    /// `POST /api/clients/<id>/volume`.
    func setVolume(_ clientId: String, value: Int) async throws {
        try await post("api/clients/\(clientId)/volume", json: ["value": value])
    }

    func seek(_ clientId: String, positionMs: Int) async throws {
        try await post("api/clients/\(clientId)/playback/seek", json: ["position_ms": positionMs])
    }

    /// Switch a group's active source. The server sets the snapcast stream,
    /// fires any external switch API, and publishes the `mode` change over MQTT
    /// (which the store overlays). Mirrors web's `POST /api/groups/source`.
    func setGroupSource(groupId: String, homeClientId: String, sourceId: String) async throws {
        try await post("api/groups/source", json: [
            "group_id": groupId,
            "home_client_id": homeClientId,
            "source_id": sourceId,
        ])
    }

    /// Move a device into the target group (the group whose home is
    /// `targetClientId`). Mirrors web's `POST /api/groups/join`.
    func joinGroup(clientId: String, targetClientId: String) async throws {
        try await post("api/groups/join", json: [
            "client_id": clientId,
            "target_client_id": targetClientId,
        ])
    }

    /// Return a device to its own home group (ungroup). Mirrors web's
    /// `POST /api/groups/return-home`.
    func returnHome(clientId: String) async throws {
        try await post("api/groups/return-home", json: ["client_id": clientId])
    }
}

/// Transport actions the server whitelists (`handle_post_client_playback`).
/// `seek` is intentionally omitted — FX-17 has no scrub UI. Note the wire
/// names: `playpause` toggles, and previous is `prev` (not `previous`).
enum PlaybackAction: String {
    case playpause
    case next
    case prev
}
