//
//  FlippingAlbumArt.swift
//  Fauxnos
//
//  FX-79: the now-playing cover performs a 3D "card flip" when the track's
//  artwork changes — the current cover spins around its vertical axis and the
//  *incoming* cover is revealed on its back face. The motion has a wind-up
//  anticipation (a small counter-rotation before the throw), a spring rotation
//  that overshoots 180° and settles, and a scale bump that peaks edge-on for
//  emphasis. It is GPU-composited 3D (Core Animation's Metal-backed transform
//  via `rotation3DEffect` + perspective) rather than a flat cross-dissolve.
//
//  Two correctness rules from the ticket:
//    • Fires once per *genuine* cover change — deduped against the shown cover,
//      so poll/MQTT refreshes carrying the same track never re-flip.
//    • Never animates to a blank then pops the art in: the incoming cover is
//      decoded BEFORE the flip starts (bounded by a short timeout). If it can't
//      decode in time, the flip reveals the source glyph and the real cover
//      fades into the back face the instant it lands, so the front inherits it.
//
//  Reduce-motion users get an instant, non-animated swap.
//

import SwiftUI
import UIKit

// MARK: - Decoded-cover cache / loader

/// Loads and memoizes decoded album covers by URL so the flip can show a fully
/// realized image the moment it starts (no async pop). Shares `URLSession`'s
/// HTTP cache with the rest of the app, so a cover already pulled for the
/// backdrop / color extraction is usually warm here too.
@MainActor
final class AlbumArtImageStore: ObservableObject {
    static let shared = AlbumArtImageStore()

    private var cache: [String: UIImage] = [:]
    private var inFlight: [String: Task<UIImage?, Never>] = [:]

    /// Synchronous cache hit, or nil if not yet decoded.
    func cached(_ urlString: String?) -> UIImage? {
        guard let urlString else { return nil }
        return cache[urlString]
    }

    /// Decoded cover for `urlString` (cached on success). nil if it can't load.
    /// Coalesces concurrent requests for the same URL onto one download.
    func image(for urlString: String) async -> UIImage? {
        if let img = cache[urlString] { return img }
        if let task = inFlight[urlString] { return await task.value }
        guard let url = URL(string: urlString) else { return nil }
        let task = Task.detached(priority: .userInitiated) { () -> UIImage? in
            guard let (data, _) = try? await URLSession.shared.data(from: url) else { return nil }
            return UIImage(data: data)
        }
        inFlight[urlString] = task
        let img = await task.value
        inFlight[urlString] = nil
        if let img { cache[urlString] = img }
        return img
    }

    #if DEBUG
    /// Pre-seed decoded covers for Xcode Previews (deterministic, no network).
    func preload(_ map: [String: UIImage]) { for (k, v) in map { cache[k] = v } }
    #endif
}

// MARK: - Flipping cover

struct FlippingAlbumArt: View {
    /// Current track's cover URL (nil when the active source carries no art).
    let artURL: String?
    let size: CGFloat
    let cornerRadius: CGFloat
    let borderColor: Color
    let shadow: (color: Color, radius: CGFloat, y: CGFloat)
    /// Shown when there's no decoded cover (the source-glyph lockup).
    let placeholder: AnyView

    // ── Motion knobs (open for tuning with the user) ──
    private static let windUpAngle: Double = -16        // anticipation counter-rotation, °
    private static let windUpDuration: Double = 0.13
    private static let flipResponse: Double = 0.62      // spring response of the throw
    private static let flipDamping: Double = 0.55       // < 1 → overshoot + settle
    private static let scaleBump: Double = 0.16         // added scale, peaks edge-on
    private static let perspective: CGFloat = 0.42      // lower = deeper 3D
    private static let loadTimeout: Double = 0.45       // max wait for the incoming cover

    private let store = AlbumArtImageStore.shared
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    @State private var frontImage: UIImage?
    @State private var frontURL: String?
    @State private var backImage: UIImage?
    @State private var angle: Double = 0
    /// The URL we're currently trying to land on; guards async races so a stale
    /// load can't promote over a newer track change.
    @State private var desiredURL: String?
    /// Bumped per flip so a superseded flip's completion / late-fill no-ops.
    @State private var flipGen = 0

    /// Scale derived from the rotation: 1 at rest / 180°, peaking edge-on (90°),
    /// dipping slightly during the wind-up — one driver keeps it perfectly synced.
    private var scale: Double { 1 + Self.scaleBump * sin(angle * .pi / 180) }

    var body: some View {
        ZStack {
            face(frontImage).opacity(angle < 90 ? 1 : 0)
            // Back face is pre-flipped 180° so the revealed cover isn't mirrored.
            face(backImage)
                .rotation3DEffect(.degrees(180), axis: (x: 0, y: 1, z: 0))
                .opacity(angle >= 90 ? 1 : 0)
        }
        .frame(width: size, height: size)
        .rotation3DEffect(.degrees(angle), axis: (x: 0, y: 1, z: 0), perspective: Self.perspective)
        .scaleEffect(scale)
        .shadow(color: shadow.color, radius: shadow.radius, y: shadow.y)
        .onAppear { sync(to: artURL, animated: false) }
        .onChange(of: artURL) { _, newURL in sync(to: newURL, animated: !reduceMotion) }
    }

