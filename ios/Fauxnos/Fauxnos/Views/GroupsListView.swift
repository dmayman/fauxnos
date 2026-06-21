//
//  GroupsListView.swift
//  Fauxnos
//
//  The control-core screen: a live list of speaker groups. Membership and
//  sources come from /api/groups; now-playing / transport / active-idle reflect
//  MQTT in real time with no manual refresh. Each group renders as a `GroupCard`.
//
//  FX-33 design pass: the deliberate Fauxnos ground (FX.bg), generous card
//  spacing, and — folding in FX-28 — a genuine loading state (skeleton
//  placeholder cards) distinct from the loaded-empty state, so the list never
//  flashes "no devices" before the first data lands.
//
//  FX-80 header cleanup: the live/offline badge is gone and the large title is
//  dropped for an inline-only nav bar (no large title overlapping the list on
//  scroll). The title is the "fauxnos" wordmark in Fustat Bold, whose color
//  tracks the backdrop behind the bar — illuminated white over dark art,
//  darkened over light art, plain gray with no artwork (see `wordmarkStyle`).
//

import SwiftUI

struct GroupsListView: View {
    @EnvironmentObject private var store: FauxnosStore
    @Environment(\.colorScheme) private var colorScheme
    @ObservedObject private var dev = DevControl.shared   // FX-77 backdrop tuning
    @ObservedObject private var artColors = AlbumArtColorStore.shared  // FX-80 wordmark contrast
    @StateObject private var dragController = CardDragController()

    /// FX-80: the wordmark fades out as the list scrolls up to it. 1 at rest, 0
    /// once the first cards have risen into the bar. Driven by scroll offset.
    @State private var wordmarkScrollOpacity: Double = 1

    /// FX-77: the cover of the top playing group, rendered full-bleed behind the
    /// whole list as a blurred backdrop the translucent cards float over. nil when
    /// nothing is playing (or the backdrop is toggled off). In DEBUG, the Mac
    /// album chooser (`demo.art`) overrides the live cover so the look can be
    /// tuned against any artwork without live Spotify.
    /// The art string driving the backdrop (and now the wordmark's contrast
    /// decision). Kept as the raw string so it keys `AlbumArtColorStore` exactly
    /// as the cards do; `backdropArtURL` derives the URL the backdrop renders.
    private var backdropArtSource: String? {
        guard dev.b("backdrop.enabled.\(colorScheme == .dark ? "dark" : "light")", true) else { return nil }
        #if DEBUG
        if let demo = dev.s("demo.art") { return demo }
        #endif
        for g in store.displayGroups where store.currentSource(of: g) == "spotify" {
            if let t = store.track(for: g), t.hasMeta, let s = t.artUrl { return s }
        }
        return nil
    }

    private var backdropArtURL: URL? { backdropArtSource.flatMap { URL(string: $0) } }

    /// FX-80: the "fauxnos" wordmark adapts to whatever sits behind the bar.
    /// Over a dark backdrop it's translucent white, linear-added so it glows off
    /// the art; over a light backdrop it flips to a dark, `.plusDarker` mark so it
    /// stays legible (white would wash out). With no art, a plain mode-adaptive
    /// gray on the solid ground. The backdrop's brightness behind the bar is the
    /// cover's average luma composited over `FX.bg` at the backdrop's top opacity
    /// (it renders full-strength at the top, fading downward).
    private var wordmarkStyle: WordmarkStyle {
        guard backdropArtURL != nil, let src = backdropArtSource else {
            return WordmarkStyle(color: FX.text2, blend: .normal)
        }
        artColors.ensure(src)
        guard let artLuma = artColors.luma(for: src) else {
            return WordmarkStyle(color: .white.opacity(0.5), blend: .plusLighter)  // loading → assume art
        }
        let dark = colorScheme == .dark
        let topOpacity = dark ? 0.79 : 0.74              // BlurArtBackdrop baseOpacity default
        let groundLuma = dark ? 0.024 : 0.976            // FX.bg luma (#060606 / #F9F9F9)
        let behindBar = topOpacity * artLuma + (1 - topOpacity) * groundLuma
        return behindBar > 0.55
            ? WordmarkStyle(color: .black.opacity(0.5), blend: .plusDarker)        // light backdrop → darkened
            : WordmarkStyle(color: .white.opacity(0.5), blend: .plusLighter)       // dark backdrop  → illuminated
    }

