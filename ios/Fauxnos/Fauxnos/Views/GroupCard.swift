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
    @ObservedObject private var dev = DevControl.shared   // FX-77 backdrop tuning
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
    // Spotify is the only source with a media player — other sources (AirPlay,
    // Vinyl, Alexa, …) are local-per-device and carry no track metadata, so they
    // render as a plain device card (V2) rather than the album-art media lockup.
    private var hasMedia: Bool { source == "spotify" && track?.hasMeta == true }
    private var showMediaCard: Bool { hasMedia || isMulti }   // V1/V3/V4
    private var isEmptyMedia: Bool { isMulti && !hasMedia }    // V4 zero-state
    private var hasControls: Bool { source == "spotify" && hasMedia }

    private var palette: ArtPalette {
        guard hasMedia, let raw = artStore.color(for: track?.artUrl) else { return .neutral }
        return buildArtPalette(from: raw, dark: colorScheme == .dark)
    }

    /// FX-77: dev-tuning keys are mode-scoped (`<base>.dark` / `<base>.light`).
    private var modeKey: String { colorScheme == .dark ? "dark" : "light" }

    // On a tinted media card a fixed neutral gray (text2/text3) reads muddy over
    // the album tint, so the card's secondary "grays" become an ink that tracks
    // the appearance instead. Dark mode blends ADDITIVELY (see `.mediaMuted`), so
    // it wants a lower opacity than light mode's flat composite.
    // ── FINE-TUNE THESE TWO OPACITIES ──
    private var mediaInkDarkOpacity: CGFloat { 0.45 }   // additive white over the tint
    private var mediaInkLightOpacity: CGFloat { 0.60 }  // flat black over the tint
    private var mediaInk: Color {
        colorScheme == .dark ? .white.opacity(mediaInkDarkOpacity)
                             : .black.opacity(mediaInkLightOpacity)
    }
    /// Use the additive blend only where the ink actually sits on the album tint.
    private var mediaAdditive: Bool { hasMedia && colorScheme == .dark }
    private var muted: Color { hasMedia ? mediaInk : FX.text2 }   // secondary grays
    private var faint: Color { hasMedia ? mediaInk : FX.text3 }   // tertiary grays

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
            // The whole card is the drop hit-area, but the white drop indicator
            // only outlines the device-card (rows) portion when there's a media /
            // rows sub-panel (V1/V3/V4) — that stroke is drawn on the panel in
            // `rowsSection`. A plain single-device card (V2) has no sub-panel, so
            // its drop indicator stays the full-card stroke.
            let dropOnWholeCard = isDropTarget && !showMediaCard
            RoundedRectangle(cornerRadius: Radius.card, style: .circular)
                .strokeBorder(dropOnWholeCard ? FX.text : (hasMedia ? FX.line : FX.lineStrong),
                              lineWidth: dropOnWholeCard ? 2 : 1)
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
        // FX-79: melt the album-derived colors (card tint, accent, slider/track
        // tints) from old to new — a smooth fade rather than a spring snap, so
        // the whole card's color shifts gracefully when the cover changes. The
        // palette updates a beat after the flip (it waits on async color
        // extraction of the new cover), so the tint settles in just behind it.
        .animation(.easeInOut(duration: 0.5), value: palette)
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
        // FX-77: on a media card the tint goes translucent (default 1.0 = opaque,
        // unchanged) so the blurred album backdrop behind the list shows through.
        // Idle / empty cards stay solid — the backdrop only renders while playing.
        if hasMedia { palette.cardTint.opacity(dev.d("media.opacity.\(modeKey)", colorScheme == .dark ? 0.4 : 0.66)) }  // V1/V3
        else if isEmptyMedia { FX.surface2 }   // V4
        else { FX.surface1 }                   // V2
    }

    // MARK: Media region (V1/V3)

    private var mediaRegion: some View {
        // Figma 2495-4019 lockup: album art + a text column (title, subtitle, then
        // the prev/play/next transport row left-aligned beneath), with the full-
        // width seek bar + flanking timestamps as a separate block 24pt below.
        VStack(alignment: .leading, spacing: Space.md) {
            HStack(alignment: .center, spacing: Space.lg) {
                albumArt
                VStack(alignment: .leading, spacing: Space.sm) {
                    // FX-79: title + artist cross-fade and slide top-to-bottom on a
                    // track change, cascaded (title leads, artist follows a beat
                    // later). Each line keys on its own text, so it transitions once
                    // per genuine change and not on poll refreshes.
                    VStack(alignment: .leading, spacing: 0) {
                        NowPlayingText(text: track?.title ?? "—", font: FxFont.titleTrack, color: FX.text)
                        if let sub = trackSubtitle {
                            NowPlayingText(text: sub, font: FxFont.metaTrack, color: palette.accent, delay: 0.08)
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

    /// 100pt cover — the web `.fx-group-media-art` (desktop 150, ≤600px 100).
    /// FX-79: a `FlippingAlbumArt` that 3D-flips to the incoming cover on a track
    /// change (keyed internally on the art URL), revealing the new art on its
    /// back face. The source glyph is the no-cover fallback, exactly as before.
    private var albumArt: some View {
        FlippingAlbumArt(
            artURL: hasMedia ? track?.artUrl : nil,
            size: 100,
            cornerRadius: Radius.art,
            borderColor: FX.line,
            shadow: (.black.opacity(colorScheme == .dark ? 0.45 : 0.12), 10, 4),
            placeholder: AnyView(sourceGlyph)
        )
    }

    private var sourceGlyph: some View {
        SourceIcon(icon: currentSourceObject?.icon, sourceId: source, size: 44)
            .mediaMuted(faint, additive: mediaAdditive)
    }

    /// The current source's full object (for its custom icon), looked up in the
    /// group's enriched sources by the active source id.
    private var currentSourceObject: Source? {
        group.sources?.first { $0.id == source }
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
                VStack(spacing: 2) {
                    ScrubBar(value: pos, duration: duration, accent: palette.accent, track: palette.trackTint) {
                        scrubbing = true; scrubValue = live
                        dragController.controlsEngaged = true   // claim the touch; don't let the card lift
                    } onScrub: { scrubValue = $0 } onCommit: { v in
                        Haptics.tap(); Task { await store.seek(Int(v), for: group) }
                        scrubbing = false; dragController.controlsEngaged = false
                    }
                    HStack(spacing: 0) {
                        Text(fmtTime(pos)).font(FxFont.timeTrack).monospacedDigit().mediaMuted(muted, additive: mediaAdditive)
                        Spacer(minLength: Space.sm)
                        Text(fmtTime(duration)).font(FxFont.timeTrack).monospacedDigit().mediaMuted(muted, additive: mediaAdditive)
                    }
                }
            }
        }
    }

    // Left-aligned prev/play/next (Figma: 24pt tap targets, 8pt apart, prev/next
    // 16pt + play 20pt, all in the album accent), sitting under the subtitle.
    private var transportActions: some View {
        HStack(spacing: Space.sm) {
            TransportButton(asset: "MediaPrev", label: "Previous", tint: palette.accent) {
                Task { await store.sendPlayback(.prev, for: group) }
            }
            PlayPauseButton(group: group, tint: palette.accent)
            TransportButton(asset: "MediaNext", label: "Next", tint: palette.accent) {
                Task { await store.sendPlayback(.next, for: group) }
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
                AllRow(clients: clients, accent: FX.text, track: FX.lineStrong, iconTint: muted,
                       additive: mediaAdditive,
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
                    // Every card's slider is neutral now — no album accent on the
                    // fill (matching the "All" row). Track is the translucent
                    // line-strong on any media card (it sits on a tint), or the
                    // solid neutral surface on a plain single-device card.
                    accent: FX.text,
                    track: showMediaCard ? FX.lineStrong : FX.surface3,
                    iconTint: muted,
                    faintTint: faint,
                    additive: mediaAdditive,
                    sourceTrigger: (!isMulti && isHomeDevice) ? AnyView(sourceTrigger) : nil,
                    // Single-device cards keep the name chevron → device menu; on a
                    // multi card the rows have no dropdown (the "All" row owns it).
                    onOpenMenu: isMulti ? nil : { showDeviceMenu = true },
                    // Non-home members get a trailing unlink (ungroup) button; the
                    // home member has no trailing affordance in the list.
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
                // FX-77: device sub-card fill also goes translucent (default 1.0)
                // so the backdrop reads through it independently of the outer tint.
                rowsPanelShape
                    .fill(palette.innerSurface.opacity(dev.d("device.opacity.\(modeKey)", colorScheme == .dark ? 0.29 : 1.0)))
                    .shadow(color: .black.opacity(colorScheme == .dark ? 0.28 : 0.08), radius: 6, y: 4)
            }
        }
        .overlay {
            if showMediaCard {
                // Full-perimeter outline for the device sub-card (top divider +
                // sides + rounded bottom), so its bottom/sides read at the SAME
                // strength as the top divider. Previously only the top was stroked
                // and the bottom/sides leaned on the lighter outer card border
                // (FX.line over the album tint), which made the bottom look faint.
                // Drop state swaps to the bright white indicator.
                rowsDropShape.strokeBorder(isDropTarget ? FX.text : FX.lineStrong,
                                           lineWidth: isDropTarget ? 2 : 1)
            }
        }
        // On a single + media card (V3) the device sub-panel is its own draggable
        // entity, with the same lift behaviors as a standalone device card — the
        // media region above is not a grab target. The slot placeholder is an
        // adaptive translucent neutral (see CardDrag.placeholder); the float is a
        // synthesized single-device card so the return crossfades
        // (matchesSource: false) rather than hard-swapping.
        .liftToRegroup(client: (!isMulti && showMediaCard) ? clients.first : nil,
                       groupId: group.id, inPlace: true, matchesSource: false)
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

    /// Drop-indicator outline for the rows portion: like `rowsPanelShape` but its
    /// bottom corners match the outer card radius so the white stroke hugs the
    /// card's rounded bottom instead of being clipped square.
    private var rowsDropShape: UnevenRoundedRectangle {
        UnevenRoundedRectangle(
            topLeadingRadius: Radius.inner,
            bottomLeadingRadius: Radius.card,
            bottomTrailingRadius: Radius.card,
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
                SourceIcon(icon: currentSourceObject?.icon, sourceId: source, size: 22)
                    .foregroundStyle(FX.text)
                // The disclosure chevron is the gray token (FX.text3) — the same
                // gray the name chevrons + old unlink icon use — so every
                // dropdown affordance reads consistently against its primary icon.
                TablerIcon(glyph: .chevronDown, size: 14)
                    .mediaMuted(faint, additive: mediaAdditive)
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
    var chevronColor: Color = FX.text3
    var additiveChevron: Bool = false
    let action: () -> Void

    var body: some View {
        Button { Haptics.tap(); action() } label: {
            HStack(spacing: Space.xs) {
                Text(label).font(FxFont.nameDevice).foregroundStyle(color).lineLimit(1)
                TablerIcon(glyph: .chevronDown, size: 16).mediaMuted(chevronColor, additive: additiveChevron)
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
    /// Secondary "gray" (volume / broadcast icons); media ink on media cards.
    var iconTint: Color = FX.text2
    /// Tertiary "gray" (home glyph, unlink, name chevron); media ink on media cards.
    var faintTint: Color = FX.text3
    /// Additive (linear-add) blend for the gray icons — on dark-mode media cards.
    var additive: Bool = false
    var sourceTrigger: AnyView? = nil
    var onOpenMenu: (() -> Void)? = nil
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
                name
                Spacer(minLength: 0)
                if let onUnlink {
                    Button { Haptics.tap(); onUnlink() } label: {
                        TablerIcon(glyph: .unlink, size: 18).mediaMuted(faintTint, additive: additive)
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
            DeviceNameTrigger(label: deviceName, color: nameColor, chevronColor: faintTint,
                              additiveChevron: additive, action: onOpenMenu)
        } else {
            Text(deviceName)
                .font(FxFont.nameDevice).foregroundStyle(nameColor).lineLimit(1)
        }
    }

    @ViewBuilder
    private var volume: some View {
        if store.isExternalVolume(client.id) {
            HStack(spacing: Space.sm) {
                TablerIcon(glyph: .broadcastTower, size: 16).mediaMuted(iconTint, additive: additive)
                Text("Volume controlled by iPhone").font(.caption).mediaMuted(faintTint, additive: additive).lineLimit(1)
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
                    VolumeIcon(level: displayValue, size: 20, tint: iconTint).frame(width: 22)
                        .blendMode(additive ? .plusLighter : .normal)
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
    var iconTint: Color = FX.text2
    var additive: Bool = false
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
                DeviceNameTrigger(label: "All", color: accent, chevronColor: iconTint,
                                  additiveChevron: additive, action: onOpenMenu)
                Spacer(minLength: 0)
                sourceTrigger
            }
            HStack(spacing: Space.md) {
                Button { Haptics.tap(); toggleMuteAll() } label: {
                    VolumeIcon(level: displayAvg, size: 20, tint: iconTint).frame(width: 22)
                        .blendMode(additive ? .plusLighter : .normal)
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
    @State private var grabOffset: CGFloat = 0

    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width
            let pct = CGFloat(min(max(value, 0), 100)) / 100
            // Track grows from 6 → 12pt while dragging (FX-88) so it's easier to
            // see under the thumb. Stays centered in the fixed 28pt frame below,
            // so the card/row height never changes.
            let trackH: CGFloat = dragging ? 12 : 6
            ZStack(alignment: .leading) {
                Capsule().fill(track).frame(height: trackH)
                Capsule().fill(fill).frame(width: max(trackH, w * pct), height: trackH)
                // Touch-reveal thumb (FX-60): hidden at rest so a resting card
                // reads as a clean fill bar (web `.fx-volume.card-v2 .fx-volume-
                // thumb { opacity: 0 }`); fades + grows in while dragging (the
                // touch analog of the web's hover/active reveal). The contentShape
                // Rectangle below keeps the full-height drag target regardless.
                //
                // FX-88: `.scaleEffect` MUST come before `.offset`. SwiftUI scales
                // around the view's un-offset layout center, so scaling *after* the
                // offset multiplies the dot's position by the scale factor — making
                // it drift ahead of both the finger and the white fill bar. Scaling
                // first (around the dot's own center) then offsetting locks the dot
                // center to `w * pct`, exactly where the fill bar ends.
                Circle().fill(fill).frame(width: 14, height: 14)
                    .shadow(color: .black.opacity(0.22), radius: 1.5, y: 1)
                    .scaleEffect(dragging ? 2.0 : 0.5)
                    .opacity(dragging ? 1 : 0)
                    .offset(x: min(max(0, w * pct - 7), w - 14))
            }
            .frame(height: 28)
            .contentShape(Rectangle())
            .gesture(
                // Drag the head only: engage solely when the touch starts on the
                // thumb (within a generous hit radius); taps elsewhere on the
                // track do nothing. `grabOffset` keeps the grab from jumping.
                DragGesture(minimumDistance: 0)
                    .onChanged { g in
                        if !dragging {
                            let thumbX = min(max(w * pct, 7), w - 7)
                            guard abs(g.startLocation.x - thumbX) <= 22 else { return }
                            dragging = true
                            grabOffset = g.startLocation.x - thumbX
                            onEditingChanged(true)
                        }
                        let x = g.location.x - grabOffset
                        value = Double(min(max(x / w, 0), 1)) * 100
                    }
                    .onEnded { _ in
                        if dragging { dragging = false; onEditingChanged(false) }
                    }
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
    @State private var grabOffset: CGFloat = 0

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
                // Drag the head only: engage solely when the touch starts on the
                // thumb; a tap elsewhere on the track does NOT seek. `grabOffset`
                // keeps the grab from jumping the position.
                DragGesture(minimumDistance: 0)
                    .onChanged { g in
                        if !dragging {
                            let thumbX = min(max(w * pct, 8), w - 8)
                            guard abs(g.startLocation.x - thumbX) <= 22 else { return }
                            dragging = true
                            grabOffset = g.startLocation.x - thumbX
                            onStart()
                        }
                        let x = g.location.x - grabOffset
                        onScrub(min(max(x / w, 0), 1) * duration)
                    }
                    .onEnded { g in
                        guard dragging else { return }   // never grabbed the head
                        dragging = false
                        let x = g.location.x - grabOffset
                        onCommit(min(max(x / w, 0), 1) * duration)
                    }
            )
            .animation(.fxQuick, value: dragging)
        }
        .frame(height: 22)
        .accessibilityElement()
        .accessibilityLabel("Seek")
    }
}

// MARK: - Media muted ink

extension View {
    /// Tints a muted "gray" element on a media card. On dark mode it uses an
    /// additive (linear-add / plus-lighter) blend so a low-opacity white reads as
    /// a soft highlight that picks up the album tint, rather than a flat overlay;
    /// on light mode (and off-media) it's a normal composite.
    func mediaMuted(_ color: Color, additive: Bool) -> some View {
        foregroundStyle(color).blendMode(additive ? .plusLighter : .normal)
    }
}

// MARK: - Marquee text (overflow-only scroll with soft edge fades)

/// A single-line label that sits static when it fits, but when the text is wider
/// than the available width it scrolls continuously (a second copy trails behind
/// a gap for a seamless loop) under a soft left/right fade. Used for the media
/// title + subtitle so long names read in full rather than truncating.
///
/// This view owns ONLY its horizontal scroll. It never needs to react to its own
/// `text` changing because `NowPlayingText` keys each title with `.id`, so a new
/// track yields a brand-new `MarqueeText` instance — the scroll always (re)starts
/// cleanly from `onAppear`, never from a fragile in-place reset.
private struct MarqueeText: View {
    let text: String
    var font: Font
    var color: Color
    var fadeWidth: CGFloat = 14
    var gap: CGFloat = 44
    var pointsPerSecond: Double = 30

    @State private var textWidth: CGFloat = 0
    @State private var containerWidth: CGFloat = 0
    @State private var animate = false

    private var overflow: Bool { textWidth > containerWidth + 1 }

    var body: some View {
        // A clear, layout-driving copy reserves the row's height and the
        // available width (truncating, so it never forces overflow on the
        // parent); the real content draws as an overlay and is masked.
        Text(text)
            .font(font)
            .lineLimit(1)
            .foregroundStyle(.clear)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(GeometryReader { g in
                Color.clear
                    .onAppear { containerWidth = g.size.width }
                    .onChange(of: g.size.width) { _, w in containerWidth = w }
            })
            .overlay(alignment: .leading) { content }
            .background(alignment: .leading) { measurer }
            .mask(overflow ? AnyView(fadeMask) : AnyView(Color.black))
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(text)
    }

    @ViewBuilder
    private var content: some View {
        if overflow {
            // Two copies a `gap` apart; scrolling left by exactly one copy+gap and
            // looping forever reads as a seamless wrap. The HStack carries its OWN
            // explicit `.animation` keyed on `animate`, so this linear loop is fully
            // insulated from any ancestor transaction (e.g. the track-change slide).
            HStack(spacing: gap) {
                label
                label
            }
            .offset(x: animate ? -(textWidth + gap) : 0)
            .animation(
                .linear(duration: max(4, Double(textWidth + gap) / pointsPerSecond)).repeatForever(autoreverses: false),
                value: animate
            )
            // Fires exactly when the row first overflows (the HStack only exists
            // then), so the loop starts reliably for every fresh instance.
            .onAppear { animate = true }
            .fixedSize()
        } else {
            label
        }
    }

    private var label: some View {
        Text(text).font(font).foregroundStyle(color).lineLimit(1).fixedSize()
    }

    /// Hidden full-width measurement so we know whether to scroll.
    private var measurer: some View {
        label
            .background(GeometryReader { g in
                Color.clear
                    .onAppear { textWidth = g.size.width }
                    .onChange(of: g.size.width) { _, w in textWidth = w }
            })
            .hidden()
    }

    private var fadeMask: some View {
        HStack(spacing: 0) {
            LinearGradient(colors: [.clear, .black], startPoint: .leading, endPoint: .trailing)
                .frame(width: fadeWidth)
            Color.black
            LinearGradient(colors: [.black, .clear], startPoint: .leading, endPoint: .trailing)
                .frame(width: fadeWidth)
        }
    }
}

// MARK: - Now-playing text line (FX-79 track-change transition)

/// One now-playing line (title or artist) that cross-fades when its text changes
/// — no motion, the two titles simply dissolve on top of each other.
///
/// Keying the `MarqueeText` with `.id(text)` makes each distinct title a distinct
/// view, so a track change is a removal (old) + insertion (new) that the framework
/// fades with the `.opacity` transition. SwiftUI manages any number of overlapping
/// in-flight transitions natively, so rapid changes just queue clean fades — none
/// of the stale-state races a hand-rolled swap suffered. The marquee's own scroll
/// is insulated: it carries its own explicit `.animation`, and the wrapper's
/// `.animation(value: text)` only opens a transaction when `text` changes.
private struct NowPlayingText: View {
    let text: String
    var font: Font
    var color: Color
    var delay: Double = 0

    var body: some View {
        ZStack(alignment: .leading) {
            MarqueeText(text: text, font: font, color: color)
                .id(text)
                .transition(.opacity)
        }
        .animation(.easeInOut(duration: 0.3).delay(delay), value: text)
    }
}

// MARK: - Transport buttons (web .fx-group-progress-actions)

/// A template-rendered media glyph from the asset catalog (custom Play/Pause/
/// Prev/Next SVGs), tinted by the caller's `foregroundStyle`.
private struct MediaGlyph: View {
    let name: String
    let size: CGFloat
    init(_ name: String, size: CGFloat) { self.name = name; self.size = size }
    var body: some View {
        Image(name).renderingMode(.template).resizable().scaledToFit()
            .frame(width: size, height: size)
    }
}

/// Press feedback for the media transport: the glyph scales up and a translucent
/// halo (the button's own tint) fades/grows in behind it while held, plus a tap
/// haptic on press-down — a stronger, more tactile affordance than a flat icon.
private struct MediaButtonStyle: ButtonStyle {
    var tint: Color

    func makeBody(configuration: Configuration) -> some View {
        Content(tint: tint, pressed: configuration.isPressed, label: configuration.label)
    }

    /// Press-in is INSTANT (no animation) so even a quick tap shows the full
    /// pressed state; only the release animates back out. Driven by explicit
    /// `withAnimation` (the `.animation(ternary, value:)` form evaluates with the
    /// stale state and can't express this asymmetry).
    private struct Content: View {
        let tint: Color
        let pressed: Bool
        let label: ButtonStyleConfiguration.Label
        @State private var lift: CGFloat = 0   // 0 = rest, 1 = pressed

        var body: some View {
            // Layout frame stays 24pt (so the lockup's button spacing is
            // unchanged); the halo + scale overflow that frame and aren't clipped.
            label
                .frame(width: 24, height: 24)
                .background {
                    Circle()
                        .fill(tint.opacity(0.16 * lift))
                        .frame(width: 38, height: 38)
                        .scaleEffect(0.5 + 0.5 * lift)
                }
                .scaleEffect(1 + 0.18 * lift)
                .contentShape(Circle())
                .onChange(of: pressed) { _, isPressed in
                    if isPressed {
                        Haptics.tap()
                        lift = 1   // instant — snaps to pressed even on a fast tap
                    } else {
                        withAnimation(.spring(response: 0.3, dampingFraction: 0.7)) { lift = 0 }
                    }
                }
        }
    }
}

private struct PlayPauseButton: View {
    @EnvironmentObject private var store: FauxnosStore
    let group: SpeakerGroup
    var tint: Color = FX.text
    @State private var pending: Bool?

    private var actualPlaying: Bool { store.playback(for: group)?.isPlaying == true }
    private var displayed: Bool { pending ?? actualPlaying }

    var body: some View {
        Button {
            // Swap the glyph instantly on finger-lift (no crossfade) — disabling
            // animations here keeps it out of the release spring transaction, so
            // it flips play↔pause hard while the scale still springs back.
            var txn = Transaction(); txn.disablesAnimations = true
            withTransaction(txn) { pending = !displayed }
            Task { await store.sendPlayback(.playpause, for: group) }
        } label: {
            MediaGlyph(displayed ? "MediaPause" : "MediaPlay", size: 20)
                .foregroundStyle(tint)
        }
        .buttonStyle(MediaButtonStyle(tint: tint))
        .accessibilityLabel(displayed ? "Pause" : "Play")
        .onChange(of: store.playback(for: group)?.updatedAt) { _, _ in pending = nil }
    }
}

private struct TransportButton: View {
    let asset: String
    let label: String
    var tint: Color = FX.text2
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            MediaGlyph(asset, size: 16)
                .foregroundStyle(tint)
        }
        .buttonStyle(MediaButtonStyle(tint: tint))
        .accessibilityLabel(label)
    }
}

// MARK: - Source picker popover (FX-19)

/// A compact, self-sizing popover for switching the group's source — a single
/// tap, no full-height sheet. Dismisses on selection or on a tap outside (the
/// system popover behavior), so there's no explicit "Done" affordance.
private struct PopoverHeightKey: PreferenceKey {
    static var defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) { value = max(value, nextValue()) }
}

struct SourcePickerPopover: View {
    @EnvironmentObject private var store: FauxnosStore
    @Environment(\.dismiss) private var dismiss
    let group: SpeakerGroup

    @State private var measuredHeight: CGFloat = 0

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
                    Haptics.select()
                    Task {
                        // Group + a non-Spotify pick → ungroup then switch.
                        if isMulti && s.id != active {
                            await store.switchSourceUngrouping(s.id, in: group)
                        } else {
                            await store.switchSource(s.id, in: group)
                        }
                    }
                    dismiss()
                } label: {
                    HStack(spacing: Space.md) {
                        SourceIcon(icon: s.icon, sourceId: s.id, size: 20)
                            .foregroundStyle(isActive ? FX.text : FX.text2)
                            .frame(width: 24)
                        Text(s.label?.isEmpty == false ? s.label! : s.id.capitalized)
                            .font(FxFont.fustat(17, .bold))
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
            // On a group, every source is listed, but switching to anything other
            // than Spotify breaks the room first — caption at the bottom flags it.
            if isMulti {
                Text("Changing source will ungroup all")
                    .font(.caption).foregroundStyle(FX.text3)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, Space.lg)
                    .padding(.top, Space.sm).padding(.bottom, Space.md)
            }
        }
        .padding(.vertical, Space.sm)
        // FIXED width (not a min/max range): the system popover reads its
        // `preferredContentSize` from this content, and a flexible width let the
        // multi-line caption re-wrap between the measure pass and the final
        // layout, under-sizing the popover and clipping the bottom. A fixed width
        // + an explicitly measured height pins the size deterministically.
        .frame(width: 260, alignment: .leading)
        .background(GeometryReader { proxy in
            Color.clear.preference(key: PopoverHeightKey.self, value: proxy.size.height)
        })
        .onPreferenceChange(PopoverHeightKey.self) { measuredHeight = $0 }
        .frame(height: measuredHeight == 0 ? nil : measuredHeight)
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
            Text("Audio group").font(FxFont.fustat(15, .bold)).foregroundStyle(FX.text)
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
                        // Device name matches the multi-card device-row treatment
                        // (FxFont.nameDevice). The home reads at the same normal
                        // weight/color as the rest — no dimming.
                        Text(store.displayName(for: d))
                            .font(FxFont.nameDevice)
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
                        Text("Ungroup all").font(FxFont.fustat(17, .semibold))
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