    @ViewBuilder
    private func face(_ image: UIImage?) -> some View {
        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
            .fill(FX.surface2)
            .frame(width: size, height: size)
            .overlay {
                if let image {
                    Image(uiImage: image).resizable().scaledToFill()
                } else {
                    placeholder
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                .strokeBorder(borderColor, lineWidth: 1))
    }

    // MARK: Drive

    /// Reconcile to a new cover URL. First cover / reduce-motion / source-cleared
    /// snap with no flip; a genuine cover change loads the incoming art (bounded)
    /// then flips to it.
    private func sync(to url: String?, animated: Bool) {
        desiredURL = url

        guard let url else {                 // source has no art now → clear, no flip
            frontImage = nil; frontURL = nil; backImage = nil; angle = 0
            return
        }
        guard url != frontURL else { return } // same cover already shown → ignore refresh

        let shouldFlip = animated && frontURL != nil
        Task {
            let img = await loadBounded(url)
            guard desiredURL == url else { return }   // superseded by a newer change
            if shouldFlip {
                beginFlip(to: url, image: img)
            } else {
                var t = Transaction(); t.disablesAnimations = true
                withTransaction(t) { frontImage = img; frontURL = url; backImage = nil; angle = 0 }
                if img == nil { fillFrontLate(url) }
            }
        }
    }

    /// The decoded cover, or nil if it doesn't arrive within `loadTimeout` — so a
    /// slow network never stalls the flip out of sync with the track change.
    private func loadBounded(_ url: String) async -> UIImage? {
        if let img = store.cached(url) { return img }
        return await withTaskGroup(of: UIImage?.self) { group in
            group.addTask { await store.image(for: url) }
            group.addTask {
                try? await Task.sleep(nanoseconds: UInt64(Self.loadTimeout * 1_000_000_000))
                return nil
            }
            let first = await group.next() ?? nil
            group.cancelAll()
            return first
        }
    }

    private func beginFlip(to url: String, image: UIImage?) {
        backImage = image
        flipGen += 1
        let gen = flipGen

        // Cover hadn't decoded in time → flip to the glyph now, then fade the real
        // cover into the back face the moment it lands (the front inherits it on
        // promote, since the completion reads the latest `backImage`).
        if image == nil {
            Task {
                let late = await store.image(for: url)
                guard gen == flipGen, desiredURL == url, let late else { return }
                withAnimation(.easeIn(duration: 0.3)) { backImage = late }
            }
        }

        withAnimation(.easeOut(duration: Self.windUpDuration)) { angle = Self.windUpAngle }
        withAnimation(.spring(response: Self.flipResponse, dampingFraction: Self.flipDamping)
                        .delay(Self.windUpDuration)) {
            angle = 180
        } completion: {
            guard gen == flipGen else { return }   // a newer flip took over
            // Promote the revealed back face to the front and reset to 0° in a
            // single non-animated frame — 0° (front) and 180° (back) show the same
            // cover, so the reset is invisible and the next flip starts clean.
            var t = Transaction(); t.disablesAnimations = true
            withTransaction(t) {
                frontImage = backImage; frontURL = url
                backImage = nil; angle = 0
            }
        }
    }

    /// Snap path fallback: a cover that timed out fades into the front once decoded.
    private func fillFrontLate(_ url: String) {
        Task {
            let late = await store.image(for: url)
            guard desiredURL == url, frontURL == url, let late else { return }
            withAnimation(.easeIn(duration: 0.3)) { frontImage = late }
        }
    }
}

// MARK: - Preview

#if DEBUG
private struct FlipPreviewHarness: View {
    @State private var url = PreviewData.cover000
    @State private var n = 0
    private let covers = [PreviewData.cover000, PreviewData.cover002]

    var body: some View {
        VStack(spacing: 40) {
            FlippingAlbumArt(
                artURL: url,
                size: 160,
                cornerRadius: Radius.art,
                borderColor: FX.line,
                shadow: (.black.opacity(0.5), 14, 6),
                placeholder: AnyView(
                    TablerIcon(glyph: .brandSpotify, size: 64).foregroundStyle(FX.text3)
                )
            )
            Button("Next track →") {
                n += 1
                url = covers[n % covers.count]
            }
            .font(FxFont.fustat(17, .bold))
            .foregroundStyle(FX.text)
            .padding(.horizontal, 24).padding(.vertical, 12)
            .background(Capsule().fill(FX.surface2))
        }
        .padding(40)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(FX.bg)
    }
}

#Preview("Album flip") { FlipPreviewHarness() }
#endif
