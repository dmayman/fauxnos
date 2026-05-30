//
//  GroupCard.swift
//  Fauxnos
//
//  The reusable per-group card. M2 (FX-17/18/19/20/32) wired it up functionally;
//  FX-33 is the design-parity pass that elevates it to the web app's design
//  intent while feeling native: the album-art-derived tint system, a deliberate
//  type hierarchy, a hero now-playing region, a thin native scrub bar, a
//  circular accent transport, restyled volume rows, and haptics on the
//  interactions that matter (grouping, source switch, transport, mute).
//
//  All the M2 behavior is preserved verbatim — optimistic volume with the
//  echo-suppression window, the play/pause MQTT reconciliation, offset-
//  preserving group volume, drag-to-group / return-home, and the FX-32 seek.
//  This file only changes how those behaviors look and feel.
//
//  Design intent mirrors the web `GroupCard.jsx`:
//    - Transport only for the Spotify source with real metadata.
//    - Play/pause optimistic; MQTT `playback` echo is the source of truth.
//    - Position interpolates client-side between MQTT updates.
//

import SwiftUI

struct GroupCard: View {
    @EnvironmentObject private var store: FauxnosStore
    @ObservedObject private var artStore = AlbumArtColorStore.shared
    @Environment(\.colorScheme) private var colorScheme
    let group: SpeakerGroup

    @State private var showSourcePicker = false
    @State private var dropTargeted = false
    @State private var scrubbing = false
    @State private var scrubValue: Double = 0

    private var homeId: String? { store.homeClientId(of: group) }
    private var track: Track? { store.track(for: group) }
    private var playback: Playback? { store.playback(for: group) }
    private var source: String? { store.currentSource(of: group) }
    private var hasMeta: Bool { track?.hasMeta == true }

    /// Transport is only meaningful for the Spotify source with metadata —
    /// the server proxies these commands to go-librespot. Mirrors the web's
    /// `hasControls = sourceId === 'spotify' && hasMeta`.
    private var hasControls: Bool { source == "spotify" && hasMeta }

