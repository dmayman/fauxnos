//
//  GroupCard.swift
//  Fauxnos
//
//  The reusable per-group card, a faithful structural port of the canonical
//  web `GroupCard.jsx` — not a restyle. Four variants, exactly as the web:
//    V1  multi + media   → media region over an accent "All" row + device rows
//    V2  single, no media→ a single device row (name · volume · source-trigger)
//    V3  single + media  → media region over one device row
//    V4  multi, no media → "connect Spotify" zero-state over All + device rows
//
//  The outer card carries the album-art tint; device rows float on it as a
//  surface sub-card. No group-title header, no device-count subtitle, no
//  standalone speaker glyph, no "playing" waveform — the track title is the
//  hero and the device name lives in its row. Iconography is Tabler (matching
//  the web's @tabler/icons-react), the typeface is Fustat.
//
//  All M2 behavior is preserved: optimistic volume + echo-suppression,
//  play/pause MQTT reconciliation, offset-preserving group volume, drag-to-
//  group / return-home, and the FX-32 seek.
//

import SwiftUI

struct GroupCard: View {
    @EnvironmentObject private var store: FauxnosStore
    @ObservedObject private var artStore = AlbumArtColorStore.shared
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    let group: SpeakerGroup

    @State private var showSourcePicker = false
    @State private var dropTargeted = false
    @State private var scrubbing = false
    @State private var scrubValue: Double = 0
    @State private var pressed = false

    // MARK: Derived state (mirrors web GroupCard)

    private var homeId: String? { store.homeClientId(of: group) }
    private var clients: [SnapClient] {
        group.clients.sorted { a, b in
            if a.id == homeId { return true }
            if b.id == homeId { return false }
            return false
        }
    }
    private var track: Track? { store.track(for: group) }
    private var playback: Playback? { store.playback(for: group) }
    private var source: String? { store.currentSource(of: group) }

    private var isMulti: Bool { group.clients.count > 1 }
    private var hasMedia: Bool { track?.hasMeta == true }
    private var showMediaCard: Bool { hasMedia || isMulti }   // V1/V3/V4
    private var isEmptyMedia: Bool { isMulti && !hasMedia }    // V4 zero-state
    private var hasControls: Bool { source == "spotify" && hasMedia }

    private var palette: ArtPalette {
        guard hasMedia, let raw = artStore.color(for: track?.artUrl) else { return .neutral }
        return buildArtPalette(from: raw, dark: colorScheme == .dark)
    }

    private var groupName: String {
        if let name = group.name, !name.isEmpty { return name }
        if let home = homeId, let c = group.clients.first(where: { $0.id == home }) {
            return store.displayName(for: c)
        }
        return group.clients.first.map { store.displayName(for: $0) } ?? group.id
    }

    // MARK: Body

    var body: some View {
        VStack(spacing: 0) {
            if showMediaCard {
                if isEmptyMedia { emptyMediaRegion } else { mediaRegion }
            }
            rowsSection
        }
        .background(outerBackground)
        .clipShape(RoundedRectangle(cornerRadius: Radius.card, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: Radius.card, style: .continuous)
                .strokeBorder(dropTargeted ? FX.text : (hasMedia ? FX.line : FX.lineStrong),
                              lineWidth: dropTargeted ? 2 : 1)
        }
        .shadow(color: .black.opacity(colorScheme == .dark ? 0.4 : 0.07),
                radius: dropTargeted ? 16 : 6, y: dropTargeted ? 7 : 2)
        .scaleEffect((pressed && !reduceMotion) ? 0.97 : 1)
        .animation(.fxPress, value: pressed)
        // Springy card press (FX-57): the whole card dips on touch-down and
        // settles with a bouncy release, the signature "live, tactile control"
        // cue. A long-press gesture (with an effectively-never-firing perform)
        // gives clean press-down/up callbacks while cooperating with the
        // enclosing ScrollView — moving past `maximumDistance` fails the
        // gesture so a scroll takes over and the card pops back. SwiftUI's
        // descendant-gesture priority keeps the volume slider, scrub bar,
        // transport / mute buttons, source trigger, and the row's `.draggable`
        // drag-to-group winning in their own regions, so a press there does NOT
        // scale the card (the web's `closest(controls)` opt-out). Honors
        // reduce-motion (no scale, mirroring `@media (prefers-reduced-motion)`).
        .onLongPressGesture(minimumDuration: 9999, maximumDistance: 12) {
            // perform — unreachable in practice; press/release runs below.
        } onPressingChanged: { isPressing in
            if isPressing, !pressed { Haptics.lift() }
            pressed = isPressing
        }
        .dropDestination(for: String.self) { items, _ in
            guard let dropped = items.first else { return false }
            Haptics.success()
            Task { await store.joinGroup(clientId: dropped, targetHomeClientId: homeId ?? group.id) }
            return true
        } isTargeted: { targeted in
            if targeted, !dropTargeted { Haptics.tap() }
            dropTargeted = targeted
        }
        .animation(.fxEase, value: dropTargeted)
        .animation(.fxEase, value: palette)
        .task(id: track?.artUrl) { artStore.ensure(track?.artUrl) }
        .sheet(isPresented: $showSourcePicker) { SourcePickerSheet(group: group) }
    }