    /// How far the backdrop crossfades a track change over — the wordmark's color
    /// crossfade rides the same duration so the two transition together (FX-80).
    private var backdropCrossfade: Double {
        dev.d("backdrop.xfade.\(colorScheme == .dark ? "dark" : "light")", 0.6)
    }

    var body: some View {
        NavigationStack {
            content
                // FX-77 full-bleed blurred album-art backdrop, beneath the
                // drag-hover tint. The translucent cards above float over it.
                .background {
                    ZStack {
                        FX.bg
                        // FX-79: cover→cover crossfade (slide + staggered fade) is
                        // handled INSIDE BlurArtBackdrop; this `.transition` only
                        // fades the whole backdrop in/out when playback starts or
                        // stops (the art URL appears / disappears).
                        if let url = backdropArtURL {
                            BlurArtBackdrop(url: url).transition(.opacity)
                        }
                        // Tints when a grouped device is dragged over empty space,
                        // marking the "drop to remove from group" zone.
                        FX.text.opacity(dragController.hoverBackground ? 0.07 : 0)
                        // FX-83: the same drop-target stroke a hovered card gets,
                        // drawn around the very edge of the screen — so "drop on
                        // the background to ungroup" reads as a real target rather
                        // than invisible dead space.
                        if dragController.hoverBackground {
                            RoundedRectangle(cornerRadius: 55, style: .continuous)
                                .strokeBorder(DropIndicator.color, lineWidth: DropIndicator.lineWidth)
                                .padding(2)
                                .transition(.opacity)
                        }
                    }
                    .ignoresSafeArea()
                    .animation(.fxEase, value: dragController.hoverBackground)
                    .animation(.easeInOut(duration: 0.5), value: backdropArtURL != nil)
                }
                // FX-80: the standard iOS nav bar (its translucent material is the
                // blur that fades cards behind it as they scroll), but inline-only
                // — no large title that overlaps the list on scroll. The title is
                // the "fauxnos" wordmark in the brand face (Fustat Bold); its color
                // adapts to the backdrop behind the bar (see `wordmarkStyle`).
                .navigationTitle("fauxnos")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .principal) {
                        WordmarkTitle(style: wordmarkStyle,
                                      crossfade: backdropCrossfade,
                                      scrollOpacity: wordmarkScrollOpacity)
                    }
                }
                // Fade the wordmark out as the list scrolls up into the bar.
                // contentOffset.y + contentInsets.top is 0 at rest, positive once
                // scrolled; the mark holds for the first few points (so a nudge
                // doesn't dim it) then fades as the cards reach it.
                .onScrollGeometryChange(for: CGFloat.self) { geo in
                    geo.contentOffset.y + geo.contentInsets.top
                } action: { _, y in
                    wordmarkScrollOpacity = 1 - min(1, max(0, (y - 20) / 44))
                }
                .refreshable { await store.refresh() }
        }
        .tint(FX.text)
        .environmentObject(dragController)
    }

    @ViewBuilder
    private var content: some View {
        if store.groups.isEmpty {
            // ScrollView so pull-to-refresh still works while empty/erroring.
            ScrollView { emptyOrError.frame(maxWidth: .infinity) }
        } else {
            // ScrollView + LazyVStack (not List) so the drag-and-drop grouping
            // behaves predictably — List intercepts drags for its own reordering
            // and makes `.draggable`/`.dropDestination` flaky.
            ScrollView {
                LazyVStack(spacing: Space.lg) {
                    ForEach(Array(store.displayGroups.enumerated()), id: \.element.id) { index, group in
                        // Staggered reveal (FX-61): real cards fade + rise in on
                        // first appearance rather than popping, staggered by index
                        // (web `fx-card-appear` with `--appear-delay`). Per-card
                        // identity keeps `shown` sticky, so a 60s refresh doesn't
                        // re-stagger. Reduce-motion shows them immediately.
                        StaggeredAppear(index: index) {
                            GroupCard(group: group)
                        }
                        // FX-83: when the finger hovers the space just below THIS
                        // (source) card while one of its devices is airborne, open
                        // an empty gap so the cards below slide down — just making
                        // room to drop on the background. Pure space: no stroke, no
                        // placeholder, not its own drop zone (the window-edge
                        // background treatment is the indicator, and the drop routes
                        // through the normal background/ungroup path).
                        if dragController.gapOpen
                            && dragController.sourceGroupId == group.id {
                            Color.clear
                                .frame(height: CardDragController.gapHeight)
                                .transition(.opacity)
                        }
                    }
                }
                .padding(.horizontal, Space.lg)
                .padding(.top, Space.sm)
                .padding(.bottom, Space.xl)
                // Open / close the make-room gap (and slide the cards below).
                .animation(.fxEase, value: dragController.gapOpen)
                // Shared geometry for lift-to-regroup: cards report their frames
                // here, and the lifted device's floating preview rides above them.
                .coordinateSpace(name: kCardSpace)
                .onPreferenceChange(CardFrameKey.self) { dragController.cardFrames = $0 }
                .overlay(alignment: .topLeading) { dragPreview }
            }
            // Freeze scrolling while a card is airborne so the drag owns the touch.
            .scrollDisabled(dragController.isDragging)
        }
    }

    /// The lifted device's floating card, tracking the finger in `kCardSpace`.
    /// Non-interactive so it never intercepts the in-flight drag.
    @ViewBuilder
    private var dragPreview: some View {
        if let preview = dragController.preview {
            // One scale drives both the card and its shadow. `previewLift` is 0
            // while the card is pressed and 1 once it floats, so the shadow grows
            // from the resting card's shadow (radius 6 / y 2 — what the source
            // card showed at the press handoff) to the full float shadow (radius
            // 22 / y 12). Same source as `scaleEffect`, so there's no separate
            // keyframe to flash bigger the instant it becomes draggable.
            let lift = dragController.previewLift
            let opacity = colorScheme == .dark ? 0.4 + 0.1 * lift : 0.07 + 0.11 * lift
            preview
                .frame(width: dragController.previewWidth)
                .scaleEffect(dragController.previewScale)
                .shadow(color: .black.opacity(opacity * dragController.previewOpacity),
                        radius: 6 + 16 * lift, y: 2 + 10 * lift)
                .position(x: dragController.dragLocation.x - dragController.grabOffset.width,
                          y: dragController.dragLocation.y - dragController.grabOffset.height)
                .opacity(dragController.previewOpacity)
                .allowsHitTesting(false)
                .transition(.opacity)
        }
    }

    /// Three distinct states, never blurred together (FX-28):
    ///   loading (no data yet)  → skeleton cards
    ///   error                  → reachability ContentUnavailableView + retry
    ///   loaded-empty           → genuine "no devices" ContentUnavailableView
    @ViewBuilder
    private var emptyOrError: some View {
        if store.isLoading && store.apiError == nil && store.lastUpdated == nil {
            LoadingSkeleton()
        } else if let error = store.apiError {
            ContentUnavailableView {
                Label("Can't reach the server", systemImage: "wifi.exclamationmark")
            } description: {
                Text("\(store.config.host)\n\(error)")
            } actions: {
                Button("Retry") { Task { await store.refresh() } }
                    .buttonStyle(.borderedProminent)
            }
            .padding(.top, 80)
        } else {
            ContentUnavailableView("No devices", systemImage: "hifispeaker.2",
                                   description: Text("No connected devices reported by \(store.config.host)."))
            .padding(.top, 80)
        }
    }
}

