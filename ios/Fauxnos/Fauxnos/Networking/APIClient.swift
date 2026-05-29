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

    func fetchGroups() async throws -> GroupsResponse {
        try await get("api/groups")
    }

    func fetchStatus() async throws -> ServerStatus {
        try await get("api/status")
    }
}