    @ViewBuilder
    private var outerBackground: some View {
        if hasMedia { palette.cardTint }       // V1/V3
        else if isEmptyMedia { FX.surface2 }   // V4
        else { FX.surface1 }                   // V2
    }

    // MARK: Media region (V1/V3)

    private var mediaRegion: some View {
        VStack(alignment: .leading, spacing: Space.lg) {
            HStack(alignment: .center, spacing: Space.lg) {
                albumArt
                VStack(alignment: .leading, spacing: Space.xs) {
                    Text(track?.title ?? "—")
                        .font(FxFont.titleTrack).foregroundStyle(FX.text).lineLimit(1)
                    if let sub = trackSubtitle {
                        Text(sub).font(FxFont.metaTrack).foregroundStyle(palette.accent).lineLimit(1)
                    }
                }
                Spacer(minLength: 0)
            }
            if hasControls { progressAndTransport }
        }
        .padding(Space.xl)
    }

    private var emptyMediaRegion: some View {
        HStack(spacing: Space.lg) {
            RoundedRectangle(cornerRadius: Radius.art, style: .continuous)
                .fill(FX.surface1)
                .frame(width: 120, height: 120)
                .overlay { TablerIcon(glyph: .brandSpotify, size: 48).foregroundStyle(FX.text3).opacity(0.35) }
            Text("Connect to \(groupName) in Spotify")
                .font(FxFont.emptyCta).foregroundStyle(FX.text2).lineLimit(2)
            Spacer(minLength: 0)
        }
        .padding(Space.xl)
    }

