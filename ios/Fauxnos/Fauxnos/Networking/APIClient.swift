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

    // MARK: - Library (server-wide music library; docs/LOCAL_SOURCES.md)

    /// One request with any method and an optional JSON body. Returns the raw
    /// body; a non-2xx throws `.http` (callers that care read the server's
    /// `{"error": …}` message via `errorMessage(_:)`).
    @discardableResult
    func send(_ method: String, _ path: String, json body: [String: Any]? = nil,
              timeout: TimeInterval = 15) async throws -> Data {
        guard let url = URL(string: "\(config.apiBaseURL.absoluteString)/\(path)") else {
            throw APIError.badURL
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = timeout
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        }
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw APIError.transport(error)
        }
        if let http = response as? HTTPURLResponse, !(200...299).contains(http.statusCode) {
            throw LibraryRequestError(status: http.statusCode, message: Self.errorMessage(data))
        }
        return data
    }

    /// The server's `{"error": "…"}` text, if any.
    static func errorMessage(_ data: Data) -> String? {
        (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["error"] as? String
    }

    private func decode<T: Decodable>(_ data: Data, as type: T.Type = T.self) throws -> T {
        do { return try Self.makeDecoder().decode(T.self, from: data) }
        catch { throw APIError.decoding(error) }
    }

    func fetchLibrary() async throws -> LibraryIndex {
        try await get("api/library")
    }

    /// Play songs (in this order) in a room — `POST /api/library/play`. The
    /// room switches to the Library source; its player state echoes over MQTT.
    func playLibrary(clientId: String, trackIds: [String]) async throws {
        try await send("POST", "api/library/play", json: ["client_id": clientId, "track_ids": trackIds])
    }

    func updateTrack(_ id: String, title: String, artist: String, album: String) async throws {
        try await send("PATCH", "api/library/tracks/\(id)", json: ["title": title, "artist": artist, "album": album])
    }

    func deleteTrack(_ id: String) async throws {
        try await send("DELETE", "api/library/tracks/\(id)")
    }

    func createPlaylist(name: String, trackIds: [String]) async throws {
        try await send("POST", "api/library/playlists", json: ["name": name, "track_ids": trackIds])
    }

    func updatePlaylist(_ id: String, name: String? = nil, add: [String]? = nil, remove: [String]? = nil) async throws {
        var body: [String: Any] = [:]
        if let name { body["name"] = name }
        if let add { body["add"] = add }
        if let remove { body["remove"] = remove }
        try await send("PATCH", "api/library/playlists/\(id)", json: body)
    }

    func deletePlaylist(_ id: String) async throws {
        try await send("DELETE", "api/library/playlists/\(id)")
    }

    func youtubePreview(_ url: String) async throws -> LinkPreview {
        try decode(try await send("POST", "api/library/youtube/preview", json: ["url": url], timeout: 60))
    }

    func spotifyPreview(_ url: String) async throws -> LinkPreview {
        try decode(try await send("POST", "api/library/spotify/preview", json: ["url": url], timeout: 90))
    }

    /// Queue a background import of a video's audio. `tags`/`artUrl` carry a
    /// Spotify song's details and cover; title/artist/thumbnail show the job
    /// in the song list while it runs.
    func importYoutube(url: String, title: String?, artist: String?, thumbnail: String?,
                       tags: [String: String]? = nil, artUrl: String? = nil) async throws {
        var body: [String: Any] = ["url": url]
        if let title { body["title"] = title }
        if let artist { body["artist"] = artist }
        if let thumbnail { body["thumbnail"] = thumbnail }
        if let tags { body["tags"] = tags }
        if let artUrl { body["art_url"] = artUrl }
        try await send("POST", "api/library/youtube", json: body)
    }

    /// Upload MP3/M4A files (multipart field `file`). Returns how many the
    /// server added; per-file rejections come back as messages.
    func uploadLibrary(files: [URL]) async throws -> (added: Int, errors: [String]) {
        guard let url = URL(string: "\(config.apiBaseURL.absoluteString)/api/library/upload") else {
            throw APIError.badURL
        }
        let boundary = "fauxnos-\(UUID().uuidString)"
        var body = Data()
        for file in files {
            let accessed = file.startAccessingSecurityScopedResource()
            defer { if accessed { file.stopAccessingSecurityScopedResource() } }
            let data = try Data(contentsOf: file)
            let mime = file.pathExtension.lowercased() == "m4a" ? "audio/mp4" : "audio/mpeg"
            body.append(Data("--\(boundary)\r\n".utf8))
            body.append(Data("Content-Disposition: form-data; name=\"file\"; filename=\"\(file.lastPathComponent)\"\r\n".utf8))
            body.append(Data("Content-Type: \(mime)\r\n\r\n".utf8))
            body.append(data)
            body.append(Data("\r\n".utf8))
        }
        body.append(Data("--\(boundary)--\r\n".utf8))
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 300
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        let (data, response) = try await session.upload(for: request, from: body)
        let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
        let added = (json?["added"] as? [Any])?.count ?? 0
        let errors = (json?["errors"] as? [[String: Any]])?.compactMap { e -> String? in
            guard let msg = e["error"] as? String else { return nil }
            return "\(e["file"] as? String ?? "File"): \(msg)"
        } ?? []
        if let http = response as? HTTPURLResponse, !(200...299).contains(http.statusCode), added == 0 {
            throw LibraryRequestError(status: http.statusCode, message: errors.first ?? Self.errorMessage(data))
        }
        return (added, errors)
    }

    /// Cover art for a library song (`/library-art/<file>`).
    func libraryArtURL(_ art: String?) -> URL? {
        guard let art, !art.isEmpty else { return nil }
        return URL(string: "\(config.apiBaseURL.absoluteString)/library-art/\(art)")
    }

    /// Restart the fauxnos-server process (`POST /api/server/restart`). The
    /// server schedules a detached `systemctl --user restart` ~1s out and
    /// returns 202 immediately, so this call resolves before the bounce
    /// actually happens. The MQTT link then drops and reconnects on its own.
    func restartServer() async throws {
        try await post("api/server/restart")
    }
}

/// A failed Library call, carrying the server's own message when it sent one.
struct LibraryRequestError: LocalizedError {
    let status: Int
    let message: String?
    var errorDescription: String? { message ?? "Server returned HTTP \(status)" }
}

/// Transport actions the server whitelists (`handle_post_client_playback`).
/// `seek` is intentionally omitted — FX-17 has no scrub UI. Note the wire
/// names: `playpause` toggles, and previous is `prev` (not `previous`).
enum PlaybackAction: String {
    case playpause
    case next
    case prev
}