    /// Album-art-derived palette for this card. Neutral when idle / no art /
    /// extraction pending. Recomputed for the active appearance.
    private var palette: ArtPalette {
        guard hasMeta, let raw = artStore.color(for: track?.artUrl) else { return .neutral }
        return buildArtPalette(from: raw, dark: colorScheme == .dark)
    }

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
        VStack(alignment: .leading, spacing: Space.md) {
            header
            if hasMeta {
                nowPlaying
                if hasControls {
                    progressBar
                    transport
                }
            } else {
                idleRow
            }
            volumeSection
        }
        .padding(Space.lg)
        .background(cardBackground)
        .overlay {
            // Highlight when a dragged device is hovering this group as a join
            // target — a soft accent ring that pulses in.
            RoundedRectangle(cornerRadius: Radius.card, style: .continuous)
                .strokeBorder(dropTargeted ? Color.accentColor : FX.line,
                              lineWidth: dropTargeted ? 2.5 : 1)
        }
        .shadow(color: .black.opacity(colorScheme == .dark ? 0.35 : 0.06),
                radius: dropTargeted ? 18 : 10, y: dropTargeted ? 8 : 4)
        .scaleEffect(dropTargeted ? 1.01 : 1)
        .dropDestination(for: String.self) { items, _ in
            guard let dropped = items.first else { return false }
            let target = store.homeClientId(of: group) ?? group.id
            Haptics.success()
            Task { await store.joinGroup(clientId: dropped, targetHomeClientId: target) }
            return true
        } isTargeted: { targeted in
            if targeted != dropTargeted, targeted { Haptics.tap() }
            dropTargeted = targeted
        }
        .animation(.fxEase, value: dropTargeted)
        .animation(.fxEase, value: palette)
        .task(id: track?.artUrl) { artStore.ensure(track?.artUrl) }
        .sheet(isPresented: $showSourcePicker) {
            SourcePickerSheet(group: group)
        }
    }

    // MARK: - Card background (art-tinted hero for media, neutral for idle)

    @ViewBuilder
    private var cardBackground: some View {
        let shape = RoundedRectangle(cornerRadius: Radius.card, style: .continuous)
        ZStack {
            shape.fill(hasMeta ? FX.surface1 : FX.surface2)
            if hasMeta {
                LinearGradient(
                    colors: [palette.cardTint.opacity(0.9), palette.cardTint.opacity(0)],
                    startPoint: .top, endPoint: .bottom
                )
                .clipShape(shape)
            }
        }
    }

    /// Visible grip that lifts a device on long-press to drag it between groups.
    /// Carries the device's client id; the drag preview is a compact name pill.
    @ViewBuilder
    func dragHandle(clientId: String, name: String) -> some View {
        Image(systemName: "line.3.horizontal")
            .font(.footnote.weight(.semibold))
            .foregroundStyle(FX.text3)
            .draggable(clientId) {
                Label(name, systemImage: "hifispeaker.fill")
                    .font(.subheadline.weight(.medium))
                    .padding(.horizontal, Space.md)
                    .padding(.vertical, Space.sm)
                    .background(.regularMaterial, in: Capsule())
            }
            .accessibilityLabel("Drag \(name) to another group to join it")
    }

    // MARK: - Header (identity + source picker + active indicator)

    private var header: some View {
        HStack(spacing: Space.sm) {
            // Single-device groups drag as a whole via this handle; multi-room
            // members each carry their own handle in the device rows below.
            if group.clients.count == 1, let home = homeId {
                dragHandle(clientId: home, name: title)
            }
            Image(systemName: group.clients.count > 1 ? "hifispeaker.2.fill" : "hifispeaker.fill")
                .font(.subheadline)
                .foregroundStyle(store.isPlaying(group) ? palette.accent : FX.text2)
            VStack(alignment: .leading, spacing: 1) {
                Text(title)
                    .font(.headline)
                    .foregroundStyle(FX.text)
                    .lineLimit(1)
                Text(subtitle)
                    .font(.caption)
                    .foregroundStyle(FX.text2)
            }
            Spacer(minLength: Space.sm)
            if store.isPlaying(group) {
                Image(systemName: "waveform")
                    .font(.subheadline)
                    .foregroundStyle(palette.accent)
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
        Button {
            Haptics.tap()
            showSourcePicker = true
        } label: {
            HStack(spacing: Space.xs) {
                Image(systemName: sourceGlyphName(source))
                Text(sourceLabel).lineLimit(1)
                Image(systemName: "chevron.down").font(.caption2.weight(.semibold))
            }
            .font(.caption.weight(.semibold))
            .padding(.horizontal, Space.md)
            .padding(.vertical, 7)
            .background(.ultraThinMaterial, in: Capsule())
            .overlay(Capsule().strokeBorder(FX.line, lineWidth: 1))
            .foregroundStyle(FX.text)
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

    // MARK: - Now playing (hero: art + track meta)

    private var nowPlaying: some View {
        HStack(spacing: Space.md) {
            albumArt
            VStack(alignment: .leading, spacing: 4) {
                Text(track?.title ?? "—")
                    .font(.title3.weight(.bold))
                    .foregroundStyle(FX.text)
                    .lineLimit(2)
                if let sub = trackSubtitle {
                    Text(sub)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(palette.accent)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: 0)
        }
    }

    /// Idle state — compact source glyph tile + "Nothing playing".
    private var idleRow: some View {
        HStack(spacing: Space.md) {
            RoundedRectangle(cornerRadius: Radius.art, style: .continuous)
                .fill(FX.surface3)
                .frame(width: 44, height: 44)
                .overlay {
                    Image(systemName: sourceGlyphName(source))
                        .font(.title3)
                        .foregroundStyle(FX.text2)
                }
            Text("Nothing playing")
                .font(.subheadline)
                .foregroundStyle(FX.text2)
            Spacer(minLength: 0)
        }
    }

    private var trackSubtitle: String? {
        let parts = [track?.artist, track?.album].compactMap { $0 }.filter { !$0.isEmpty }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    /// 64pt art tile with a soft drop shadow. Loads the track's `artUrl` async;
    /// falls back to a source glyph while loading, on failure, or when idle.
    private var albumArt: some View {
        let url = hasMeta ? track?.artUrl.flatMap(URL.init(string:)) : nil
        return RoundedRectangle(cornerRadius: Radius.art, style: .continuous)
            .fill(FX.surface3)
            .frame(width: 64, height: 64)
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
            .clipShape(RoundedRectangle(cornerRadius: Radius.art, style: .continuous))
            .shadow(color: .black.opacity(colorScheme == .dark ? 0.4 : 0.15), radius: 8, y: 3)
    }

    private var sourceGlyph: some View {
        Image(systemName: sourceGlyphName(source))
            .font(.title)
            .foregroundStyle(FX.text2)
    }

    // MARK: - Transport

    private var transport: some View {
        HStack(spacing: Space.xxl) {
            TransportButton(systemName: "backward.fill", size: 18, label: "Previous") {
                Haptics.tap()
                Task { await store.sendPlayback(.prev, for: group) }
            }
            PlayPauseButton(group: group, accent: palette.accent)
            TransportButton(systemName: "forward.fill", size: 18, label: "Next") {
                Haptics.tap()
                Task { await store.sendPlayback(.next, for: group) }
            }
        }
        .foregroundStyle(FX.text)
        .frame(maxWidth: .infinity)
        .padding(.top, 2)
    }

    // MARK: - Progress (custom thin scrub bar; preserves FX-32 seek semantics)

    @ViewBuilder
    private var progressBar: some View {
        let duration = Double(track?.durationMs ?? 0)
        if duration > 0 {
            TimelineView(.periodic(from: .now, by: 0.5)) { context in
                // Live interpolated position; while scrubbing we freeze on the
                // user's dragged value so the thumb doesn't fight interpolation.
                let live = interpolatedPosition(at: context.date, duration: duration)
                let pos = scrubbing ? scrubValue : live
                VStack(spacing: 5) {
                    ScrubBar(
                        value: pos,
                        duration: duration,
                        accent: palette.accent,
                        track: palette.trackTint
                    ) {
                        scrubbing = true
                        scrubValue = live
                    } onScrub: { v in
                        scrubValue = v
                    } onCommit: { v in
                        // Commit: seek to the released position. The store
                        // re-bases playback optimistically, then the MQTT echo
                        // confirms and interpolation resumes.
                        Haptics.tap()
                        Task { await store.seek(Int(v), for: group) }
                        scrubbing = false
                    }
                    HStack {
                        Text(fmtTime(pos)).foregroundStyle(FX.text2)
                        Spacer()
                        Text(fmtTime(duration)).foregroundStyle(FX.text2)
                    }
                    .font(.caption2.monospacedDigit())
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
    private var volumeSection: some View {
        let isMulti = group.clients.count > 1
        VStack(spacing: Space.sm) {
            Divider().overlay(FX.line)
            if isMulti {
                GroupVolumeSlider(clients: group.clients, accent: palette.accent)
            }
            ForEach(group.clients) { client in
                DeviceVolumeRow(
                    client: client,
                    showName: isMulti,
                    isHome: client.id == homeId,
                    isMulti: isMulti,
                    accent: palette.accent
                )
            }
        }
    }
}

// MARK: - Scrub bar (thin, native-feeling seek control)

/// A thin progress/scrub bar — capsule track, accent fill, a small thumb that
/// grows while dragging. Reports drag start / move / commit so the parent can
/// freeze position interpolation during a scrub and seek on release.
private struct ScrubBar: View {
    let value: Double
    let duration: Double
    let accent: Color
    let track: Color
    var onStart: () -> Void
    var onScrub: (Double) -> Void
    var onCommit: (Double) -> Void

    @State private var dragging = false

    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width
            let pct = duration > 0 ? min(max(value / duration, 0), 1) : 0
            ZStack(alignment: .leading) {
                Capsule().fill(track).frame(height: 4)
                Capsule().fill(accent).frame(width: w * pct, height: 4)
                Circle()
                    .fill(accent)
                    .frame(width: dragging ? 16 : 11, height: dragging ? 16 : 11)
                    .shadow(color: .black.opacity(0.3), radius: 2, y: 1)
                    .offset(x: w * pct - (dragging ? 8 : 5.5))
            }
            .frame(height: 16)
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { g in
                        if !dragging { dragging = true; onStart() }
                        let p = min(max(g.location.x / w, 0), 1)
                        onScrub(p * duration)
                    }
                    .onEnded { g in
                        let p = min(max(g.location.x / w, 0), 1)
                        dragging = false
                        onCommit(p * duration)
                    }
            )
            .animation(.fxQuick, value: dragging)
        }
        .frame(height: 16)
        .accessibilityElement()
        .accessibilityLabel("Seek")
        .accessibilityValue("\(Int(value / 1000)) of \(Int(duration / 1000)) seconds")
    }
}

// MARK: - Transport buttons

/// Play/pause with optimistic state: flips immediately on tap, then defers to
/// the MQTT `playback` echo. The pending flag clears whenever a fresh playback
/// payload arrives (`updatedAt` changes), mirroring the web MediaCard. Rendered
/// as a filled accent disc — the card's primary action.
private struct PlayPauseButton: View {
    @EnvironmentObject private var store: FauxnosStore
    let group: SpeakerGroup
    let accent: Color
    @State private var pending: Bool?

    private var actualPlaying: Bool { store.playback(for: group)?.isPlaying == true }
    private var displayed: Bool { pending ?? actualPlaying }

    var body: some View {
        Button {
            Haptics.tap()
            pending = !displayed
            Task { await store.sendPlayback(.playpause, for: group) }
        } label: {
            ZStack {
                Circle().fill(accent).frame(width: 52, height: 52)
                Image(systemName: displayed ? "pause.fill" : "play.fill")
                    .font(.title3)
                    .foregroundStyle(contrastOn(accent))
                    .offset(x: displayed ? 0 : 1)   // optical centering of play glyph
            }
            .contentShape(Circle())
        }
        .buttonStyle(.plain)
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
                .font(.system(size: size, weight: .semibold))
                .frame(width: 44, height: 44)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }
}

/// Choose black/white for legibility on top of an arbitrary accent fill.
private func contrastOn(_ color: Color) -> Color {
    let ui = UIColor(color)
    var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
    ui.getRed(&r, green: &g, blue: &b, alpha: &a)
    let luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return luma > 0.6 ? .black : .white
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
                            .foregroundStyle(FX.text2)
                    }
                    ForEach(sources) { s in
                        Button {
                            Haptics.select()
                            Task { await store.switchSource(s.id, in: group) }
                            dismiss()
                        } label: {
                            HStack(spacing: Space.md) {
                                Image(systemName: sourceGlyphName(s.id))
                                    .font(.body)
                                    .frame(width: 26)
                                    .foregroundStyle(active == s.id ? Color.accentColor : FX.text2)
                                Text(s.label?.isEmpty == false ? s.label! : s.id.capitalized)
                                    .foregroundStyle(FX.text)
                                    .fontWeight(active == s.id ? .semibold : .regular)
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
                        Label {
                            Text("Ungroup to use other sources — only Spotify plays across multiple grouped devices.")
                        } icon: {
                            Image(systemName: "info.circle")
                        }
                        .font(.footnote)
                        .foregroundStyle(FX.text2)
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
        .presentationDragIndicator(.visible)
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
    var isHome: Bool = false
    var isMulti: Bool = false
    var accent: Color = FX.text

    @State private var editing = false
    @State private var dragValue: Double = 0
    @State private var lastNonZero: Int = 50

    private var current: Int { store.volume(for: client) }

    /// Non-home members of a multi-room group can be dragged out and ungrouped.
    /// The home member isn't draggable — dragging it would disband the group
    /// (mirrors web, where the home row has no drag/ungroup affordance).
    private var canRegroup: Bool { isMulti && !isHome }

    var body: some View {
        HStack(spacing: Space.sm) {
            if canRegroup {
                Image(systemName: "line.3.horizontal")
                    .font(.footnote).foregroundStyle(FX.text3).frame(width: 14)
                    .draggable(client.id) {
                        Label(client.host.name, systemImage: "hifispeaker.fill")
                            .font(.subheadline).padding(Space.sm)
                            .background(.regularMaterial, in: Capsule())
                    }
                    .accessibilityLabel("Drag \(client.host.name) to another group")
            } else if isMulti {
                // Reserve the grip column so the home row aligns with members.
                Color.clear.frame(width: 14, height: 1)
            }

            if store.isExternalVolume(client.id) {
                Image(systemName: "airplayaudio")
                    .font(.caption).foregroundStyle(FX.text2).frame(width: 20)
                if showName { nameLabel }
                Text("Volume controlled by iPhone")
                    .font(.caption).foregroundStyle(FX.text3)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .lineLimit(1)
            } else {
                Button {
                    Haptics.tap()
                    if current > 0 { lastNonZero = current }
                    let next = current == 0 ? max(lastNonZero, 1) : 0
                    store.publishVolume(next, clientId: client.id)
                } label: {
                    Image(systemName: volumeGlyph(displayValue))
                        .font(.caption).foregroundStyle(FX.text2).frame(width: 20)
                        .contentTransition(.symbolEffect(.replace))
                }
                .buttonStyle(.plain)
                .accessibilityLabel(displayValue == 0 ? "Unmute \(client.host.name)" : "Mute \(client.host.name)")

                if showName { nameLabel }
                Slider(value: binding, in: 0...100) { isEditing in
                    editing = isEditing
                    if isEditing { dragValue = Double(current) }
                }
                .tint(accent)
                .accessibilityLabel("\(client.host.name) volume")
                Text("\(displayValue)")
                    .font(.caption.monospacedDigit()).foregroundStyle(FX.text2)
                    .frame(width: 30, alignment: .trailing)
            }

            if canRegroup {
                Button {
                    Haptics.tap()
                    Task { await store.returnHome(clientId: client.id) }
                } label: {
                    Image(systemName: "rectangle.portrait.and.arrow.right")
                        .font(.caption).foregroundStyle(FX.text2)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Ungroup \(client.host.name)")
            }
        }
    }

    private var nameLabel: some View {
        Text(client.host.name)
            .font(.caption.weight(.medium)).foregroundStyle(FX.text2)
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
    var accent: Color = FX.text

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
        HStack(spacing: Space.sm) {
            Button {
                Haptics.tap()
                toggleMuteAll()
            } label: {
                Image(systemName: volumeGlyph(displayAvg))
                    .font(.caption).foregroundStyle(FX.text2).frame(width: 20)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(displayAvg == 0 ? "Unmute all" : "Mute all")

            Text("All")
                .font(.caption.weight(.semibold)).foregroundStyle(FX.text)
                .frame(width: 96, alignment: .leading)

            Slider(value: binding, in: 0...100) { isEditing in
                editing = isEditing
                if isEditing {
                    baseAvg = avg
                    dragAvg = Double(avg)
                    baseVols = Dictionary(uniqueKeysWithValues: clients.map { ($0.id, store.volume(for: $0)) })
                }
            }
            .tint(accent)
            .accessibilityLabel("All devices volume")

            Text("\(displayAvg)")
                .font(.caption.monospacedDigit()).foregroundStyle(FX.text2)
                .frame(width: 30, alignment: .trailing)
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
