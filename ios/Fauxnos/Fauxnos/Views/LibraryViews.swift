//
//  LibraryViews.swift
//  Fauxnos
//
//  The Library and Noise screens — the iOS port of the web's LibraryPanel,
//  LibraryBrowser and the Noise card's Tune popover:
//
//    LibraryScreen       the server-wide library (header "Library" button):
//                        filter pills, songs / artists / albums / playlists,
//                        tap a song to play it in a room you pick, ⋯ menus for
//                        playlists / details / delete, and Add (upload files,
//                        YouTube, Spotify, new playlist).
//    LibraryBrowseSheet  a room's Library card "browse" — same browser, but a
//                        tap plays straight into that room.
//    NoiseTuneSheet      the band graph for a room's low and high cuts.
//
//  All writes go through FauxnosStore+Library.swift.
//

import SwiftUI
import UniformTypeIdentifiers

// MARK: - Shared pieces

enum LibraryFilter: String, CaseIterable, Identifiable {
    case songs, artists, albums, playlists
    var id: String { rawValue }
    var label: String { rawValue.capitalized }
}

/// A page you can open from the library list.
enum LibraryPage: Hashable {
    case artist(String)
    case album(String)          // "album\0artist"
    case playlist(String)       // playlist id
    case youtube
    case spotify
}

private let unknownArtist = "Unknown artist"

/// Artists / albums (name → songs) and the songs a page shows.
@MainActor
struct LibraryCollections {
    let store: FauxnosStore

    var artists: [(String, [LibraryTrack])] {
        Dictionary(grouping: store.library.tracks) { $0.artist ?? unknownArtist }
            .sorted { $0.key.localizedCaseInsensitiveCompare($1.key) == .orderedAscending }
            .map { ($0.key, $0.value) }
    }

    var albums: [(String, [LibraryTrack])] {
        Dictionary(grouping: store.library.tracks.filter { $0.album?.isEmpty == false }) {
            "\($0.album ?? "")\u{0}\($0.artist ?? "")"
        }
        .sorted { $0.key.localizedCaseInsensitiveCompare($1.key) == .orderedAscending }
        .map { ($0.key, $0.value) }
    }

    func title(_ page: LibraryPage) -> String {
        switch page {
        case .artist(let name): return name
        case .album(let key): return String(key.split(separator: "\u{0}", omittingEmptySubsequences: false).first ?? "Album")
        case .playlist(let id): return playlist(id)?.name ?? "Playlist"
        case .youtube: return "Add from YouTube"
        case .spotify: return "Add from Spotify"
        }
    }

    func tracks(_ page: LibraryPage) -> [LibraryTrack] {
        switch page {
        case .artist(let name): return store.library.tracks.filter { ($0.artist ?? unknownArtist) == name }
        case .album(let key): return albums.first { $0.0 == key }?.1 ?? []
        case .playlist(let id): return (playlist(id)?.trackIds ?? []).compactMap { store.libraryTrack(id: $0) }
        case .youtube, .spotify: return []
        }
    }

    func playlist(_ id: String) -> LibraryPlaylist? {
        store.library.playlists.first { $0.id == id }
    }
}

/// Filter pills (web .fx-lib-pill): the active one is a filled capsule.
struct LibraryFilterPills: View {
    @Binding var filter: LibraryFilter

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: Space.sm) {
                ForEach(LibraryFilter.allCases) { f in
                    Button {
                        Haptics.select()
                        withAnimation(.fxQuick) { filter = f }
                    } label: {
                        Text(f.label)
                            .font(FxFont.fustat(15, .semibold))
                            .foregroundStyle(filter == f ? FX.surface1 : FX.text2)
                            .padding(.horizontal, 16)
                            .frame(height: 36)
                            .background(Capsule().fill(filter == f ? FX.text : .clear))
                            .overlay(Capsule().strokeBorder(filter == f ? .clear : FX.lineStrong, lineWidth: 1))
                    }
                    .buttonStyle(.plain)
                    .accessibilityAddTraits(filter == f ? .isSelected : [])
                }
            }
        }
    }
}

/// A song's cover (or a note glyph), with animated bars while it plays in a
/// room and an optional spinner for an import still downloading.
struct LibraryArtView: View {
    @EnvironmentObject private var store: FauxnosStore
    var art: String?
    var remoteURL: String? = nil
    var size: CGFloat = 48
    var fallbackIcon = "outline:music"
    var playing = false
    var busy = false