// MARK: - Wordmark title (FX-80)

/// The resolved look of the "fauxnos" mark for the current backdrop — a color +
/// blend pair. Equatable so `WordmarkTitle` can crossfade when it changes.
private struct WordmarkStyle: Equatable {
    var color: Color
    var blend: BlendMode
}

/// The nav-bar wordmark. When its `style` changes (a track-change flips the
/// backdrop light↔dark, or art finishes loading) it crossfades between the old
/// and new look over `crossfade` seconds — matched to the backdrop's own fade so
/// the two transition together. Blend modes can't tween, so this dissolves two
/// fully-rendered layers rather than animating a single one. `scrollOpacity`
/// multiplies on top, fading the whole mark out as the list scrolls up to it.
private struct WordmarkTitle: View {
    let style: WordmarkStyle
    let crossfade: Double
    let scrollOpacity: Double

    @State private var shown: WordmarkStyle
    @State private var outgoing: WordmarkStyle?
    @State private var t: Double = 1   // incoming layer opacity, 0→1 across a swap

    init(style: WordmarkStyle, crossfade: Double, scrollOpacity: Double) {
        self.style = style
        self.crossfade = crossfade
        self.scrollOpacity = scrollOpacity
        _shown = State(initialValue: style)
    }

    var body: some View {
        ZStack {
            if let outgoing { label(outgoing).opacity(1 - t) }
            label(shown).opacity(t)
        }
        .opacity(scrollOpacity)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("fauxnos")
        .accessibilityAddTraits(.isHeader)
        .onChange(of: style) { _, new in
            outgoing = shown
            shown = new
            t = 0
            withAnimation(.linear(duration: crossfade)) { t = 1 } completion: { outgoing = nil }
        }
    }

