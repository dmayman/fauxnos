//
//  GroupCard.swift
//  Fauxnos
//
//  The reusable per-group card — FX-17's deliverable and the surface that
//  volume (FX-18) and source switching (FX-19) will hang off. It turns the M1
//  read-only row into a living now-playing surface: album art + track meta,
//  transport (play/pause/next/prev), a read-only progress bar, and the M1
//  per-device volume display (control deferred to FX-18).
//
//  Mirrors the web `GroupCard.jsx` contract:
//    - Transport controls only for the Spotify source with real metadata
//      (go-librespot is the only thing the transport endpoint drives).
//    - Play/pause is optimistic; the MQTT `playback` echo is the source of
//      truth and reconciles the local pending flag.
//    - Position interpolates client-side between MQTT updates so the bar moves.
//

import SwiftUI

struct GroupCard: View {
    @EnvironmentObject private var store: FauxnosStore
    let group: SpeakerGroup

    @State private var showSourcePicker = false

    private var homeId: String? { store.homeClientId(of: group) }
    private var track: Track? { store.track(for: group) }
    private var playback: Playback? { store.playback(for: group) }
    private var source: String? { store.currentSource(of: group) }
    private var hasMeta: Bool { track?.hasMeta == true }

    /// Transport is only meaningful for the Spotify source with metadata —
    /// the server proxies these commands to go-librespot. Mirrors the web's
    /// `hasControls = sourceId === 'spotify' && hasMeta`.
    private var hasControls: Bool { source == "spotify" && hasMeta }

