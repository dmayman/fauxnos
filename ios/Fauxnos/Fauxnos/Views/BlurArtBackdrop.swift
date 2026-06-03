//
//  BlurArtBackdrop.swift
//  Fauxnos
//
//  FX-77: the currently-playing album cover rendered full-bleed behind the
//  whole list, scaled up, blurred, and faded down the screen — a soft backdrop
//  the (now translucent) group cards float over. This is the "no glass" sibling
//  of FX-74: there's no material/glass layer, the blurred cover IS the backdrop,
//  and it shows through the cards via their tunable fill opacity.
//
//  FX-79: on a track change the backdrop crossfades WITH a horizontal parallax —
//  the outgoing cover fades + slides left while the incoming one starts further
//  right and glides left into place. Three correctness rules learned the hard way:
//    • The clip/mask "shell" stays put full-screen; only the SCALED ART pans
//      inside it. Translating the whole view instead drags the clip edge across
//      the screen as a hard line — this version offsets the image within a fixed
//      clip, and bumps the art's scale so the pan never exposes a cropped edge.
//    • Layers render from DECODED UIImages (via AlbumArtImageStore), not fresh
//      AsyncImages. When the cover swaps front→outgoing role an AsyncImage would
//      reload and flash a blank frame; reusing the decoded image is instant. The
//      incoming cover is also decoded BEFORE the crossfade starts, so the old one
//      simply holds until the new is ready (no flash, no pop).
//    • The two layers don't plain cross-dissolve (that dips coverage at the
//      midpoint and the dark ground washes through). The incoming opacity ramps
//      in fast while the outgoing holds then fades, so the screen stays covered
//      the whole way — the fade is staggered, the motion is simultaneous.
//
//  Every look knob reads from `DevControl` with a baked fallback, so a Mac
//  tuning page can dial it live in DEBUG while release builds use the constants.
//

import SwiftUI
import UIKit

struct BlurArtBackdrop: View {
    let url: URL
    @ObservedObject private var dev = DevControl.shared
    @Environment(\.colorScheme) private var colorScheme

    private let store = AlbumArtImageStore.shared

    // The settled cover, and (only during a crossfade) the one sliding out — held
    // as decoded images so a role swap never triggers a reload flash.
    @State private var frontImage: UIImage?
    @State private var frontURL: URL?
    @State private var outgoingImage: UIImage?
    /// Two independent 0→1 timelines so the slide can run slower / differently
    /// eased than the fade: `fadeT` drives the staggered opacity, `slideT` drives
    /// the horizontal parallax (a longer ease-out). Both 1 = settled.
    @State private var fadeT: Double = 1
    @State private var slideT: Double = 1
    /// The cover we're trying to land on; guards async races so a stale decode
    /// can't apply over a newer change.
    @State private var desiredURL: URL?

    // FX-77: backdrop knobs are mode-scoped (`<base>.dark` / `<base>.light`).
    private var m: String { colorScheme == .dark ? "dark" : "light" }

    var body: some View {
        // FX-79 parallax distance (the art's leftward travel) + fade / slide
        // durations (slide runs slower + ease-out; fade is the quicker dissolve).
        let slide = dev.f("backdrop.slide.\(m)", 56)
        GeometryReader { geo in
            ZStack {
                // Incoming / settled cover, behind. While a crossfade runs it
                // slides in from the right and ramps opacity in fast; once settled
                // (`outgoingImage == nil`) it sits at rest (fadeT/slideT == 1).
                if let frontImage {
                    coverLayer(frontImage, geo: geo, slide: slide,
                               offsetX: lerp(slide, 0, slideT),
                               opacity: incomingOpacity(fadeT))
                }
                // Outgoing cover, on top, fading + sliding left. Holding it above
                // the incoming (which is already opaque underneath by mid-fade)
                // is what keeps the ground from washing through at the midpoint.
                if let outgoingImage {
                    coverLayer(outgoingImage, geo: geo, slide: slide,
                               offsetX: lerp(0, -slide, slideT),
                               opacity: outgoingOpacity(fadeT))
                }
                // Optional dark scrim over the art for extra card legibility.
                Color.black.opacity(dev.d("backdrop.scrim.\(m)", 0.0))
            }
        }
        .onAppear { load(url, initial: true) }
        .onChange(of: url) { _, newURL in load(newURL, initial: false) }
        .allowsHitTesting(false)
    }