    private var url: URL? {
        if let remoteURL { return URL(string: remoteURL) }
        return store.api.libraryArtURL(art)
    }

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 8, style: .continuous).fill(FX.surface3)
            if let url {
                AsyncImage(url: url) { phase in
                    if let image = phase.image { image.resizable().scaledToFill() }
                    else { SourceIcon(icon: fallbackIcon, sourceId: nil, size: size * 0.42).foregroundStyle(FX.text3) }
                }
            } else {
                SourceIcon(icon: fallbackIcon, sourceId: nil, size: size * 0.42).foregroundStyle(FX.text3)
            }
            if playing || busy {
                Color.black.opacity(0.45)
                if busy { ProgressView().tint(.white) } else { PlayingBars().frame(width: 18, height: 16) }
            }
        }
        .frame(width: size, height: size)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

/// Three bouncing bars — "playing in a room" (web .fx-lib-thumb-overlay).
struct PlayingBars: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var animate = false

    var body: some View {
        HStack(alignment: .bottom, spacing: 2.5) {
            ForEach(0..<3, id: \.self) { i in
                Capsule().fill(.white)
                    .frame(width: 3)
                    .scaleEffect(y: reduceMotion ? 0.7 : (animate ? 1 : 0.35), anchor: .bottom)
                    .animation(reduceMotion ? nil :
                        .easeInOut(duration: 0.45).repeatForever().delay(Double(i) * 0.15), value: animate)
            }
        }
        .onAppear { animate = true }
        .accessibilityLabel("Playing")
    }
}

/// Toast at the bottom of a Library screen.
struct LibraryToastView: View {
    let toast: LibraryToast

    var body: some View {
        HStack(spacing: Space.sm) {
            Image(systemName: toast.isError ? "exclamationmark.circle.fill" : "checkmark.circle.fill")
                .foregroundStyle(toast.isError ? FX.err : FX.ok)
            Text(toast.text).font(FxFont.fustat(14, .semibold)).foregroundStyle(FX.text).lineLimit(2)
        }
        .padding(.vertical, Space.sm).padding(.horizontal, Space.lg)
        .background(Capsule().fill(.regularMaterial))
        .overlay(Capsule().strokeBorder(FX.line, lineWidth: 1))
        .shadow(color: .black.opacity(0.18), radius: 12, y: 4)
        .padding(.horizontal, Space.lg)
    }
}

private extension View {
    func libraryToast(_ toast: LibraryToast?) -> some View {
        overlay(alignment: .bottom) {
            ZStack {
                if let toast {
                    LibraryToastView(toast: toast).transition(.move(edge: .bottom).combined(with: .opacity))
                }
            }
            .padding(.bottom, Space.xl)
            .animation(.fxEase, value: toast)
        }
    }
}

// MARK: - Song row

/// One song. Tapping asks which room to play it in (with the rest of `queue`
/// after it); the ⋯ menu has the management actions.
struct LibraryTrackRow: View {
    @EnvironmentObject private var store: FauxnosStore
    let track: LibraryTrack
    var queue: [String]
    var playlist: LibraryPlaylist? = nil
    var onEdit: (LibraryTrack) -> Void
    var onNewPlaylist: ([String]) -> Void

    @State private var askRoom = false
    @State private var confirmDelete = false

    var body: some View {
        HStack(spacing: Space.md) {
            LibraryArtView(art: track.art, playing: !store.roomsPlaying(path: track.path).isEmpty)
            VStack(alignment: .leading, spacing: 2) {
                Text(track.title).font(FxFont.fustat(17, .semibold)).foregroundStyle(FX.text).lineLimit(1)
                Text(track.subtitle).font(FxFont.fustat(14, .medium)).foregroundStyle(FX.text2).lineLimit(1)
            }
            Spacer(minLength: Space.sm)
            Text(fmtDuration(track.durationMs)).font(FxFont.fustat(14, .medium)).monospacedDigit().foregroundStyle(FX.text2)
            Menu {
                Menu("Play in") {
                    ForEach(store.libraryRooms, id: \.id) { room in
                        Button(room.name) { Task { await store.playLibrary(queue, in: room.id) } }
                    }
                }
                Menu("Add to playlist") {
                    ForEach(store.library.playlists) { p in
                        Button(p.name) { Task { await store.addToPlaylist(p, trackIds: [track.id]) } }
                    }
                    Button("New playlist…") { onNewPlaylist([track.id]) }
                }
                Button("Edit details…") { onEdit(track) }
                if let playlist {
                    Button("Remove from \(playlist.name)") {
                        Task { await store.removeFromPlaylist(playlist, trackIds: [track.id]) }
                    }
                }
                Button("Delete from library", role: .destructive) { confirmDelete = true }
            } label: {
                Image(systemName: "ellipsis")
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(FX.text2)
                    .frame(width: 36, height: 36)
                    .contentShape(Rectangle())
            }
            .accessibilityLabel("More for \(track.title)")
        }
        .padding(.vertical, 6)
        .contentShape(Rectangle())
        .onTapGesture { Haptics.tap(); askRoom = true }
        .accessibilityAddTraits(.isButton)
        .confirmationDialog("Play \(track.title) in", isPresented: $askRoom, titleVisibility: .visible) {
            ForEach(store.libraryRooms, id: \.id) { room in
                Button(room.name) { Task { await store.playLibrary(queue, in: room.id) } }
            }
        } message: {
            if store.libraryRooms.isEmpty { Text("Add Library to a room in the web app's device panel first.") }
        }
        .confirmationDialog("Delete \(track.title)?", isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Delete", role: .destructive) { Task { await store.deleteTrack(track) } }
        } message: {
            Text("This removes the file from the server.")
        }
    }
}

