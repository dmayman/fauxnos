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
    @EnvironmentObject private var dragController: CardDragController
    @ObservedObject private var artStore = AlbumArtColorStore.shared
    @Environment(\.colorScheme) private var colorScheme
    let group: SpeakerGroup

    @State private var showSourcePicker = false
    @State private var showDeviceMenu = false
    @State private var scrubbing = false
    @State private var scrubValue: Double = 0

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

    /// This card is the active drop zone for the device currently being lifted.
    private var isDropTarget: Bool { dragController.hoverGroupId == group.id }

    var body: some View {
        VStack(spacing: 0) {
            if showMediaCard {
                if isEmptyMedia { emptyMediaRegion } else { mediaRegion }
            }
            rowsSection
        }
        .background(outerBackground)
        .clipShape(RoundedRectangle(cornerRadius: Radius.card, style: .circular))
        .overlay {
            RoundedRectangle(cornerRadius: Radius.card, style: .circular)
                .strokeBorder(isDropTarget ? FX.text : (hasMedia ? FX.line : FX.lineStrong),
                              lineWidth: isDropTarget ? 2 : 1)
        }
        .shadow(color: .black.opacity(colorScheme == .dark ? 0.4 : 0.07),
                radius: isDropTarget ? 16 : 6, y: isDropTarget ? 7 : 2)
        // Publish this card's frame so a lifted device can hit-test it as a
        // drop zone (collected by GroupsListView into the drag controller).
        .background(
            GeometryReader { geo in
                Color.clear.preference(key: CardFrameKey.self,
                                       value: [group.id: geo.frame(in: .named(kCardSpace))])
            }
        )
        // V2 (single, no media) lifts as a whole — the card IS the device. V3
        // (single + media) instead makes ONLY its device sub-panel draggable (see
        // rowsSection), so the media region isn't a grab target; multi cards lift
        // per row. The press-ramp, detent and drag all live in the LiftToRegroup
        // modifier; it yields to the slider/buttons/source trigger and the ScrollView.
        .liftToRegroup(client: (!isMulti && !showMediaCard) ? clients.first : nil,
                       groupId: group.id, inPlace: true)
        .animation(.fxEase, value: isDropTarget)
        .animation(.fxEase, value: palette)
        .task(id: track?.artUrl) { artStore.ensure(track?.artUrl) }
        // The device menu (group-membership editor) opens from any row's name
        // chevron + the "All" chevron — a bottom sheet rather than the popover
        // the source picker uses, since composing a group is a heavier task.
        .sheet(isPresented: $showDeviceMenu) {
            DeviceMenuSheet(group: group)
        }
    }

    @ViewBuilder
    private var outerBackground: some View {
        if hasMedia { palette.cardTint }       // V1/V3
        else if isEmptyMedia { FX.surface2 }   // V4
        else { FX.surface1 }                   // V2
    }

    // MARK: Media region (V1/V3)

    private var mediaRegion: some View {
        // Figma 2495-4019 lockup: album art + a text column (title, subtitle, then
        // the prev/play/next transport row left-aligned beneath), with the full-
        // width seek bar + flanking timestamps as a separate block 24pt below.
        VStack(alignment: .leading, spacing: Space.xl) {
            HStack(alignment: .center, spacing: Space.lg) {
                albumArt
                VStack(alignment: .leading, spacing: Space.sm) {
                    VStack(alignment: .leading, spacing: 0) {
                        Text(track?.title ?? "—")
                            .font(FxFont.titleTrack).foregroundStyle(FX.text).lineLimit(1)
                        if let sub = trackSubtitle {
                            Text(sub).font(FxFont.metaTrack).foregroundStyle(palette.accent).lineLimit(1)
                        }
                    }
                    if hasControls { transportActions }
                }
                Spacer(minLength: 0)
            }
            if hasControls { progressBar }
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

    // Figma lockup: a full-width seek bar with the start / end times flanking it
    // BELOW the bar (start left, end right), 4pt under the track. The transport
    // row no longer lives here — it sits in the text column above.
    @ViewBuilder
    private var progressBar: some View {
        let duration = Double(track?.durationMs ?? 0)
        if duration > 0 {
            TimelineView(.periodic(from: .now, by: 0.5)) { context in
                let live = interpolatedPosition(at: context.date, duration: duration)
                let pos = scrubbing ? scrubValue : live
                VStack(spacing: Space.xs) {
                    ScrubBar(value: pos, duration: duration, accent: palette.accent, track: palette.trackTint) {
                        scrubbing = true; scrubValue = live
                        dragController.controlsEngaged = true   // claim the touch; don't let the card lift
                    } onScrub: { scrubValue = $0 } onCommit: { v in
                        Haptics.tap(); Task { await store.seek(Int(v), for: group) }
                        scrubbing = false; dragController.controlsEngaged = false
                    }
                    HStack(spacing: 0) {
                        Text(fmtTime(pos)).font(FxFont.timeTrack).monospacedDigit().foregroundStyle(FX.text2)
                        Spacer(minLength: Space.sm)
                        Text(fmtTime(duration)).font(FxFont.timeTrack).monospacedDigit().foregroundStyle(FX.text2)
                    }
                }
            }
        }
    }

    // Left-aligned prev/play/next (Figma: 24pt tap targets, 8pt apart, prev/next
    // 16pt + play 20pt, all in the album accent), sitting under the subtitle.
    private var transportActions: some View {
        HStack(spacing: Space.sm) {
            TransportButton(glyph: .trackPrev, label: "Previous", tint: palette.accent) {
                Haptics.tap(); Task { await store.sendPlayback(.prev, for: group) }
            }
            PlayPauseButton(group: group, tint: palette.accent)
            TransportButton(glyph: .trackNext, label: "Next", tint: palette.accent) {
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
                // Multi-device cards stay NEUTRAL: the rows never adopt the
                // album-art tint (web `.fx-volume.card-v2` is fx-text / fx-line-
                // strong, not the accent), and the "All" master shares the exact
                // same colors as its member rows below — they're set apart by a
                // hairline rule, not a color shift.
                AllRow(clients: clients, accent: FX.text, track: FX.lineStrong,
                       sourceTrigger: AnyView(sourceTrigger),
                       onOpenMenu: { showDeviceMenu = true })
                // Edge-to-edge separator between the "All" master and the member
                // rows (web `.is-all::after` 1px fx-line hairline).
                Rectangle().fill(FX.line).frame(height: 1)
            }
            ForEach(clients) { client in
                let isHomeDevice = client.id == homeId
                DeviceRow(
                    client: client,
                    isHome: isHomeDevice,
                    groupId: group.id,
                    // Multi-device members lift out by row (the home stays put —
                    // pull it out of its own group makes no sense). Single cards
                    // lift at the card level, so their row isn't draggable.
                    draggable: isMulti && !isHomeDevice,
                    nameColor: FX.text,
                    // Multi rows are always neutral (matching the "All" row above);
                    // only single + media cards carry the album accent.
                    accent: isMulti ? FX.text : (hasMedia ? palette.accent : FX.text),
                    track: isMulti ? FX.lineStrong : (hasMedia ? palette.trackTint : FX.surface3),
                    sourceTrigger: (!isMulti && isHomeDevice) ? AnyView(sourceTrigger) : nil,
                    // Single-device cards keep the name chevron → device menu; on a
                    // multi card the rows have no dropdown (the "All" row owns it).
                    onOpenMenu: isMulti ? nil : { showDeviceMenu = true },
                    // On a multi card the home device shows an inline home marker;
                    // every other member gets a trailing unlink (ungroup) button.
                    showHomeIcon: isMulti && isHomeDevice,
                    onUnlink: (isMulti && !isHomeDevice)
                        ? { Haptics.tap(); Task { await store.returnHome(clientId: client.id) } }
                        : nil
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
        // On a single + media card (V3) the device sub-panel is its own draggable
        // entity, with the same lift behaviors as a standalone device card — the
        // media region above is not a grab target. The slot placeholder is tinted
        // with the album color; the float is a synthesized single-device card so
        // the return crossfades (matchesSource: false) rather than hard-swapping.
        .liftToRegroup(client: (!isMulti && showMediaCard) ? clients.first : nil,
                       groupId: group.id, inPlace: true,
                       placeholderTint: palette.placeholderTint, matchesSource: false)
    }

    /// The floating rows panel outline — rounded top corners only; the bottom
    /// stays square because the outer card clipShape rounds the card's bottom.
    private var rowsPanelShape: UnevenRoundedRectangle {
        UnevenRoundedRectangle(
            topLeadingRadius: Radius.inner,
            bottomLeadingRadius: 0,
            bottomTrailingRadius: 0,
            topTrailingRadius: Radius.inner,
            style: .circular
        )
    }

    // MARK: Source trigger (web .fx-source-trigger — icon + chevron, no label)

    private var sourceTrigger: some View {
        Button {
            Haptics.tap(); showSourcePicker = true
        } label: {
            HStack(spacing: Space.xs) {
                TablerIcon(glyph: sourceTablerGlyph(source), size: 22)
                    .foregroundStyle(FX.text)
                // The disclosure chevron is the gray token (FX.text3) — the same
                // gray the name chevrons + old unlink icon use — so every
                // dropdown affordance reads consistently against its primary icon.
                TablerIcon(glyph: .chevronDown, size: 14)
                    .foregroundStyle(FX.text3)
            }
            .frame(height: 40)
            .padding(.horizontal, Space.sm)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Source: \(sourceLabel). Tap to change.")
        // A real popover anchored to the trigger — on a compact iPhone width
        // SwiftUI would auto-adapt `.popover` into a sheet, so we opt back out
        // with `.presentationCompactAdaptation(.popover)`. Picking a source is a
        // single tap; a full-height bottom sheet was too heavy a gesture.
        .popover(isPresented: $showSourcePicker, arrowEdge: .top) {
            SourcePickerPopover(group: group)
                .presentationCompactAdaptation(.popover)
        }
    }

    private var sourceLabel: String {
        guard let s = source else { return "source" }
        if let m = (group.sources ?? []).first(where: { $0.id == s }), let l = m.label, !l.isEmpty { return l }
        return s.capitalized
    }
}

// MARK: - Device-name trigger (web .fx-group-row-name chevron)

/// A row/group title rendered as a tappable disclosure — the label plus a small
/// chevron — that opens the device menu (group-membership editor). Mirrors the
/// web `RowName` chevron; here the whole label + chevron is the tap target. Used
/// by both the "All" master row and each device row.
private struct DeviceNameTrigger: View {
    let label: String
    var color: Color = FX.text
    let action: () -> Void

    var body: some View {
        Button { Haptics.tap(); action() } label: {
            HStack(spacing: Space.xs) {
                Text(label).font(FxFont.nameDevice).foregroundStyle(color).lineLimit(1)
                TablerIcon(glyph: .chevronDown, size: 16).foregroundStyle(FX.text3)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(label). Edit group.")
    }
}

// MARK: - Device row (web .fx-group-row-v2)

struct DeviceRow: View {
    @EnvironmentObject private var store: FauxnosStore
    @EnvironmentObject private var dragController: CardDragController
    let client: SnapClient
    var isHome: Bool = false
    var groupId: String = ""
    var draggable: Bool = false
    var nameColor: Color = FX.text
    var accent: Color = FX.text
    var track: Color = FX.surface3
    var sourceTrigger: AnyView? = nil
    var onOpenMenu: (() -> Void)? = nil
    /// Multi-device home member: shows an inline home glyph after the name.
    var showHomeIcon: Bool = false
    /// Multi-device non-home member: shows a trailing unlink (ungroup) button.
    var onUnlink: (() -> Void)? = nil

    @State private var editing = false
    @State private var dragValue: Double = 0
    @State private var lastNonZero: Int = 50

    private var current: Int { store.volume(for: client) }

    private var deviceName: String { store.displayName(for: client) }

    var body: some View {
        // Two lines: device name (with the source trigger inline on the right)
        // on top, the volume row below — sitting close beneath the name.
        VStack(alignment: .leading, spacing: Space.xs) {
            HStack(spacing: Space.md) {
                HStack(spacing: Space.xs) {
                    name
                    if showHomeIcon {
                        Image("TinyHome")
                            .renderingMode(.template)
                            .resizable().scaledToFit()
                            .frame(width: 10, height: 10)
                            .foregroundStyle(FX.text3)
                    }
                }
                Spacer(minLength: 0)
                if let onUnlink {
                    Button { Haptics.tap(); onUnlink() } label: {
                        TablerIcon(glyph: .unlink, size: 18).foregroundStyle(FX.text3)
                            .frame(width: 32, height: 32)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Remove \(deviceName) from group")
                } else if let sourceTrigger {
                    sourceTrigger
                }
            }
            volume
        }
        // The whole row lifts out into a single-device-card preview (multi-group
        // members only — no drag handle anymore; the row itself is the target).
        // The float is a synthesized card, not a pixel match for the row, so the
        // return crossfades rather than hard-swapping.
        .liftToRegroup(client: draggable ? client : nil, groupId: groupId, inPlace: false,
                       matchesSource: false)
    }

    @ViewBuilder
    private var name: some View {
        if let onOpenMenu {
            DeviceNameTrigger(label: deviceName, color: nameColor, action: onOpenMenu)
        } else {
            Text(deviceName)
                .font(FxFont.nameDevice).foregroundStyle(nameColor).lineLimit(1)
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
                    dragController.controlsEngaged = isEditing   // claim the touch; don't let the row lift
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
    @EnvironmentObject private var dragController: CardDragController
    let clients: [SnapClient]
    var accent: Color = FX.text
    var track: Color = FX.lineStrong
    var sourceTrigger: AnyView
    var onOpenMenu: () -> Void

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
        VStack(alignment: .leading, spacing: Space.xs) {
            HStack(spacing: 6) {
                DeviceNameTrigger(label: "All", color: accent, action: onOpenMenu)
                Spacer(minLength: 0)
                sourceTrigger
            }
            HStack(spacing: Space.md) {
                Button { Haptics.tap(); toggleMuteAll() } label: {
                    VolumeIcon(level: displayAvg, size: 20, tint: FX.text2).frame(width: 22)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(displayAvg == 0 ? "Unmute all" : "Mute all")
                FxSlider(value: binding, fill: accent, track: track) { isEditing in
                    editing = isEditing
                    dragController.controlsEngaged = isEditing   // claim the touch; don't let the card lift
                    if isEditing {
                        baseAvg = avg; dragAvg = Double(avg)
                        baseVols = Dictionary(uniqueKeysWithValues: clients.map { ($0.id, store.volume(for: $0)) })
                    }
                }
                .frame(maxWidth: .infinity)
                .accessibilityLabel("All devices volume")
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
    var tint: Color = FX.text
    @State private var pending: Bool?

    private var actualPlaying: Bool { store.playback(for: group)?.isPlaying == true }
    private var displayed: Bool { pending ?? actualPlaying }

    var body: some View {
        Button {
            Haptics.tap(); pending = !displayed
            Task { await store.sendPlayback(.playpause, for: group) }
        } label: {
            TablerIcon(glyph: displayed ? .pause : .play, size: 20)
                .foregroundStyle(tint)
                .frame(width: 24, height: 24)
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
    var tint: Color = FX.text2
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            TablerIcon(glyph: glyph, size: 16)
                .foregroundStyle(tint)
                .frame(width: 24, height: 24)
                .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }
}

// MARK: - Source picker popover (FX-19)

/// A compact, self-sizing popover for switching the group's source — a single
/// tap, no full-height sheet. Dismisses on selection or on a tap outside (the
/// system popover behavior), so there's no explicit "Done" affordance.
struct SourcePickerPopover: View {
    @EnvironmentObject private var store: FauxnosStore
    @Environment(\.dismiss) private var dismiss
    let group: SpeakerGroup

    private var sources: [Source] { store.availableSources(for: group) }
    private var isMulti: Bool { group.clients.count > 1 }
    private var active: String? { store.currentSource(of: group) }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if sources.isEmpty {
                Text("No sources available")
                    .font(.subheadline).foregroundStyle(FX.text2)
                    .padding(.horizontal, Space.lg).padding(.vertical, Space.md)
            }
            ForEach(sources) { s in
                let isActive = active == s.id
                Button {
                    Haptics.select(); Task { await store.switchSource(s.id, in: group) }; dismiss()
                } label: {
                    HStack(spacing: Space.md) {
                        TablerIcon(glyph: sourceTablerGlyph(s.id), size: 20)
                            .foregroundStyle(isActive ? FX.text : FX.text2)
                            .frame(width: 24)
                        Text(s.label?.isEmpty == false ? s.label! : s.id.capitalized)
                            .font(FxFont.fustat(17, isActive ? .semibold : .medium))
                            .foregroundStyle(isActive ? FX.text : FX.text2)
                        Spacer(minLength: Space.xl)
                        if isActive {
                            Image(systemName: "checkmark").foregroundStyle(FX.text).fontWeight(.semibold)
                        }
                    }
                    .padding(.horizontal, Space.lg).padding(.vertical, Space.md)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
            if isMulti {
                Text("Ungroup to use other sources — only Spotify plays across multiple grouped devices.")
                    .font(.caption).foregroundStyle(FX.text3)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, Space.lg)
                    .padding(.top, Space.sm).padding(.bottom, Space.md)
            }
        }
        .padding(.vertical, Space.sm)
        .frame(minWidth: 240, maxWidth: 280, alignment: .leading)
        .presentationBackground(FX.surface1)
    }
}

// MARK: - Device menu (group-membership editor; web AddDevicesPopover)

/// Bottom-sheet editor for composing / editing a group's membership, opened from
/// any row's name chevron or the "All" chevron. Shows the WHOLE fleet; the home
/// (master) device is pinned checked + locked (it can't leave its own group).
/// Current members come pre-checked and can be toggled off to remove them. The
/// commit button reconciles the chosen set against live state (joins + return-
/// homes). Styled to match the app — FX surfaces, Fustat, Tabler — rather than a
/// stock system list, so it reads like the rest of the UI (web AddDevicesPopover).
struct DeviceMenuSheet: View {
    @EnvironmentObject private var store: FauxnosStore
    @Environment(\.dismiss) private var dismiss
    let group: SpeakerGroup

    @State private var selected: Set<String> = []

    private var home: String? { store.homeClientId(of: group) }
    private var devices: [SnapClient] { store.allClients }
    private var memberIds: Set<String> { Set(group.clients.map(\.id)) }
    private var isGroup: Bool { group.clients.count > 1 }

    /// Home pinned to the top; the rest keep `allClients` name order.
    private var ordered: [SnapClient] {
        guard let home else { return devices }
        return devices.filter { $0.id == home } + devices.filter { $0.id != home }
    }

    private var allSelected: Bool { !devices.isEmpty && selected.count == devices.count }

    /// Dirty = the chosen membership differs from what's live. While still a
    /// single device, also require 1+ pick beyond the home (a one-device "group"
    /// isn't a group).
    private var isDirty: Bool {
        selected != memberIds && (isGroup || selected.count > 1)
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            ScrollView { deviceList }
            footer
        }
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
        .presentationBackground(FX.surface1)
        .onAppear {
            var initial = memberIds
            if let home { initial.insert(home) }
            selected = initial
        }
    }

    private var header: some View {
        HStack {
            Text("Audio group").font(FxFont.fustat(20, .bold)).foregroundStyle(FX.text)
            Spacer(minLength: Space.lg)
            Button {
                Haptics.tap()
                selected = allSelected ? (home.map { [$0] } ?? []) : Set(devices.map(\.id))
            } label: {
                Text(allSelected ? "Select none" : "Select all")
                    .font(FxFont.fustat(15, .semibold)).foregroundStyle(FX.text2)
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, Space.xl)
        .padding(.top, Space.xl).padding(.bottom, Space.lg)
    }

    private var deviceList: some View {
        VStack(spacing: 0) {
            ForEach(ordered) { d in
                let checked = selected.contains(d.id)
                let locked = d.id == home
                Button {
                    guard !locked else { return }
                    Haptics.select()
                    if checked { selected.remove(d.id) } else { selected.insert(d.id) }
                } label: {
                    HStack(spacing: Space.sm) {
                        // Device name matches the source dropdown's type treatment
                        // — same 17pt size, bold weight, primary text color. The
                        // home reads normal (not dimmed); a small light house glyph
                        // to its right marks it as the group's anchor.
                        Text(store.displayName(for: d))
                            .font(FxFont.fustat(17, .bold))
                            .foregroundStyle(FX.text)
                            .lineLimit(1)
                        if locked {
                            TablerIcon(glyph: .home, size: 15)
                                .foregroundStyle(FX.text2)
                        }
                        Spacer(minLength: Space.lg)
                        // Locked (home) checkbox is just a checked box at 60%
                        // opacity — same shape, dimmed — rather than a distinct
                        // locked treatment.
                        checkBox(on: locked ? true : checked, dimmed: locked)
                    }
                    .padding(.horizontal, Space.xl).padding(.vertical, Space.md)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                // NB: no `.disabled(locked)` — that dims the whole row (lightening
                // the name + house and compounding with the checkbox opacity). The
                // home is non-toggleable via the action's early return instead, so
                // its name reads full-strength and only its checkbox sits at 60%.
                .allowsHitTesting(!locked)
            }
        }
        .padding(.bottom, Space.sm)
    }

    private func checkBox(on: Bool, dimmed: Bool) -> some View {
        RoundedRectangle(cornerRadius: 6, style: .continuous)
            .fill(on ? FX.text : .clear)
            .overlay(RoundedRectangle(cornerRadius: 6, style: .continuous)
                .strokeBorder(on ? .clear : FX.lineStrong, lineWidth: 1.5))
            .frame(width: 24, height: 24)
            .overlay {
                if on {
                    Image(systemName: "checkmark").font(.system(size: 12, weight: .bold))
                        .foregroundStyle(FX.surface1)
                }
            }
            .opacity(dimmed ? 0.6 : 1)
    }

    @ViewBuilder
    private var footer: some View {
        Divider().overlay(FX.line)
        Group {
            if isGroup && !isDirty {
                // Existing group, untouched: the only action is to disband it —
                // confirming with just the home returns every member home.
                Button { if let home { confirm([home]) } } label: {
                    HStack(spacing: Space.sm) {
                        TablerIcon(glyph: .unlink, size: 18)
                        Text("Break group").font(FxFont.fustat(17, .semibold))
                    }
                    .foregroundStyle(FX.text)
                    .frame(maxWidth: .infinity).frame(height: 50)
                    .overlay(Capsule().strokeBorder(FX.lineStrong, lineWidth: 1))
                }
                .buttonStyle(.plain)
            } else {
                Button { confirm(selected) } label: {
                    Text(isGroup ? "Update group" : "Create group")
                        .font(FxFont.fustat(17, .bold))
                        .foregroundStyle(isDirty ? FX.surface1 : FX.text3)
                        .frame(maxWidth: .infinity).frame(height: 50)
                        .background(Capsule().fill(isDirty ? FX.text : FX.surface2))
                }
                .buttonStyle(.plain)
                .disabled(!isDirty)
            }
        }
        .padding(.horizontal, Space.xl).padding(.vertical, Space.lg)
    }

    private func confirm(_ ids: Set<String>) {
        guard let home else { return }
        Haptics.tap()
        Task { await store.setGroupMembership(desiredIds: ids, homeClientId: home) }
        dismiss()
    }
}

// MARK: - Previews

#if DEBUG
/// Drops a single card onto the real app ground with list-equivalent padding so
/// the canvas matches how it reads in `GroupsListView`. Seeds a store scoped to
/// just that group's data.
private struct CardPreview: View {
    let group: SpeakerGroup
    var body: some View {
        ScrollView {
            GroupCard(group: group)
                .padding(Space.lg)
        }
        .background(FX.bg.ignoresSafeArea())
        .environmentObject(FauxnosStore.preview(groups: [group]))
        .environmentObject(CardDragController())
    }
}

#Preview("V1 · multi + media") { CardPreview(group: PreviewData.groupV1) }
#Preview("V2 · single, no media") { CardPreview(group: PreviewData.groupV2) }
#Preview("V3 · single + media") { CardPreview(group: PreviewData.groupV3) }
#Preview("V4 · multi, no media") { CardPreview(group: PreviewData.groupV4) }

#Preview("Source picker") {
    SourcePickerPopover(group: PreviewData.groupV1)
        .environmentObject(FauxnosStore.preview())
}
#endif
