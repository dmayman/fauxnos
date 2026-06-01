//
//  GroupsListView.swift
//  Fauxnos
//
//  The control-core screen: a live list of speaker groups. Membership and
//  sources come from /api/groups; now-playing / transport / active-idle reflect
//  MQTT in real time with no manual refresh. Each group renders as a `GroupCard`.
//
//  FX-33 design pass: the deliberate Fauxnos ground (FX.bg), generous card
//  spacing, a refined live/offline pill, and — folding in FX-28 — a genuine
//  loading state (skeleton placeholder cards) distinct from the loaded-empty
//  state, so the list never flashes "no devices" before the first data lands.
//

import SwiftUI

struct GroupsListView: View {
    @EnvironmentObject private var store: FauxnosStore

    var body: some View {
        NavigationStack {
            content
                .background(FX.bg.ignoresSafeArea())
                .navigationTitle("Fauxnos")
                .toolbar {
                    ToolbarItem(placement: .topBarTrailing) {
                        ConnectionBadge(connected: store.mqttConnected)
                    }
                }
                .refreshable { await store.refresh() }
        }
        .tint(FX.text)
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
                    ForEach(Array(store.groups.enumerated()), id: \.element.id) { index, group in
                        // Staggered reveal (FX-61): real cards fade + rise in on
                        // first appearance rather than popping, staggered by index
                        // (web `fx-card-appear` with `--appear-delay`). Per-card
                        // identity keeps `shown` sticky, so a 60s refresh doesn't
                        // re-stagger. Reduce-motion shows them immediately.
                        StaggeredAppear(index: index) {
                            GroupCard(group: group)
                        }
                    }
                }
                .padding(.horizontal, Space.lg)
                .padding(.top, Space.sm)
                .padding(.bottom, Space.xl)
            }
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

// MARK: - Connection badge

private struct ConnectionBadge: View {
    let connected: Bool
    var body: some View {
        HStack(spacing: 5) {
            Circle()
                .fill(connected ? FX.ok : FX.warn)
                .frame(width: 7, height: 7)
            Text(connected ? "Live" : "Offline")
                .font(.caption2.weight(.semibold))
                .foregroundStyle(FX.text2)
        }
        .padding(.horizontal, Space.sm)
        .padding(.vertical, 5)
        .background(.ultraThinMaterial, in: Capsule())
        .accessibilityLabel(connected ? "Real-time connected" : "Real-time disconnected")
    }
}

#Preview {
    GroupsListView().environmentObject(FauxnosStore())
}
