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
//  Every knob reads from `DevControl` with a baked fallback, so a Mac tuning
//  page can dial the look live in DEBUG while release builds use the constants
//  below. The defaults below are the candidate shipping values.
//

import SwiftUI

struct BlurArtBackdrop: View {
    let url: URL
    @ObservedObject private var dev = DevControl.shared
    @Environment(\.colorScheme) private var colorScheme

    // FX-77: backdrop knobs are mode-scoped (`<base>.dark` / `<base>.light`).
    // Dark defaults are the values dialed in 2026-06-03; light mirrors them
    // until tuned separately.
    private var m: String { colorScheme == .dark ? "dark" : "light" }

    var body: some View {
        let fadeStart = dev.f("backdrop.fadeStart.\(m)", 0.0)
        return GeometryReader { geo in
            ZStack {
                AsyncImage(url: url) { phase in
                    if case .success(let image) = phase {
                        image
                            .resizable()
                            .scaledToFill()
                            .frame(width: geo.size.width, height: geo.size.height)
                            .scaleEffect(dev.f("backdrop.scale.\(m)", 1.25))
                            .blur(radius: dev.f("backdrop.blur.\(m)", 52))
                            .opacity(dev.d("backdrop.opacity.\(m)", colorScheme == .dark ? 0.79 : 0.74))
                    }
                }
                .frame(width: geo.size.width, height: geo.size.height)
                .clipped()
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
                // Optional dark scrim over the art for extra card legibility.
                Color.black.opacity(dev.d("backdrop.scrim.\(m)", 0.0))
            }
        }
        // Fade between covers when the playing track (or the dev album chooser)
        // changes, so the backdrop crossfades rather than hard-cutting.
        .id(url)
        .transition(.opacity)
        .allowsHitTesting(false)
    }
}