    private var trackSubtitle: String? {
        let parts = [track?.artist, track?.album].compactMap { $0 }.filter { !$0.isEmpty }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    /// 100pt cover — the web mweb `.fx-group-media-art` (desktop 150, ≤600px 100).
    private var albumArt: some View {
        let url = hasMedia ? track?.artUrl.flatMap(URL.init(string:)) : nil
        return RoundedRectangle(cornerRadius: Radius.art, style: .continuous)
            .fill(FX.surface2)
            .frame(width: 100, height: 100)
            .overlay {
                if let url {
                    AsyncImage(url: url) { phase in
                        if case .success(let image) = phase { image.resizable().scaledToFill() }
                        else { sourceGlyph }
                    }
                } else { sourceGlyph }
            }
            .clipShape(RoundedRectangle(cornerRadius: Radius.art, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: Radius.art, style: .continuous).strokeBorder(FX.line, lineWidth: 1))
            .shadow(color: .black.opacity(colorScheme == .dark ? 0.45 : 0.12), radius: 10, y: 4)
    }

    private var sourceGlyph: some View {
        TablerIcon(glyph: sourceTablerGlyph(source), size: 44).foregroundStyle(FX.text3)
    }

    // MARK: Progress + inline transport (web .fx-group-progress)

    // Phone media layout (FX-58): mirrors the web mweb `.fx-group-progress`
    // (flex-direction: column) — the seek bar runs edge-to-edge with the start
    // / end times flanking it, and the transport row centers beneath, rather
    // than the desktop one-line "time–bar–time–prev/play/next" cram.
    @ViewBuilder
    private var progressAndTransport: some View {
        let duration = Double(track?.durationMs ?? 0)
        if duration > 0 {
            TimelineView(.periodic(from: .now, by: 0.5)) { context in
                let live = interpolatedPosition(at: context.date, duration: duration)
                let pos = scrubbing ? scrubValue : live
                VStack(spacing: Space.sm) {
                    HStack(spacing: Space.md) {
                        Text(fmtTime(pos)).font(FxFont.timeTrack).monospacedDigit().foregroundStyle(FX.text2)
                        ScrubBar(value: pos, duration: duration, accent: palette.accent, track: palette.trackTint) {
                            scrubbing = true; scrubValue = live
                        } onScrub: { scrubValue = $0 } onCommit: { v in
                            Haptics.tap(); Task { await store.seek(Int(v), for: group) }; scrubbing = false
                        }
                        Text(fmtTime(duration)).font(FxFont.timeTrack).monospacedDigit().foregroundStyle(FX.text2)
                    }
                    transportActions   // centered beneath (web .fx-group-progress-actions align-self: center)
                }
            }
        }
    }

    private var transportActions: some View {
        HStack(spacing: Space.xs) {
            TransportButton(glyph: .trackPrev, label: "Previous") {
                Haptics.tap(); Task { await store.sendPlayback(.prev, for: group) }
            }
            PlayPauseButton(group: group)
            TransportButton(glyph: .trackNext, label: "Next") {
                Haptics.tap(); Task { await store.sendPlayback(.next, for: group) }
            }
        }
    }

    private func interpolatedPosition(at now: Date, duration: Double) -> Double {
        guard let pb = playback else { return 0 }
        let base = Double(pb.positionMs ?? 0)
        guard pb.isPlaying == true else { return min(base, duration) }
        let t0 = pb.updatedAt ?? (now.timeIntervalSince1970 * 1000)
        return min(max(base + (now.timeIntervalSince1970 * 1000) - t0, 0), duration)
    }

    private func fmtTime(_ ms: Double) -> String {
        let total = Int(max(ms, 0) / 1000)
        return String(format: "%d:%02d", total / 60, total % 60)
    }

    // MARK: Rows section (floating sub-card under media, or the whole V2 body)

    private var rowsSection: some View {
        VStack(spacing: Space.lg) {
            if isMulti {
                AllRow(clients: clients, accent: palette.accent,
                       sourceTrigger: AnyView(sourceTrigger), homeId: homeId)
            }
            ForEach(clients) { client in
                DeviceRow(
                    client: client,
                    isHome: client.id == homeId,
                    isMulti: isMulti,
                    nameColor: isMulti ? FX.text2 : FX.text,
                    accent: hasMedia ? palette.accent : FX.text,
                    track: hasMedia ? palette.trackTint : FX.surface3,
                    sourceTrigger: (!isMulti && client.id == homeId) ? AnyView(sourceTrigger) : nil
                )
            }
        }
        .padding(.horizontal, Space.xl)
        .padding(.top, Space.lg)
        .padding(.bottom, showMediaCard ? Space.xl : Space.lg)
        .frame(maxWidth: .infinity, alignment: .leading)
        // Floating rows sub-card (FX-59): on media cards (V1/V3/V4) the rows read
        // as a surface floating on the album-art tint — innerSurface fill, rounded
        // TOP corners curving up into the media above, and a soft lift shadow
        // (web `.fx-group-rows` border-radius + box-shadow). The outer card's
        // clipShape keeps the panel's sides/bottom flush, so the hairline is
        // top-only (web `border-top`), masked off the sides/bottom to avoid
        // doubling the outer card border. V2 (no media) keeps a plain body.
        .background {
            if showMediaCard {
                rowsPanelShape
                    .fill(palette.innerSurface)
                    .shadow(color: .black.opacity(colorScheme == .dark ? 0.28 : 0.08), radius: 6, y: 4)
            }
        }
        .overlay {
            if showMediaCard {
                rowsPanelShape
                    .strokeBorder(FX.lineStrong, lineWidth: 1)
                    .mask(alignment: .top) {
                        Rectangle()
                            .frame(height: Radius.inner + 2)
                            .frame(maxHeight: .infinity, alignment: .top)
                    }
            }
        }
    }

    /// The floating rows panel outline — rounded top corners only; the bottom
    /// stays square because the outer card clipShape rounds the card's bottom.
    private var rowsPanelShape: UnevenRoundedRectangle {
        UnevenRoundedRectangle(
            topLeadingRadius: Radius.inner,
            bottomLeadingRadius: 0,
            bottomTrailingRadius: 0,
            topTrailingRadius: Radius.inner,
            style: .continuous
        )
    }

    // MARK: Source trigger (web .fx-source-trigger — icon + chevron, no label)

    private var sourceTrigger: some View {
        Button {
            Haptics.tap(); showSourcePicker = true
        } label: {
            HStack(spacing: Space.xs) {
                TablerIcon(glyph: sourceTablerGlyph(source), size: 22)
                TablerIcon(glyph: .chevronDown, size: 14)
            }
            .foregroundStyle(FX.text)
            .frame(height: 40)
            .padding(.horizontal, Space.sm)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Source: \(sourceLabel). Tap to change.")
    }

    private var sourceLabel: String {
        guard let s = source else { return "source" }
        if let m = (group.sources ?? []).first(where: { $0.id == s }), let l = m.label, !l.isEmpty { return l }
        return s.capitalized
    }
}

// MARK: - Device row (web .fx-group-row-v2)

struct DeviceRow: View {
    @EnvironmentObject private var store: FauxnosStore
    let client: SnapClient
    var isHome: Bool = false
    var isMulti: Bool = false
    var nameColor: Color = FX.text
    var accent: Color = FX.text
    var track: Color = FX.surface3
    var sourceTrigger: AnyView? = nil

    @State private var editing = false
    @State private var dragValue: Double = 0
    @State private var lastNonZero: Int = 50

    private var current: Int { store.volume(for: client) }
    private var canRegroup: Bool { isMulti && !isHome }

    private var deviceName: String { store.displayName(for: client) }

    var body: some View {
        // Two lines: device name on top, controls (volume + source) below.
        VStack(alignment: .leading, spacing: Space.sm) {
            name
            HStack(spacing: Space.md) {
                volume
                if let sourceTrigger { sourceTrigger }
            }
        }
    }

    @ViewBuilder
    private var name: some View {
        let label = Text(deviceName)
            .font(FxFont.nameDevice).foregroundStyle(nameColor).lineLimit(1)

        if canRegroup {
            HStack(spacing: 6) {
                Image(systemName: "line.3.horizontal").font(.caption2).foregroundStyle(FX.text3)
                label
            }
            .draggable(client.id) {
                Label(deviceName, systemImage: "hifispeaker.fill")
                    .font(.subheadline).padding(Space.sm).background(.regularMaterial, in: Capsule())
            }
            .accessibilityLabel("Drag \(deviceName) to another group")
        } else {
            label
        }
    }

    @ViewBuilder
    private var volume: some View {
        if store.isExternalVolume(client.id) {
            HStack(spacing: Space.sm) {
                TablerIcon(glyph: .broadcastTower, size: 16).foregroundStyle(FX.text2)
                Text("Volume controlled by iPhone").font(.caption).foregroundStyle(FX.text3).lineLimit(1)
                Spacer(minLength: 0)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        } else {
            HStack(spacing: Space.md) {
                Button {
                    Haptics.tap()
                    if current > 0 { lastNonZero = current }
                    store.publishVolume(current == 0 ? max(lastNonZero, 1) : 0, clientId: client.id)
                } label: {
                    VolumeIcon(level: displayValue, size: 20, tint: FX.text2).frame(width: 22)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(displayValue == 0 ? "Unmute \(deviceName)" : "Mute \(deviceName)")

                FxSlider(value: binding, fill: accent, track: track) { isEditing in
                    editing = isEditing
                    if isEditing { dragValue = Double(current) }
                }
                .frame(maxWidth: .infinity)
                .accessibilityLabel("\(deviceName) volume")
                .accessibilityValue("\(displayValue) percent")
            }
        }
    }

    private var displayValue: Int { editing ? Int(dragValue.rounded()) : current }

    private var binding: Binding<Double> {
        Binding(
            get: { editing ? dragValue : Double(current) },
            set: { newVal in dragValue = newVal; store.publishVolume(Int(newVal.rounded()), clientId: client.id) }
        )
    }
}

// MARK: - "All" row (web .fx-group-row-v2.is-all)

struct AllRow: View {
    @EnvironmentObject private var store: FauxnosStore
    let clients: [SnapClient]
    var accent: Color = FX.text
    var sourceTrigger: AnyView
    var homeId: String?

    @State private var editing = false
    @State private var dragAvg: Double = 0
    @State private var baseAvg: Int = 0
    @State private var baseVols: [String: Int] = [:]
    @State private var preMute: [String: Int]?

    private var avg: Int {
        guard !clients.isEmpty else { return 0 }
        return Int((Double(clients.reduce(0) { $0 + store.volume(for: $1) }) / Double(clients.count)).rounded())
    }
    private var displayAvg: Int { editing ? Int(dragAvg.rounded()) : avg }

    var body: some View {
        VStack(alignment: .leading, spacing: Space.sm) {
            HStack(spacing: 6) {
                Text("All").font(FxFont.nameDevice).foregroundStyle(accent)
                Button {
                    Haptics.tap()
                    for c in clients where c.id != homeId { Task { await store.returnHome(clientId: c.id) } }
                } label: {
                    TablerIcon(glyph: .unlink, size: 15).foregroundStyle(FX.text3)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Ungroup all")
            }
            HStack(spacing: Space.md) {
                Button { Haptics.tap(); toggleMuteAll() } label: {
                    VolumeIcon(level: displayAvg, size: 20, tint: FX.text2).frame(width: 22)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(displayAvg == 0 ? "Unmute all" : "Mute all")
                FxSlider(value: binding, fill: accent, track: accent.opacity(0.18)) { isEditing in
                    editing = isEditing
                    if isEditing {
                        baseAvg = avg; dragAvg = Double(avg)
                        baseVols = Dictionary(uniqueKeysWithValues: clients.map { ($0.id, store.volume(for: $0)) })
                    }
                }
                .frame(maxWidth: .infinity)
                .accessibilityLabel("All devices volume")
                sourceTrigger
            }
        }
    }

    private var binding: Binding<Double> {
        Binding(
            get: { editing ? dragAvg : Double(avg) },
            set: { newVal in
                dragAvg = newVal
                let delta = Int(newVal.rounded()) - baseAvg
                for c in clients { store.publishVolume((baseVols[c.id] ?? store.volume(for: c)) + delta, clientId: c.id) }
            }
        )
    }

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

// MARK: - FxSlider (web .fx-volume — thin track, accent fill, dot thumb)

struct FxSlider: View {
    @Binding var value: Double          // 0…100
    var fill: Color
    var track: Color
    var onEditingChanged: (Bool) -> Void
    @State private var dragging = false

    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width
            let pct = CGFloat(min(max(value, 0), 100)) / 100
            ZStack(alignment: .leading) {
                Capsule().fill(track).frame(height: 6)
                Capsule().fill(fill).frame(width: max(6, w * pct), height: 6)
                // Touch-reveal thumb (FX-60): hidden at rest so a resting card
                // reads as a clean fill bar (web `.fx-volume.card-v2 .fx-volume-
                // thumb { opacity: 0 }`); fades + grows in while dragging (the
                // touch analog of the web's hover/active reveal). The contentShape
                // Rectangle below keeps the full-height drag target regardless.
                Circle().fill(fill).frame(width: 14, height: 14)
                    .shadow(color: .black.opacity(0.22), radius: 1.5, y: 1)
                    .offset(x: min(max(0, w * pct - 7), w - 14))
                    .scaleEffect(dragging ? 1.25 : 0.5)
                    .opacity(dragging ? 1 : 0)
                // Live % bubble (FX-60 nicety): floats above the thumb while
                // dragging, fades out on release. Non-interactive so it never
                // intercepts the drag. Center clamped to stay within the track.
                Text("\(Int(value.rounded()))%")
                    .font(.caption2.weight(.semibold)).monospacedDigit()
                    .foregroundStyle(FX.text)
                    .padding(.horizontal, 7).padding(.vertical, 3)
                    .background(.regularMaterial, in: Capsule())
                    .shadow(color: .black.opacity(0.18), radius: 3, y: 1)
                    .fixedSize()
                    .position(x: min(max(w * pct, 7), w - 7), y: -16)
                    .opacity(dragging ? 1 : 0)
                    .scaleEffect(dragging ? 1 : 0.8, anchor: .bottom)
                    .allowsHitTesting(false)
            }
            .frame(height: 28)
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { g in
                        if !dragging { dragging = true; onEditingChanged(true) }
                        value = Double(min(max(g.location.x / w, 0), 1)) * 100
                    }
                    .onEnded { _ in dragging = false; onEditingChanged(false) }
            )
            .animation(.fxQuick, value: dragging)
        }
        .frame(height: 28)
    }
}

// MARK: - Scrub bar (progress; web .fx-group-progress-track)

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
                Capsule().fill(track).frame(height: 6)
                Capsule().fill(accent).frame(width: max(0, w * pct), height: 6)
                // Touch-reveal scrub thumb (FX-60): hidden at rest (web
                // `.fx-group-progress-thumb { opacity: 0 }`), fades + grows in
                // while scrubbing. Fixed 16pt frame so the offset math is stable;
                // reveal is driven by scale + opacity. Hit target stays full-width.
                Circle().fill(accent).frame(width: 16, height: 16)
                    .shadow(color: .black.opacity(0.25), radius: 2, y: 1)
                    .offset(x: min(max(0, w * pct - 8), w - 16))
                    .scaleEffect(dragging ? 1 : 0.5)
                    .opacity(dragging ? 1 : 0)
            }
            .frame(height: 22)
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { g in
                        if !dragging { dragging = true; onStart() }
                        onScrub(min(max(g.location.x / w, 0), 1) * duration)
                    }
                    .onEnded { g in
                        dragging = false
                        onCommit(min(max(g.location.x / w, 0), 1) * duration)
                    }
            )
            .animation(.fxQuick, value: dragging)
        }
        .frame(height: 22)
        .accessibilityElement()
        .accessibilityLabel("Seek")
    }
}