/// An artist, album or playlist row; opens its page.
private struct LibraryCollectionRow: View {
    let title: String
    let subtitle: String
    let art: String?
    var fallbackIcon = "outline:music"

    var body: some View {
        HStack(spacing: Space.md) {
            LibraryArtView(art: art, fallbackIcon: fallbackIcon)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(FxFont.fustat(17, .semibold)).foregroundStyle(FX.text).lineLimit(1)
                Text(subtitle).font(FxFont.fustat(14, .medium)).foregroundStyle(FX.text2).lineLimit(1)
            }
            Spacer(minLength: Space.sm)
            Image(systemName: "chevron.right").font(.system(size: 13, weight: .semibold)).foregroundStyle(FX.text3)
        }
        .padding(.vertical, 6)
        .contentShape(Rectangle())
    }
}

private func songsLabel(_ n: Int) -> String { n == 1 ? "1 song" : "\(n) songs" }

private func bytesLabel(_ n: Int) -> String {
    let gb = Double(n) / 1e9
    return gb >= 1 ? String(format: "%.1f GB", gb) : "\(n / 1_000_000) MB"
}

// MARK: - Library screen

struct LibraryScreen: View {
    @EnvironmentObject private var store: FauxnosStore
    @Environment(\.dismiss) private var dismiss

    @State private var filter: LibraryFilter = .songs
    @State private var path: [LibraryPage] = []
    @State private var showImporter = false
    @State private var newPlaylistTracks: [String]?
    @State private var newPlaylistName = ""
    @State private var editing: LibraryTrack?

    private var collections: LibraryCollections { LibraryCollections(store: store) }