    private func label(_ s: WordmarkStyle) -> some View {
        Text("fauxnos")
            .font(FxFont.fustat(21, .bold))
            .foregroundStyle(s.color)
            .blendMode(s.blend)
    }
}

// MARK: - Loading skeleton

/// Placeholder cards shown only before the first data arrives, so the screen
/// reads as "loading" rather than "empty" (FX-28). A directional shimmer sweep
/// (FX-61) keeps it feeling live without faking content.
private struct LoadingSkeleton: View {
    var body: some View {
        VStack(spacing: Space.lg) {
            ForEach(0..<3, id: \.self) { i in card(index: i) }
        }
        .padding(.horizontal, Space.lg)
        .padding(.top, Space.sm)
        .accessibilityLabel("Loading devices")
    }

    private func card(index: Int) -> some View {
        VStack(alignment: .leading, spacing: Space.md) {
            HStack(spacing: Space.sm) {
                bar(width: 18, height: 18, radius: 5)
                bar(width: 120, height: 14)
                Spacer()
                bar(width: 78, height: 28, radius: 14)
            }
            HStack(spacing: Space.md) {
                bar(width: 64, height: 64, radius: Radius.art)
                VStack(alignment: .leading, spacing: 8) {
                    bar(width: 160, height: 16)
                    bar(width: 110, height: 12)
                }
                Spacer()
            }
            fullBar(height: 4, radius: 2)
        }
        .padding(Space.lg)
        .background(RoundedRectangle(cornerRadius: Radius.card, style: .continuous).fill(FX.surface2))
        // Directional shimmer (FX-61): a translucent highlight band slides L→R
        // across each placeholder, staggered per card — the web
        // `.fx-skeleton-card::after` translateX(-100% → 100%) sweep. Clipped to
        // the card shape; reduce-motion leaves a static placeholder (no sweep).
        .overlay { ShimmerSweep(delay: Double(index) * 0.22) }
        .clipShape(RoundedRectangle(cornerRadius: Radius.card, style: .continuous))
    }

    private func bar(width: CGFloat, height: CGFloat, radius: CGFloat = 6) -> some View {
        RoundedRectangle(cornerRadius: radius, style: .continuous)
            .fill(FX.surface3)
            .frame(width: width, height: height)
    }

    private func fullBar(height: CGFloat, radius: CGFloat = 6) -> some View {
        RoundedRectangle(cornerRadius: radius, style: .continuous)
            .fill(FX.surface3)
            .frame(maxWidth: .infinity).frame(height: height)
    }
}

// MARK: - Shimmer sweep + staggered reveal (FX-61)

/// A highlight band that slides left→right across its container on a repeating
/// loop, the touch-platform port of the web skeleton's `translateX` gradient
/// sweep. Non-interactive; honors reduce-motion (stays parked off-screen).
private struct ShimmerSweep: View {
    let delay: Double
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var phase: CGFloat = -1

    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width
            LinearGradient(
                colors: [.clear, Color.white.opacity(0.10), .clear],
                startPoint: .leading, endPoint: .trailing
            )
            .frame(width: w * 0.5)
            .offset(x: phase * w * 1.5)
        }
        .allowsHitTesting(false)
        .onAppear {
            guard !reduceMotion else { return }
            withAnimation(.linear(duration: 1.4).repeatForever(autoreverses: false).delay(delay)) {
                phase = 1
            }
        }
    }
}

/// Fades + rises its content in once, on first appearance, staggered by index
/// (capped so deep lists don't accumulate long delays). Reduce-motion shows the
/// content immediately. Interactivity is never gated — only the visual entrance.
private struct StaggeredAppear<Content: View>: View {
    let index: Int
    let content: Content
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var shown = false

    init(index: Int, @ViewBuilder content: () -> Content) {
        self.index = index
        self.content = content()
    }

    var body: some View {
        content
            .opacity(shown ? 1 : 0)
            .offset(y: shown ? 0 : 10)
            .onAppear {
                if reduceMotion { shown = true; return }
                withAnimation(.easeOut(duration: 0.5).delay(Double(min(index, 6)) * 0.07)) {
                    shown = true
                }
            }
    }
}

#Preview("Groups — populated") {
    GroupsListView().environmentObject(FauxnosStore.preview())
}

#Preview("Groups — loading") {
    // Empty store, never started → no data yet → the loading skeleton path.
    GroupsListView().environmentObject(FauxnosStore())
}

