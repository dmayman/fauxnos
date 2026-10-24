//
//  LibraryModels.swift
//  Fauxnos
//
//  Wire formats for the Noise and Library sources, mirroring the server and
//  device contracts in docs/LOCAL_SOURCES.md (the web reads the same shapes):
//
//    MQTT status/clients/<id>/noise    → NoiseState
//    MQTT status/clients/<id>/library  → LibraryNowPlaying
//    REST GET /api/library             → LibraryIndex (songs, playlists, jobs)
//    REST POST /api/library/{youtube,spotify}/preview → LinkPreview
//
//  Decoded with `.convertFromSnakeCase` like the rest of Models.swift.
//

import Foundation

// MARK: - Noise (MQTT status/clients/<id>/noise)

/// A room's noise settings. `on: false` keeps Noise selected but silent; the
/// cuts are in Hz, 0 = off. Older devices omit `on` (treated as on).
struct NoiseState: Decodable, Equatable {
    var on: Bool?
    var color: String?
    var lowCut: Int?
    var highCut: Int?

    var isOn: Bool { on != false }
    var colorName: String { color ?? "brown" }
}

enum NoiseColor: String, CaseIterable, Identifiable {
    case white, pink, brown
    var id: String { rawValue }
    var label: String { rawValue.capitalized }
}

// MARK: - Library player (MQTT status/clients/<id>/library)

/// What a room's Library player (its MPD) is doing. `path` is the song's path
/// in the server library (nil for a URL from elsewhere, like radio).
struct LibraryNowPlaying: Decodable, Equatable {
    let state: String?          // "play" | "pause" | "stop"
    let file: String?
    let path: String?
    let position: Int?
    let queueLength: Int?
    let elapsedMs: Int?
    let durationMs: Int?
    let updatedAt: Double?

    var isPlaying: Bool { state == "play" }
    /// Something is loaded (playing or paused) — the card dims only without one.
    var hasSong: Bool { file != nil && state != "stop" }
}

// MARK: - Library index (REST GET /api/library)

struct LibraryIndex: Decodable {
    var tracks: [LibraryTrack]
    var playlists: [LibraryPlaylist]
    var storage: LibraryStorage?
    var jobs: [LibraryJob]
    var youtubeAvailable: Bool?

    static let empty = LibraryIndex(tracks: [], playlists: [], storage: nil, jobs: [], youtubeAvailable: false)
}

struct LibraryTrack: Decodable, Identifiable, Equatable {
    let id: String
    let path: String
    let title: String
    let artist: String?
    let album: String?
    let durationMs: Int?
    let size: Int?
    /// File name under /library-art/, e.g. "4147f8ff74e2.webp".
    let art: String?

    var subtitle: String {
        let parts = [artist, album].compactMap { $0 }.filter { !$0.isEmpty }
        return parts.isEmpty ? "Unknown artist" : parts.joined(separator: " · ")
    }
}

struct LibraryPlaylist: Decodable, Identifiable, Equatable {
    let id: String
    let name: String
    let trackIds: [String]
}

struct LibraryStorage: Decodable {
    let total: Int
    let used: Int
    let free: Int
}

/// A YouTube or Spotify import running (or finished) in the background.
struct LibraryJob: Decodable, Identifiable, Equatable {
    let id: String
    let url: String
    let status: String          // "running" | "done" | "failed"
    let title: String?
    let artist: String?
    let thumbnail: String?
    let error: String?
}

// MARK: - Link previews (YouTube / Spotify)

struct LinkPreview: Decodable, Equatable {
    let url: String
    let title: String?
    let artist: String?
    let album: String?
    let durationMs: Int?
    let thumbnail: String?
    /// YouTube only: whether there's M4A audio to import.
    let importable: Bool?
    /// Spotify only: the YouTube video whose audio would be imported.
    let match: YouTubeMatch?
}

struct YouTubeMatch: Decodable, Equatable {
    let url: String
    let title: String?
    let channel: String?
    let durationMs: Int?
}

// MARK: - Formatting

func fmtDuration(_ ms: Int?) -> String {
    guard let ms else { return "" }
    let s = ms / 1000
    return String(format: "%d:%02d", s / 60, s % 60)
}