    var body: some View {
        NavigationStack(path: $path) {
            ScrollView {
                VStack(alignment: .leading, spacing: Space.md) {
                    LibraryFilterPills(filter: $filter)
                    Text(storageLine).font(FxFont.fustat(14, .medium)).foregroundStyle(FX.text2)
                    list
                }
                .padding(.horizontal, Space.lg)
                .padding(.bottom, 80)
            }
            .background(FX.bg.ignoresSafeArea())
            .navigationTitle("Library")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Done") { dismiss() }
                }
                ToolbarItem(placement: .topBarTrailing) { addMenu }
            }
            .navigationDestination(for: LibraryPage.self) { page in
                switch page {
                case .youtube: LinkImportView(spotify: false)
                case .spotify: LinkImportView(spotify: true)
                default: LibraryPageView(page: page, onEdit: { editing = $0 }, onNewPlaylist: askNewPlaylist)
                }
            }
            .refreshable { await store.refreshLibrary() }
        }
        .tint(FX.text)
        .libraryToast(store.libraryToast)
        .task { await store.refreshLibrary() }
        .fileImporter(isPresented: $showImporter,
                      allowedContentTypes: [.mp3, .mpeg4Audio],
                      allowsMultipleSelection: true) { result in
            if case .success(let urls) = result { Task { await store.uploadLibrary(urls) } }
        }
        .alert("New playlist", isPresented: Binding(get: { newPlaylistTracks != nil },
                                                    set: { if !$0 { newPlaylistTracks = nil } })) {
            TextField("Name", text: $newPlaylistName)
            Button("Create") {
                let name = newPlaylistName.trimmingCharacters(in: .whitespaces)
                let ids = newPlaylistTracks ?? []
                if !name.isEmpty { Task { await store.createPlaylist(name, trackIds: ids) } }
            }
            Button("Cancel", role: .cancel) {}
        }
        .sheet(item: $editing) { track in
            EditTrackSheet(track: track).environmentObject(store)
        }
    }

    private var storageLine: String {
        var line = songsLabel(store.library.tracks.count)
        if let s = store.library.storage { line += " • \(bytesLabel(s.free)) free" }
        return line
    }

    private func askNewPlaylist(_ tracks: [String]) {
        newPlaylistName = ""
        newPlaylistTracks = tracks
    }

    private var addMenu: some View {
        Menu {
            Button { showImporter = true } label: { Label("Upload files", systemImage: "square.and.arrow.up") }
            Button { path.append(.youtube) } label: { Label("From YouTube", systemImage: "play.rectangle") }
                .disabled(store.library.youtubeAvailable != true)
            Button { path.append(.spotify) } label: { Label("From Spotify", systemImage: "music.note") }
                .disabled(store.library.youtubeAvailable != true)
            Button { askNewPlaylist([]) } label: { Label("New playlist", systemImage: "music.note.list") }
        } label: {
            Label("Add", systemImage: "plus")
                .font(FxFont.fustat(15, .bold))
        }
    }

    @ViewBuilder
    private var list: some View {
        LazyVStack(alignment: .leading, spacing: 0) {
            switch filter {
            case .songs:
                ForEach(store.runningImports) { job in
                    HStack(spacing: Space.md) {
                        LibraryArtView(art: nil, remoteURL: job.thumbnail, busy: true)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(job.title ?? job.url).font(FxFont.fustat(17, .semibold)).foregroundStyle(FX.text2).lineLimit(1)
                            Text([job.artist, "Importing…"].compactMap { $0 }.joined(separator: " · "))
                                .font(FxFont.fustat(14, .medium)).foregroundStyle(FX.text2).lineLimit(1)
                        }
                        Spacer(minLength: 0)
                    }
                    .padding(.vertical, 6)
                }
                let tracks = store.library.tracks
                ForEach(Array(tracks.enumerated()), id: \.element.id) { i, t in
                    LibraryTrackRow(track: t, queue: tracks[i...].map(\.id),
                                    onEdit: { editing = $0 }, onNewPlaylist: askNewPlaylist)
                }
                if tracks.isEmpty && store.libraryLoaded && store.runningImports.isEmpty {
                    emptyNote("No songs yet. Use Add to upload files or import from YouTube or Spotify.")
                }
            case .artists:
                ForEach(collections.artists, id: \.0) { name, tracks in
                    NavigationLink(value: LibraryPage.artist(name)) {
                        LibraryCollectionRow(title: name, subtitle: songsLabel(tracks.count),
                                             art: tracks.first { $0.art != nil }?.art)
                    }
                    .buttonStyle(.plain)
                }
            case .albums:
                ForEach(collections.albums, id: \.0) { key, tracks in
                    NavigationLink(value: LibraryPage.album(key)) {
                        LibraryCollectionRow(title: tracks.first?.album ?? "Album",
                                             subtitle: [tracks.first?.artist, songsLabel(tracks.count)].compactMap { $0 }.joined(separator: " · "),
                                             art: tracks.first { $0.art != nil }?.art)
                    }
                    .buttonStyle(.plain)
                }
                if collections.albums.isEmpty && store.libraryLoaded {
                    emptyNote("No albums. Albums come from each song's details.")
                }
            case .playlists:
                ForEach(store.library.playlists) { p in
                    let tracks = collections.tracks(.playlist(p.id))
                    NavigationLink(value: LibraryPage.playlist(p.id)) {
                        LibraryCollectionRow(title: p.name, subtitle: songsLabel(tracks.count),
                                             art: tracks.first { $0.art != nil }?.art, fallbackIcon: "outline:playlist")
                    }
                    .buttonStyle(.plain)
                }
                if store.library.playlists.isEmpty && store.libraryLoaded {
                    emptyNote("No playlists yet. Make one from Add.")
                }
            }
        }
    }

    private func emptyNote(_ text: String) -> some View {
        Text(text)
            .font(FxFont.fustat(15, .medium)).foregroundStyle(FX.text2)
            .frame(maxWidth: .infinity).multilineTextAlignment(.center)
            .padding(.vertical, Space.xxl)
    }
}

/// An artist, album or playlist page: its songs, Play all, and (playlists)
/// rename / delete.
private struct LibraryPageView: View {
    @EnvironmentObject private var store: FauxnosStore
    @Environment(\.dismiss) private var dismiss
    let page: LibraryPage
    var onEdit: (LibraryTrack) -> Void
    var onNewPlaylist: ([String]) -> Void

    @State private var askRoom = false
    @State private var renaming = false
    @State private var newName = ""
    @State private var confirmDelete = false