    /// One full-bleed blurred cover. The clip + fade mask are fixed to the screen
    /// frame; the art is scaled (with enough headroom to cover the `slide` pan)
    /// and OFFSET inside that clip, so the panning never drags a hard clip edge.
    private func coverLayer(_ image: UIImage, geo: GeometryProxy, slide: CGFloat,
                            offsetX: CGFloat, opacity: Double) -> some View {
        let fadeStart = dev.f("backdrop.fadeStart.\(m)", 0.0)
        // Ensure the scaled art overscans the frame by at least the pan distance
        // (+ a small margin) so a left/right offset can't reveal a cropped edge.
        let needed = 1 + 2 * (abs(slide) + 8) / max(geo.size.width, 1)
        let imgScale = max(dev.f("backdrop.scale.\(m)", 1.25), needed)
        let baseOpacity = dev.d("backdrop.opacity.\(m)", colorScheme == .dark ? 0.79 : 0.74)

        return Image(uiImage: image)
            .resizable()
            .scaledToFill()
            .frame(width: geo.size.width, height: geo.size.height)
            .scaleEffect(imgScale)
            .blur(radius: dev.f("backdrop.blur.\(m)", 52))
            .offset(x: offsetX)                 // ← the ART moves, clip stays put
            .frame(width: geo.size.width, height: geo.size.height)
            .clipped()                          // fixed full-screen clip (static shell)
            .mask(
                LinearGradient(
                    stops: [
                        .init(color: .black, location: fadeStart),
                        .init(color: .clear,
                              location: max(dev.f("backdrop.fadeEnd.\(m)", colorScheme == .dark ? 0.6 : 0.79), fadeStart + 0.01)),
                    ],
                    startPoint: .top, endPoint: .bottom
                )
            )
            .opacity(baseOpacity * opacity)
    }

    // MARK: Load + drive

    private func load(_ url: URL, initial: Bool) {
        guard url != frontURL else { return }
        desiredURL = url
        // Decode the incoming cover BEFORE touching the layers. Cached → instant;
        // otherwise the old cover simply holds until the new is ready (no flash).
        if let cached = store.cached(url.absoluteString) {
            apply(cached, url: url, initial: initial)
        } else {
            Task {
                let img = await store.image(for: url.absoluteString)
                guard desiredURL == url, let img else { return }
                apply(img, url: url, initial: initial)
            }
        }
    }

    private func apply(_ img: UIImage, url: URL, initial: Bool) {
        // First cover (or appearing fresh): just show it, no crossfade.
        if initial || frontImage == nil {
            var t = Transaction(); t.disablesAnimations = true
            withTransaction(t) { frontImage = img; frontURL = url; outgoingImage = nil; fadeT = 1; slideT = 1 }
            return
        }
        let fadeDur = dev.f("backdrop.xfade.\(m)", 0.6)
        let slideDur = dev.f("backdrop.slideDur.\(m)", 1.05)
        // Reset both timelines WITHOUT animation (reusing the already-decoded
        // outgoing image), then run them on their own curves: fade is the quicker
        // staggered dissolve; slide is the slower ease-out parallax.
        var reset = Transaction(); reset.disablesAnimations = true
        withTransaction(reset) {
            outgoingImage = frontImage
            frontImage = img
            frontURL = url
            fadeT = 0
            slideT = 0
        }
        withAnimation(.linear(duration: fadeDur)) { fadeT = 1 }
        // The slide is the longer leg, so clear the spent outgoing layer when it
        // finishes (its opacity already hit 0 when the fade completed).
        withAnimation(.easeOut(duration: slideDur)) { slideT = 1 } completion: { outgoingImage = nil }
    }

    // MARK: Fade curves (fadeT 0 → 1)

    /// Incoming ramps to full quickly (full by ~0.55) so it backs the outgoing
    /// before that one fades — no midpoint coverage dip.
    private func incomingOpacity(_ t: Double) -> Double { smoothstep(0, 0.55, t) }

    /// Outgoing holds opaque briefly, then fades out over the back half.
    private func outgoingOpacity(_ t: Double) -> Double { 1 - smoothstep(0.18, 1, t) }
}

// MARK: - Small interpolation helpers

private func lerp(_ a: CGFloat, _ b: CGFloat, _ t: Double) -> CGFloat {
    a + (b - a) * CGFloat(t)
}

private func smoothstep(_ e0: Double, _ e1: Double, _ x: Double) -> Double {
    let t = min(max((x - e0) / (e1 - e0), 0), 1)
    return t * t * (3 - 2 * t)
}