    /// Display title: friendly group name if the server has one, else the home
    /// device's hostname (friendly per-device names are FX-22 / M3).
    private var title: String {
        if let name = group.name, !name.isEmpty { return name }
        if let home = homeId, let client = group.clients.first(where: { $0.id == home }) {
            return client.host.name
        }
        return group.clients.first?.host.name ?? group.id
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header
            nowPlaying
            if hasControls { transport }
            volumeRows
        }
        .padding(14)
        .background(.background.secondary, in: RoundedRectangle(cornerRadius: 14))
        .sheet(isPresented: $showSourcePicker) {
            SourcePickerSheet(group: group)
        }
    }

    // MARK: - Header (title + source picker + active indicator)

    private var header: some View {
        HStack(spacing: 10) {
            Image(systemName: group.clients.count > 1 ? "hifispeaker.2.fill" : "hifispeaker.fill")
                .font(.title3)
                .foregroundStyle(store.isPlaying(group) ? Color.accentColor : .secondary)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.headline)
                Text(subtitle)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            if store.isPlaying(group) {
                Image(systemName: "waveform")
                    .foregroundStyle(Color.accentColor)
                    .symbolEffect(.variableColor.iterative, options: .repeating)
            }
            sourceChip
        }
    }

    private var subtitle: String {
        let n = group.clients.count
        return n == 1 ? "1 device" : "\(n) devices"
    }

    /// Tappable chip showing the active source; opens the picker sheet. Label
    /// prefers the source's friendly `label` from `/api/groups`, else the id.
    private var sourceChip: some View {
        Button { showSourcePicker = true } label: {
            HStack(spacing: 4) {
                Image(systemName: sourceGlyphName(source))
                Text(sourceLabel).lineLimit(1)
                Image(systemName: "chevron.down").font(.caption2)
            }
            .font(.caption.weight(.medium))
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(.fill.tertiary, in: Capsule())
            .foregroundStyle(.primary)
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Source: \(sourceLabel). Tap to change.")
    }

    private var sourceLabel: String {
        guard let s = source else { return "Source" }
        if let match = (group.sources ?? []).first(where: { $0.id == s }),
           let l = match.label, !l.isEmpty { return l }
        return s.capitalized
    }

    // MARK: - Now playing (art + track meta, or idle state)

    @ViewBuilder
    private var nowPlaying: some View {
        HStack(spacing: 12) {
            albumArt
            if hasMeta {
                VStack(alignment: .leading, spacing: 3) {
                    Text(track?.title ?? "—")
                        .font(.subheadline.weight(.semibold))
                        .lineLimit(1)
                    if let sub = trackSubtitle {
                        Text(sub)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                }
            } else {
                Text("Nothing playing")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
        }
    }

    private var trackSubtitle: String? {
        let parts = [track?.artist, track?.album].compactMap { $0 }.filter { !$0.isEmpty }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    /// 56pt art tile. Loads the track's `artUrl` async; falls back to a
    /// source-appropriate glyph while loading, on failure, or when idle.
    private var albumArt: some View {
        let url = hasMeta ? track?.artUrl.flatMap(URL.init(string:)) : nil
        return RoundedRectangle(cornerRadius: 8)
            .fill(.quaternary)
            .frame(width: 56, height: 56)
            .overlay {
                if let url {
                    AsyncImage(url: url) { phase in
                        switch phase {
                        case .success(let image):
                            image.resizable().scaledToFill()
                        default:
                            sourceGlyph
                        }
                    }
                } else {
                    sourceGlyph
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private var sourceGlyph: some View {
        Image(systemName: sourceGlyphName(source))
            .font(.title2)
            .foregroundStyle(.secondary)
    }

    // MARK: - Transport

    private var transport: some View {
        VStack(spacing: 10) {
            progressBar
            HStack(spacing: 36) {
                TransportButton(systemName: "backward.fill", size: 20, label: "Previous") {
                    Task { await store.sendPlayback(.prev, for: group) }
                }
                PlayPauseButton(group: group)
                TransportButton(systemName: "forward.fill", size: 20, label: "Next") {
                    Task { await store.sendPlayback(.next, for: group) }
                }
            }
            .frame(maxWidth: .infinity)
        }
    }

    // MARK: - Progress (read-only; seek is out of FX-17 scope)

    @ViewBuilder
    private var progressBar: some View {
        let duration = Double(track?.durationMs ?? 0)
        if duration > 0 {
            TimelineView(.periodic(from: .now, by: 0.5)) { context in
                let pos = interpolatedPosition(at: context.date, duration: duration)
                let fraction = min(max(pos / duration, 0), 1)
                VStack(spacing: 4) {
                    GeometryReader { geo in
                        ZStack(alignment: .leading) {
                            Capsule().fill(.quaternary)
                            Capsule().fill(Color.accentColor)
                                .frame(width: geo.size.width * fraction)
                        }
                    }
                    .frame(height: 4)
                    HStack {
                        Text(fmtTime(pos)).font(.caption2.monospacedDigit()).foregroundStyle(.tertiary)
                        Spacer()
                        Text(fmtTime(duration)).font(.caption2.monospacedDigit()).foregroundStyle(.tertiary)
                    }
                }
            }
        }
    }

    /// Interpolate playback position client-side between MQTT updates, mirroring
    /// the web `useInterpolatedPosition`. `updatedAt` and `positionMs` are both
    /// epoch/relative milliseconds.
    private func interpolatedPosition(at now: Date, duration: Double) -> Double {
        guard let pb = playback else { return 0 }
        let base = Double(pb.positionMs ?? 0)
        guard pb.isPlaying == true else { return min(base, duration) }
        let t0 = pb.updatedAt ?? (now.timeIntervalSince1970 * 1000)
        let elapsed = (now.timeIntervalSince1970 * 1000) - t0
        return min(max(base + elapsed, 0), duration)
    }

    private func fmtTime(_ ms: Double) -> String {
        let total = Int(max(ms, 0) / 1000)
        return String(format: "%d:%02d", total / 60, total % 60)
    }

    // MARK: - Volume (FX-18: group fan-out + per-device sliders)

    @ViewBuilder
    private var volumeRows: some View {
        let isMulti = group.clients.count > 1
        if isMulti {
            GroupVolumeSlider(clients: group.clients)
        }
        ForEach(group.clients) { client in
            DeviceVolumeRow(client: client, showName: isMulti)
        }
    }
}

// MARK: - Transport buttons

/// Play/pause with optimistic state: flips immediately on tap, then defers to
/// the MQTT `playback` echo. The pending flag clears whenever a fresh playback
/// payload arrives (`updatedAt` changes), mirroring the web MediaCard.
private struct PlayPauseButton: View {
    @EnvironmentObject private var store: FauxnosStore
    let group: SpeakerGroup
    @State private var pending: Bool?

    private var actualPlaying: Bool { store.playback(for: group)?.isPlaying == true }
    private var displayed: Bool { pending ?? actualPlaying }

    var body: some View {
        Button {
            pending = !displayed
            Task { await store.sendPlayback(.playpause, for: group) }
        } label: {
            Image(systemName: displayed ? "pause.fill" : "play.fill")
                .font(.title)
                .frame(width: 44, height: 44)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .foregroundStyle(Color.accentColor)
        .accessibilityLabel(displayed ? "Pause" : "Play")
        .onChange(of: store.playback(for: group)?.updatedAt) { _, _ in
            // The echo landed — let MQTT be the source of truth again.
            pending = nil
        }
    }
}

private struct TransportButton: View {
    let systemName: String
    let size: CGFloat
    let label: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: systemName)
                .font(.system(size: size))
                .frame(width: 44, height: 44)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .foregroundStyle(.primary)
        .accessibilityLabel(label)
    }
}

// MARK: - Source picker sheet (FX-19)

/// Native sheet listing the group's real available sources. Selection is driven
/// by the live `mode` echo (via `store.currentSource`), so it sticks instead of
/// reverting after a switch. Multi-room groups only offer Spotify (server +
/// `availableSources` enforce this) with a hint explaining why.
struct SourcePickerSheet: View {
    @EnvironmentObject private var store: FauxnosStore
    @Environment(\.dismiss) private var dismiss
    let group: SpeakerGroup

    private var sources: [Source] { store.availableSources(for: group) }
    private var isMulti: Bool { group.clients.count > 1 }
    private var active: String? { store.currentSource(of: group) }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    if sources.isEmpty {
                        Text("No sources available")
                            .foregroundStyle(.secondary)
                    }
                    ForEach(sources) { s in
                        Button {
                            Task { await store.switchSource(s.id, in: group) }
                            dismiss()
                        } label: {
                            HStack(spacing: 12) {
                                Image(systemName: sourceGlyphName(s.id))
                                    .frame(width: 24)
                                    .foregroundStyle(.secondary)
                                Text(s.label?.isEmpty == false ? s.label! : s.id.capitalized)
                                    .foregroundStyle(.primary)
                                Spacer()
                                if active == s.id {
                                    Image(systemName: "checkmark")
                                        .foregroundStyle(.tint)
                                        .fontWeight(.semibold)
                                }
                            }
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }
                }
                if isMulti {
                    Section {
                        Text("Ungroup to use other sources — only Spotify plays across multiple grouped devices.")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .navigationTitle("Source")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
        .presentationDetents([.medium, .large])
    }
}

/// Source-id → SF Symbol, shared by the picker rows and the card chip.
func sourceGlyphName(_ id: String?) -> String {
    switch id {
    case "spotify": return "music.note"
    case "airplay": return "airplayaudio"
    case "analog":  return "mic.fill"
    case .some:     return "dot.radiowaves.left.and.right"
    default:        return "headphones"
    }
}

// MARK: - Volume glyph

/// SF-symbol speaker glyph that ramps with level — mute (slash) only at 0,
/// matching the web `VolumeIcon` states (mute / low / high).
private func volumeGlyph(_ v: Int) -> String {
    if v == 0 { return "speaker.slash.fill" }
    if v < 40 { return "speaker.wave.1.fill" }
    return "speaker.wave.2.fill"
}

// MARK: - Per-device volume slider

/// One device's live volume. Tap the glyph to mute/unmute (restores the last
/// non-zero level). External-volume devices (AirPlay) show the controlled-by
/// caption instead of a slider — we don't fight the iPhone for authority.
struct DeviceVolumeRow: View {
    @EnvironmentObject private var store: FauxnosStore
    let client: SnapClient
    let showName: Bool

    @State private var editing = false
    @State private var dragValue: Double = 0
    @State private var lastNonZero: Int = 50

    private var current: Int { store.volume(for: client) }

    var body: some View {
        HStack(spacing: 8) {
            if store.isExternalVolume(client.id) {
                Image(systemName: "airplayaudio")
                    .font(.caption).foregroundStyle(.secondary).frame(width: 18)
                if showName { nameLabel }
                Text("Volume controlled by iPhone")
                    .font(.caption).foregroundStyle(.tertiary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .lineLimit(1)
            } else {
                Button {
                    if current > 0 { lastNonZero = current }
                    let next = current == 0 ? max(lastNonZero, 1) : 0
                    store.publishVolume(next, clientId: client.id)
                } label: {
                    Image(systemName: volumeGlyph(displayValue))
                        .font(.caption).foregroundStyle(.secondary).frame(width: 18)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(displayValue == 0 ? "Unmute \(client.host.name)" : "Mute \(client.host.name)")

                if showName { nameLabel }
                Slider(value: binding, in: 0...100) { isEditing in
                    editing = isEditing
                    if isEditing { dragValue = Double(current) }
                }
                .tint(.accentColor)
                .accessibilityLabel("\(client.host.name) volume")
                Text("\(displayValue)")
                    .font(.caption.monospacedDigit()).foregroundStyle(.tertiary)
                    .frame(width: 28, alignment: .trailing)
            }
        }
    }

    private var nameLabel: some View {
        Text(client.host.name)
            .font(.caption).foregroundStyle(.secondary)
            .frame(width: 96, alignment: .leading).lineLimit(1)
    }

    private var displayValue: Int { editing ? Int(dragValue.rounded()) : current }

    /// During a drag the slider reads the local value (so a lagging MQTT echo
    /// can't yank it); each move publishes optimistically through the store.
    private var binding: Binding<Double> {
        Binding(
            get: { editing ? dragValue : Double(current) },
            set: { newVal in
                dragValue = newVal
                store.publishVolume(Int(newVal.rounded()), clientId: client.id)
            }
        )
    }
}

// MARK: - Group ("All") volume slider — offset-preserving fan-out

/// Group-level volume across a multi-room card. Displays the member average;
/// dragging applies the delta to every member, preserving each device's offset
/// from the average (pre-tuned room balance survives a global move) — mirroring
/// the web `AllRow`. Mute/unmute snapshots and restores each member's level.
struct GroupVolumeSlider: View {
    @EnvironmentObject private var store: FauxnosStore
    let clients: [SnapClient]

    @State private var editing = false
    @State private var dragAvg: Double = 0
    @State private var baseAvg: Int = 0
    @State private var baseVols: [String: Int] = [:]
    @State private var preMute: [String: Int]?

    private var avg: Int {
        guard !clients.isEmpty else { return 0 }
        let total = clients.reduce(0) { $0 + store.volume(for: $1) }
        return Int((Double(total) / Double(clients.count)).rounded())
    }

    private var displayAvg: Int { editing ? Int(dragAvg.rounded()) : avg }

    var body: some View {
        HStack(spacing: 8) {
            Button {
                toggleMuteAll()
            } label: {
                Image(systemName: volumeGlyph(displayAvg))
                    .font(.caption).foregroundStyle(.secondary).frame(width: 18)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(displayAvg == 0 ? "Unmute all" : "Mute all")

            Text("All")
                .font(.caption.weight(.medium)).foregroundStyle(.secondary)
                .frame(width: 96, alignment: .leading)

            Slider(value: binding, in: 0...100) { isEditing in
                editing = isEditing
                if isEditing {
                    baseAvg = avg
                    dragAvg = Double(avg)
                    baseVols = Dictionary(uniqueKeysWithValues: clients.map { ($0.id, store.volume(for: $0)) })
                }
            }
            .tint(.accentColor)
            .accessibilityLabel("All devices volume")

            Text("\(displayAvg)")
                .font(.caption.monospacedDigit()).foregroundStyle(.tertiary)
                .frame(width: 28, alignment: .trailing)
        }
    }

    private var binding: Binding<Double> {
        Binding(
            get: { editing ? dragAvg : Double(avg) },
            set: { newVal in
                dragAvg = newVal
                let delta = Int(newVal.rounded()) - baseAvg
                for c in clients {
                    let base = baseVols[c.id] ?? store.volume(for: c)
                    store.publishVolume(base + delta, clientId: c.id)  // store clamps 0…100
                }
            }
        )
    }

    /// Mute all → snapshot each member and zero them; unmute → restore the
    /// snapshot, so per-room balance is preserved across the toggle.
    private func toggleMuteAll() {
        if avg == 0, let saved = preMute {
            for c in clients { store.publishVolume(saved[c.id] ?? 50, clientId: c.id) }
            preMute = nil
        } else {
            preMute = Dictionary(uniqueKeysWithValues: clients.map { ($0.id, store.volume(for: $0)) })
            for c in clients { store.publishVolume(0, clientId: c.id) }
        }
    }
}