    private var collections: LibraryCollections { LibraryCollections(store: store) }
    private var tracks: [LibraryTrack] { collections.tracks(page) }
    private var playlist: LibraryPlaylist? {
        if case .playlist(let id) = page { return collections.playlist(id) }
        return nil
    }

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 0) {
                ForEach(Array(tracks.enumerated()), id: \.element.id) { i, t in
                    LibraryTrackRow(track: t, queue: tracks[i...].map(\.id), playlist: playlist,
                                    onEdit: onEdit, onNewPlaylist: onNewPlaylist)
                }
                if tracks.isEmpty {
                    Text(playlist != nil ? "No songs yet. Add songs from their ⋯ menu." : "No songs here.")
                        .font(FxFont.fustat(15, .medium)).foregroundStyle(FX.text2)
                        .frame(maxWidth: .infinity).padding(.vertical, Space.xxl)
                }
            }
            .padding(.horizontal, Space.lg)
        }
        .background(FX.bg.ignoresSafeArea())
        .navigationTitle(collections.title(page))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItemGroup(placement: .topBarTrailing) {
                if !tracks.isEmpty {
                    Button { askRoom = true } label: { Image(systemName: "play.fill") }
                        .accessibilityLabel("Play all")
                }
                if let playlist {
                    Menu {
                        Button("Rename…") { newName = playlist.name; renaming = true }
                        Button("Delete playlist", role: .destructive) { confirmDelete = true }
                    } label: { Image(systemName: "ellipsis.circle") }
                    .accessibilityLabel("Playlist options")
                }
            }
        }
        .confirmationDialog("Play all in", isPresented: $askRoom, titleVisibility: .visible) {
            ForEach(store.libraryRooms, id: \.id) { room in
                Button(room.name) { Task { await store.playLibrary(tracks.map(\.id), in: room.id) } }
            }
        }
        .alert("Rename playlist", isPresented: $renaming) {
            TextField("Name", text: $newName)
            Button("Save") {
                let name = newName.trimmingCharacters(in: .whitespaces)
                if let playlist, !name.isEmpty { Task { await store.renamePlaylist(playlist, to: name) } }
            }
            Button("Cancel", role: .cancel) {}
        }
        .confirmationDialog("Delete \(playlist?.name ?? "playlist")?", isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Delete playlist", role: .destructive) {
                if let playlist { Task { await store.deletePlaylist(playlist); dismiss() } }
            }
        } message: {
            Text("Its songs stay in the library.")
        }
    }
}

/// Edit a song's title, artist and album (written into the file's tags).
private struct EditTrackSheet: View {
    @EnvironmentObject private var store: FauxnosStore
    @Environment(\.dismiss) private var dismiss
    let track: LibraryTrack
    @State private var title = ""
    @State private var artist = ""
    @State private var album = ""

    var body: some View {
        NavigationStack {
            Form {
                TextField("Title", text: $title)
                TextField("Artist", text: $artist)
                TextField("Album", text: $album)
            }
            .navigationTitle("Edit details")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        Task { await store.editTrack(track.id, title: title, artist: artist, album: album) }
                        dismiss()
                    }
                    .disabled(title.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
        }
        .presentationDetents([.medium])
        .onAppear {
            title = track.title
            artist = track.artist ?? ""
            album = track.album ?? ""
        }
    }
}

// MARK: - Add from YouTube / Spotify

/// Paste a link; the details load on their own; Import queues it in the
/// background (it shows in Songs with a spinner until it lands).
private struct LinkImportView: View {
    @EnvironmentObject private var store: FauxnosStore
    @Environment(\.dismiss) private var dismiss
    let spotify: Bool

    @State private var link = ""
    @State private var preview: LinkPreview?
    @State private var looking = false
    @State private var lookedUp = ""

