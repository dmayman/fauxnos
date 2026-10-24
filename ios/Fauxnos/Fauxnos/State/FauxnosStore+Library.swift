//
//  FauxnosStore+Library.swift
//  Fauxnos
//
//  The Noise and Library half of the store — the iOS counterpart of the web's
//  useLibrary hook plus the noise/library parts of useMqtt. State lives in the
//  store's @Published properties (`noise`, `libraryNow`, `library`); this file
//  holds the reads views need and the actions they call.
//
//  Writes follow the web: Noise settings and Library transport go straight to
//  the room over MQTT (set/clients/<id>/noise, /library/<action>); library
//  management (play, upload, edit, playlists, imports) goes through the
//  server's /api/library REST API, then refreshes the index.
//

import Foundation

/// A short message shown at the bottom of the Library screens.
struct LibraryToast: Identifiable, Equatable {
    let id = UUID()
    let text: String
    let isError: Bool
}

extension FauxnosStore {

    // MARK: - Reads

    /// The library song a room's player is on, or nil (nothing loaded, or a
    /// URL from outside the library).
    func libraryTrack(forClient id: String?) -> LibraryTrack? {
        guard let id, let path = libraryNow[id]?.path else { return nil }
        return library.tracks.first { $0.path == path }
    }

    func libraryTrack(id: String) -> LibraryTrack? {
        library.tracks.first { $0.id == id }
    }

    func noiseState(for group: SpeakerGroup) -> NoiseState? {
        homeClientId(of: group).flatMap { noise[$0] }
    }

    func libraryNowPlaying(for group: SpeakerGroup) -> LibraryNowPlaying? {
        homeClientId(of: group).flatMap { libraryNow[$0] }
    }

    /// The cover a group shows, whatever its source: the Spotify track's art,
    /// the generated Noise art, or the Library song's cover. Feeds the card's
    /// art, its tint, and the page backdrop alike.
    func artURLString(for group: SpeakerGroup) -> String? {
        switch currentSource(of: group) {
        case "spotify":
            guard let t = track(for: group), t.hasMeta else { return nil }
            return t.artUrl
        case "noise":
            return NoiseArt.urlString(for: noiseState(for: group)?.color)
        case "library":
            return api.libraryArtURL(libraryTrack(forClient: homeClientId(of: group))?.art)?.absoluteString
        default:
            return nil
        }
    }

    /// Rooms that can play the library: their source list includes Library.
    var libraryRooms: [(id: String, name: String)] {
        liveGroups.compactMap { g -> (String, String)? in
            guard (g.sources ?? []).contains(where: { $0.id == "library" }),
                  let home = homeClientId(of: g) else { return nil }
            return (home, displayName(forId: home, fallback: home))
        }
        .sorted { $0.1.localizedCaseInsensitiveCompare($1.1) == .orderedAscending }
    }

    /// Names of the rooms playing a library song right now.
    func roomsPlaying(path: String) -> [String] {
        libraryNow.compactMap { id, now in
            guard now.isPlaying, now.path == path, modes[id] == "library" else { return nil }
            return displayName(forId: id, fallback: id)
        }
        .sorted()
    }

    var runningImports: [LibraryJob] { library.jobs.filter { $0.status == "running" } }

    // MARK: - Noise (MQTT)

    /// Change a room's noise settings: any of on / color / low_cut / high_cut.
    /// Optimistic; the device republishes its stored settings (and snaps a
    /// rejected change back).
    func setNoise(_ changes: [String: Any], clientId: String) {
        var n = noise[clientId] ?? NoiseState()
        if let on = changes["on"] as? Bool { n.on = on }
        if let c = changes["color"] as? String { n.color = c }
        if let lo = changes["low_cut"] as? Int { n.lowCut = lo }
        if let hi = changes["high_cut"] as? Int { n.highCut = hi }
        noise[clientId] = n
        guard let data = try? JSONSerialization.data(withJSONObject: changes) else { return }
        mqtt?.publish(topic: "set/clients/\(clientId)/noise", payload: data)
    }

    // MARK: - Library player (MQTT)

    /// Library transport on a room: "toggle", "next" or "prev".
    func libraryControl(_ action: String, clientId: String) {
        mqtt?.publish(topic: "set/clients/\(clientId)/library/\(action)", payload: Data())
    }

    /// Seek a room's Library player. Re-bases the position optimistically so
    /// the scrubber doesn't snap back while the device confirms.
    func librarySeek(_ positionMs: Int, clientId: String) {
        if let now = libraryNow[clientId] {
            libraryNow[clientId] = LibraryNowPlaying(
                state: now.state, file: now.file, path: now.path, position: now.position,
                queueLength: now.queueLength, elapsedMs: positionMs, durationMs: now.durationMs,
                updatedAt: Date().timeIntervalSince1970 * 1000)
        }
        mqtt?.publish(topic: "set/clients/\(clientId)/library/seek", payload: Data("\(positionMs)".utf8))
    }

    // MARK: - Library index (REST)

