//
//  ServerConfig.swift
//  Fauxnos
//
//  Points the app at a Fauxnos server. M1 scope is a single hard-coded host
//  (`fauxnos.local`, the server's bare-hostname alias that redirects :80 → the
//  Flask API on :8080). Discovery / multi-server is a later milestone — but the
//  host is overridable via UserDefaults so a dev can retarget the simulator at
//  a specific Pi without a rebuild.
//

import Foundation

struct ServerConfig: Equatable {
    /// Bare host or hostname:port. REST is plain http on :80 (→ :8080), MQTT is
    /// websocket on :9001 — both cleartext over the LAN (see Info.plist ATS).
    var host: String

    static let defaultHost = "fauxnos.local"

    /// UserDefaults key a developer can set to retarget without rebuilding,
    /// e.g. `defaults write dm.Fauxnos fauxnos.serverHost fauxnos000.local`.
    private static let overrideKey = "fauxnos.serverHost"

    static func load() -> ServerConfig {
        let override = UserDefaults.standard.string(forKey: overrideKey)
        let host = (override?.isEmpty == false) ? override! : defaultHost
        return ServerConfig(host: host)
    }

    var apiBaseURL: URL {
        URL(string: "http://\(host)")!
    }

    /// MQTT-over-websocket endpoint. The mosquitto websocket listener lives on
    /// :9001 regardless of the API port redirect.
    var mqttWebSocketURL: URL {
        let bareHost = host.split(separator: ":").first.map(String.init) ?? host
        return URL(string: "ws://\(bareHost):9001")!
    }
}