    private var canImport: Bool {
        guard let preview else { return false }
        return spotify ? preview.match != nil : preview.importable != false
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Space.lg) {
                TextField(spotify ? "Paste a Spotify song link" : "Paste a YouTube link", text: $link)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .keyboardType(.URL)
                    .font(FxFont.fustat(16, .medium))
                    .padding(.horizontal, Space.md).frame(height: 48)
                    .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(FX.surface2))
                    .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(FX.lineStrong, lineWidth: 1))
                if looking {
                    HStack(spacing: Space.sm) {
                        ProgressView()
                        Text(spotify ? "Finding the song and its audio…" : "Finding the video…")
                            .font(FxFont.fustat(15, .medium)).foregroundStyle(FX.text2)
                    }
                }
                if let preview { previewCard(preview) }
            }
            .padding(Space.lg)
        }
        .background(FX.bg.ignoresSafeArea())
        .navigationTitle(spotify ? "Add from Spotify" : "Add from YouTube")
        .navigationBarTitleDisplayMode(.inline)
        .task(id: link) { await lookUp() }
    }

    private func lookUp() async {
        let url = link.trimmingCharacters(in: .whitespacesAndNewlines)
        guard url.hasPrefix("http") || url.hasPrefix("spotify:"), url != lookedUp else { return }
        try? await Task.sleep(nanoseconds: 500_000_000)   // let pasting settle
        guard !Task.isCancelled else { return }
        lookedUp = url
        preview = nil
        looking = true
        defer { looking = false }
        do {
            let p = spotify ? try await store.api.spotifyPreview(url) : try await store.api.youtubePreview(url)
            preview = p
            if spotify && p.match == nil { store.showLibraryToast("Couldn't find matching audio for that song", error: true) }
        } catch {
            store.showLibraryToast("Couldn't look that up: \((error as? LocalizedError)?.errorDescription ?? error.localizedDescription)", error: true)
        }
    }

    private func previewCard(_ p: LinkPreview) -> some View {
        VStack(alignment: .leading, spacing: Space.md) {
            HStack(spacing: Space.md) {
                AsyncImage(url: p.thumbnail.flatMap { URL(string: $0) }) { phase in
                    if let image = phase.image { image.resizable().scaledToFill() } else { FX.surface3 }
                }
                .frame(width: spotify ? 72 : 112, height: spotify ? 72 : 63)
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                VStack(alignment: .leading, spacing: 2) {
                    Text(p.title ?? "Untitled").font(FxFont.fustat(17, .semibold)).foregroundStyle(FX.text).lineLimit(2)
                    Text([p.artist, p.album].compactMap { $0 }.joined(separator: " · "))
                        .font(FxFont.fustat(14, .medium)).foregroundStyle(FX.text2).lineLimit(1)
                    if p.durationMs != nil {
                        Text(fmtDuration(p.durationMs)).font(FxFont.fustat(14, .medium)).foregroundStyle(FX.text2)
                    }
                }
                Spacer(minLength: 0)
            }
            if let m = p.match {
                Text("Audio from YouTube: \(m.title ?? m.url)\([m.channel, fmtDuration(m.durationMs)].compactMap { $0 }.filter { !$0.isEmpty }.map { " · \($0)" }.joined())")
                    .font(FxFont.fustat(14, .medium)).foregroundStyle(FX.text2)
            }
            Button {
                Haptics.commit()
                Task { if await store.importLink(p, spotify: spotify) { dismiss() } }
            } label: {
                Text("Import")
                    .font(FxFont.fustat(17, .bold))
                    .foregroundStyle(canImport ? FX.surface1 : FX.text3)
                    .frame(maxWidth: .infinity).frame(height: 50)
                    .background(Capsule().fill(canImport ? FX.text : FX.surface2))
            }
            .buttonStyle(.plain)
            .disabled(!canImport)
        }
        .padding(Space.lg)
        .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(FX.surface1))
        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(FX.line, lineWidth: 1))
    }
}

// MARK: - Room browse sheet

/// A room's Library card → browse: the same filters and pages, but a tap plays
/// straight into this room (the song and the rest of the list after it).
struct LibraryBrowseSheet: View {
    @EnvironmentObject private var store: FauxnosStore
    @Environment(\.dismiss) private var dismiss
    let clientId: String
    @State private var filter: LibraryFilter = .songs