    func refreshLibrary() async {
        if let index = try? await api.fetchLibrary() {
            // An import we saw running that has now finished gets a toast.
            let wasRunning = Set(runningImports.map(\.id))
            library = index
            libraryLoaded = true
            for job in index.jobs where wasRunning.contains(job.id) && job.status != "running" {
                let name = job.title ?? "YouTube audio"
                if job.status == "done" { showLibraryToast("Imported \(name)") }
                else { showLibraryToast("Couldn't import \(name): \(job.error ?? "unknown error")", error: true) }
            }
        }
        // While an import runs, poll so it lands (and leaves the list) on its own.
        libraryPollTask?.cancel()
        if !runningImports.isEmpty {
            libraryPollTask = Task { [weak self] in
                try? await Task.sleep(nanoseconds: 2_000_000_000)
                guard !Task.isCancelled else { return }
                await self?.refreshLibrary()
            }
        }
    }

    func showLibraryToast(_ text: String, error: Bool = false) {
        let toast = LibraryToast(text: text, isError: error)
        libraryToast = toast
        Task { [weak self] in
            try? await Task.sleep(nanoseconds: error ? 6_000_000_000 : 3_000_000_000)
            if self?.libraryToast == toast { self?.libraryToast = nil }
        }
    }

    private func message(_ error: Error) -> String {
        (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
    }

    /// Run a library change, then refresh; toast `done` or the error.
    private func libraryAction(_ done: String?, failed: String, _ work: () async throws -> Void) async {
        do {
            try await work()
            if let done { showLibraryToast(done) }
        } catch {
            showLibraryToast("\(failed): \(message(error))", error: true)
        }
        await refreshLibrary()
    }

    // MARK: - Library actions

    /// Play songs (this one first, then the rest) in a room.
    func playLibrary(_ trackIds: [String], in clientId: String) async {
        let room = displayName(forId: clientId, fallback: clientId)
        do {
            try await api.playLibrary(clientId: clientId, trackIds: trackIds)
            setModeOptimistic("library", clientId: clientId)
            showLibraryToast("Playing in \(room)")
        } catch {
            showLibraryToast("Couldn't play in \(room): \(message(error))", error: true)
        }
    }

    func uploadLibrary(_ files: [URL]) async {
        guard !files.isEmpty else { return }
        showLibraryToast(files.count == 1 ? "Uploading \(files[0].lastPathComponent)…" : "Uploading \(files.count) files…")
        do {
            let result = try await api.uploadLibrary(files: files)
            if let first = result.errors.first {
                showLibraryToast(first, error: true)
            } else {
                showLibraryToast(result.added == 1 ? "Added 1 song" : "Added \(result.added) songs")
            }
        } catch {
            showLibraryToast("Upload failed: \(message(error))", error: true)
        }
        await refreshLibrary()
    }

    func editTrack(_ id: String, title: String, artist: String, album: String) async {
        await libraryAction(nil, failed: "Couldn't save the details") {
            try await api.updateTrack(id, title: title, artist: artist, album: album)
        }
    }

    func deleteTrack(_ track: LibraryTrack) async {
        await libraryAction("Deleted \(track.title)", failed: "Couldn't delete \(track.title)") {
            try await api.deleteTrack(track.id)
        }
    }

    func createPlaylist(_ name: String, trackIds: [String] = []) async {
        await libraryAction(trackIds.isEmpty ? "Created \(name)" : "Added to \(name)", failed: "Couldn't create the playlist") {
            try await api.createPlaylist(name: name, trackIds: trackIds)
        }
    }

    func addToPlaylist(_ playlist: LibraryPlaylist, trackIds: [String]) async {
        await libraryAction("Added to \(playlist.name)", failed: "Couldn't add to \(playlist.name)") {
            try await api.updatePlaylist(playlist.id, add: trackIds)
        }
    }

    func removeFromPlaylist(_ playlist: LibraryPlaylist, trackIds: [String]) async {
        await libraryAction("Removed from \(playlist.name)", failed: "Couldn't remove from \(playlist.name)") {
            try await api.updatePlaylist(playlist.id, remove: trackIds)
        }
    }

    func renamePlaylist(_ playlist: LibraryPlaylist, to name: String) async {
        await libraryAction(nil, failed: "Couldn't rename the playlist") {
            try await api.updatePlaylist(playlist.id, name: name)
        }
    }

    func deletePlaylist(_ playlist: LibraryPlaylist) async {
        await libraryAction("Deleted \(playlist.name)", failed: "Couldn't delete \(playlist.name)") {
            try await api.deletePlaylist(playlist.id)
        }
    }

    /// Queue an import from a YouTube or Spotify preview.
    func importLink(_ preview: LinkPreview, spotify: Bool) async -> Bool {
        do {
            if spotify {
                guard let match = preview.match else { return false }
                var tags: [String: String] = [:]
                if let t = preview.title { tags["title"] = t }
                if let a = preview.artist { tags["artist"] = a }
                try await api.importYoutube(url: match.url, title: preview.title, artist: preview.artist,
                                            thumbnail: preview.thumbnail, tags: tags, artUrl: preview.thumbnail)
            } else {
                try await api.importYoutube(url: preview.url, title: preview.title, artist: preview.artist,
                                            thumbnail: preview.thumbnail)
            }
            await refreshLibrary()
            return true
        } catch {
            showLibraryToast("Couldn't start the import: \(message(error))", error: true)
            return false
        }
    }
}