// MARK: - Transport buttons (web .fx-group-progress-actions — 32pt icon-btn)

private struct PlayPauseButton: View {
    @EnvironmentObject private var store: FauxnosStore
    let group: SpeakerGroup
    @State private var pending: Bool?

    private var actualPlaying: Bool { store.playback(for: group)?.isPlaying == true }
    private var displayed: Bool { pending ?? actualPlaying }

    var body: some View {
        Button {
            Haptics.tap(); pending = !displayed
            Task { await store.sendPlayback(.playpause, for: group) }
        } label: {
            TablerIcon(glyph: displayed ? .pause : .play, size: 20)
                .foregroundStyle(FX.text)
                .frame(width: 32, height: 32)
                .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(displayed ? "Pause" : "Play")
        .onChange(of: store.playback(for: group)?.updatedAt) { _, _ in pending = nil }
    }
}

private struct TransportButton: View {
    let glyph: TablerIcon.Glyph
    let label: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            TablerIcon(glyph: glyph, size: 17)
                .foregroundStyle(FX.text2)
                .frame(width: 32, height: 32)
                .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }
}

// MARK: - Source picker sheet (FX-19)

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
                        Text("No sources available").foregroundStyle(FX.text2)
                    }
                    ForEach(sources) { s in
                        Button {
                            Haptics.select(); Task { await store.switchSource(s.id, in: group) }; dismiss()
                        } label: {
                            HStack(spacing: Space.md) {
                                TablerIcon(glyph: sourceTablerGlyph(s.id), size: 22)
                                    .foregroundStyle(active == s.id ? Color.accentColor : FX.text2)
                                    .frame(width: 26)
                                Text(s.label?.isEmpty == false ? s.label! : s.id.capitalized)
                                    .foregroundStyle(FX.text)
                                    .fontWeight(active == s.id ? .semibold : .regular)
                                Spacer()
                                if active == s.id {
                                    Image(systemName: "checkmark").foregroundStyle(.tint).fontWeight(.semibold)
                                }
                            }
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }
                }
                if isMulti {
                    Section {
                        Label("Ungroup to use other sources — only Spotify plays across multiple grouped devices.",
                              systemImage: "info.circle")
                            .font(.footnote).foregroundStyle(FX.text2)
                    }
                }
            }
            .navigationTitle("Source")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
    }
}