    private var collections: LibraryCollections { LibraryCollections(store: store) }
    private var currentId: String? { store.libraryTrack(forClient: clientId)?.id }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: Space.md) {
                    LibraryFilterPills(filter: $filter)
                    LazyVStack(alignment: .leading, spacing: 0) {
                        switch filter {
                        case .songs: songs(store.library.tracks)
                        case .artists:
                            ForEach(collections.artists, id: \.0) { name, tracks in
                                NavigationLink(value: LibraryPage.artist(name)) {
                                    LibraryCollectionRow(title: name, subtitle: songsLabel(tracks.count),
                                                         art: tracks.first { $0.art != nil }?.art)
                                }.buttonStyle(.plain)
                            }
                        case .albums:
                            ForEach(collections.albums, id: \.0) { key, tracks in
                                NavigationLink(value: LibraryPage.album(key)) {
                                    LibraryCollectionRow(title: tracks.first?.album ?? "Album",
                                                         subtitle: tracks.first?.artist ?? songsLabel(tracks.count),
                                                         art: tracks.first { $0.art != nil }?.art)
                                }.buttonStyle(.plain)
                            }
                        case .playlists:
                            ForEach(store.library.playlists) { p in
                                let tracks = collections.tracks(.playlist(p.id))
                                NavigationLink(value: LibraryPage.playlist(p.id)) {
                                    LibraryCollectionRow(title: p.name, subtitle: songsLabel(tracks.count),
                                                         art: tracks.first { $0.art != nil }?.art, fallbackIcon: "outline:playlist")
                                }.buttonStyle(.plain)
                            }
                        }
                    }
                }
                .padding(.horizontal, Space.lg)
            }
            .background(FX.bg.ignoresSafeArea())
            .navigationTitle("Play in \(store.displayName(forId: clientId, fallback: clientId))")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Done") { dismiss() } } }
            .navigationDestination(for: LibraryPage.self) { page in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) { songs(collections.tracks(page)) }
                        .padding(.horizontal, Space.lg)
                }
                .background(FX.bg.ignoresSafeArea())
                .navigationTitle(collections.title(page))
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button { play(collections.tracks(page).map(\.id)) } label: { Image(systemName: "play.fill") }
                            .accessibilityLabel("Play all")
                    }
                }
            }
        }
        .tint(FX.text)
        .presentationDetents([.large])
        .libraryToast(store.libraryToast)
    }

    @ViewBuilder
    private func songs(_ tracks: [LibraryTrack]) -> some View {
        ForEach(Array(tracks.enumerated()), id: \.element.id) { i, t in
            Button { play(tracks[i...].map(\.id)) } label: {
                HStack(spacing: Space.md) {
                    LibraryArtView(art: t.art, size: 44, playing: t.id == currentId && store.libraryNow[clientId]?.isPlaying == true)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(t.title).font(FxFont.fustat(17, .semibold))
                            .foregroundStyle(t.id == currentId ? FX.ok : FX.text).lineLimit(1)
                        Text(t.artist ?? unknownArtist).font(FxFont.fustat(14, .medium)).foregroundStyle(FX.text2).lineLimit(1)
                    }
                    Spacer(minLength: 0)
                }
                .padding(.vertical, 6)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
        }
        if tracks.isEmpty {
            Text(store.library.tracks.isEmpty ? "The library is empty. Add songs from Library." : "Nothing here yet.")
                .font(FxFont.fustat(15, .medium)).foregroundStyle(FX.text2)
                .frame(maxWidth: .infinity).padding(.vertical, Space.xxl)
        }
    }

    private func play(_ ids: [String]) {
        guard !ids.isEmpty else { return }
        Haptics.tap()
        Task { await store.playLibrary(ids, in: clientId) }
        dismiss()
    }
}

// MARK: - Noise tune sheet (band graph)

/// The low and high cuts as the filter curve they make, on a log frequency
/// axis (20 Hz–20 kHz). Drag either edge; dragging past the outer end turns
/// that cut off. Sent on release (each change restarts the generator ~1 s).
struct NoiseTuneSheet: View {
    @EnvironmentObject private var store: FauxnosStore
    @Environment(\.dismiss) private var dismiss
    let clientId: String

    @State private var draft: (low: Int, high: Int)?
    @State private var dragging: Bool? // true = low edge, false = high edge

    private var stored: (low: Int, high: Int) {
        let n = store.noise[clientId]
        return (n?.lowCut ?? 0, n?.highCut ?? 0)
    }
    private var current: (low: Int, high: Int) { draft ?? stored }

    private static let fMin = 20.0, fMax = 20000.0
    private static let floorDb = 30.0

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: Space.lg) {
                GeometryReader { geo in
                    let w = geo.size.width, h = geo.size.height
                    ZStack {
                        Canvas { ctx, size in
                            for f in [100.0, 1000.0, 10000.0] {
                                var grid = Path()
                                let x = xFor(f, w: size.width)
                                grid.move(to: CGPoint(x: x, y: 0)); grid.addLine(to: CGPoint(x: x, y: size.height))
                                ctx.stroke(grid, with: .color(FX.line), lineWidth: 1)
                            }
                            let curve = curvePath(size: size)
                            var area = curve
                            area.addLine(to: CGPoint(x: size.width, y: size.height))
                            area.addLine(to: CGPoint(x: 0, y: size.height))
                            area.closeSubpath()
                            ctx.fill(area, with: .color(FX.text.opacity(0.12)))
                            ctx.stroke(curve, with: .color(FX.text), style: StrokeStyle(lineWidth: 2.5, lineJoin: .round))
                        }
                        handle(low: true, w: w, h: h)
                        handle(low: false, w: w, h: h)
                    }
                    .contentShape(Rectangle())
                    .gesture(
                        DragGesture(minimumDistance: 0)
                            .onChanged { g in
                                if dragging == nil {
                                    let lowX = xFor(Double(current.low == 0 ? Int(Self.fMin) : current.low), w: w)
                                    let highX = xFor(Double(current.high == 0 ? Int(Self.fMax) : current.high), w: w)
                                    dragging = abs(g.startLocation.x - lowX) <= abs(g.startLocation.x - highX)
                                    Haptics.select()
                                }
                                update(low: dragging!, hz: fFor(g.location.x, w: w))
                            }
                            .onEnded { _ in commit() }
                    )
                }
                .frame(height: 180)
                HStack {
                    label("Low cut", current.low)
                    Spacer()
                    label("High cut", current.high)
                }
                Button {
                    Haptics.tap()
                    store.setNoise(["low_cut": 0, "high_cut": 0], clientId: clientId)
                } label: {
                    Text("Reset cuts").font(FxFont.fustat(15, .semibold)).foregroundStyle(FX.text2)
                }
                .buttonStyle(.plain)
                .disabled(stored.low == 0 && stored.high == 0)
                Spacer(minLength: 0)
            }
            .padding(Space.xl)
            .background(FX.bg.ignoresSafeArea())
            .navigationTitle("Tune")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Done") { dismiss() } } }
        }
        .tint(FX.text)
        .presentationDetents([.medium])
    }

    private func label(_ title: String, _ hz: Int) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(FxFont.fustat(14, .medium)).foregroundStyle(FX.text2)
            Text(hzLabel(hz)).font(FxFont.fustat(19, .bold)).foregroundStyle(FX.text)
        }
    }

    private func handle(low: Bool, w: CGFloat, h: CGFloat) -> some View {
        let hz = low ? current.low : current.high
        let f = hz == 0 ? (low ? Self.fMin : Self.fMax) : Double(hz)
        let y = hz == 0 ? yFor(0, h: h) : yFor(-3, h: h)
        return Circle()
            .fill(FX.surface1)
            .overlay(Circle().strokeBorder(FX.text, lineWidth: 2.5))
            .frame(width: dragging == low ? 22 : 16, height: dragging == low ? 22 : 16)
            .position(x: xFor(f, w: w), y: y)
            .animation(.fxQuick, value: dragging)
            .allowsHitTesting(false)
    }

    // MARK: Geometry

    private func xFor(_ f: Double, w: CGFloat) -> CGFloat {
        CGFloat(log10(f / Self.fMin) / 3) * w
    }

    private func fFor(_ x: CGFloat, w: CGFloat) -> Double {
        Self.fMin * pow(10, 3 * Double(min(max(x / w, 0), 1)))
    }

    private func yFor(_ db: Double, h: CGFloat) -> CGFloat {
        let top: CGFloat = 12
        return top + CGFloat(min(Self.floorDb, -db) / Self.floorDb) * (h - top)
    }

    /// 2-pole Butterworth high-pass + low-pass, as sox applies them.
    private func responseDb(_ f: Double) -> Double {
        var db = 0.0
        let (lo, hi) = (Double(current.low), Double(current.high))
        if lo > 0 { let r = pow(f / lo, 4); db += 10 * log10(r / (1 + r)) }
        if hi > 0 { db -= 10 * log10(1 + pow(f / hi, 4)) }
        return db
    }

    private func curvePath(size: CGSize) -> Path {
        var p = Path()
        for i in 0...96 {
            let f = Self.fMin * pow(10, 3 * Double(i) / 96)
            let pt = CGPoint(x: xFor(f, w: size.width), y: yFor(responseDb(f), h: size.height))
            if i == 0 { p.move(to: pt) } else { p.addLine(to: pt) }
        }
        return p
    }

    // MARK: Editing

    private func roundHz(_ hz: Double) -> Int {
        let step = hz < 100 ? 5.0 : hz < 1000 ? 10.0 : 100.0
        return Int((hz / step).rounded() * step)
    }

    /// Clamp into each cut's range, keep the band ≥ ~half an octave, and turn
    /// a cut off when it's dragged past its outer end.
    private func update(low: Bool, hz: Double) {
        var next = current
        if low {
            if hz < 22 { next.low = 0 }
            else { next.low = roundHz(min(hz, min(2000, next.high > 0 ? Double(next.high) / 1.5 : .infinity))) }
        } else {
            if hz > 18200 { next.high = 0 }
            else { next.high = roundHz(max(hz, max(200, next.low > 0 ? Double(next.low) * 1.5 : 0))) }
        }
        draft = next
    }

    private func commit() {
        defer { draft = nil; dragging = nil }
        guard let d = draft else { return }
        var changes: [String: Any] = [:]
        if d.low != stored.low { changes["low_cut"] = d.low }
        if d.high != stored.high { changes["high_cut"] = d.high }
        if !changes.isEmpty { Haptics.commit(); store.setNoise(changes, clientId: clientId) }
    }

    private func hzLabel(_ hz: Int) -> String {
        hz == 0 ? "Off" : hz >= 1000 ? String(format: "%.1f kHz", Double(hz) / 1000) : "\(hz) Hz"
    }
}
