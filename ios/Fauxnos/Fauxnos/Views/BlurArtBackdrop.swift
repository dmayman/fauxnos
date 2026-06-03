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

    var body: some View {
        GeometryReader { geo in
            ZStack {
                AsyncImage(url: url) { phase in
                    if case .success(let image) = phase {
                        image
                            .resizable()
                            .scaledToFill()
                            .frame(width: geo.size.width, height: geo.size.height)
                            .scaleEffect(dev.f("backdrop.scale", 1.3))
                            .blur(radius: dev.f("backdrop.blur", 60))
                            .opacity(dev.d("backdrop.opacity", 0.85))
                    }
                }
                .frame(width: geo.size.width, height: geo.size.height)
                .clipped()
                .mask(
                    LinearGradient(
                        stops: [
                            .init(color: .black, location: dev.f("backdrop.fadeStart", 0.0)),
                            .init(color: .clear,
                                  location: max(dev.f("backdrop.fadeEnd", 0.7),
                                                dev.f("backdrop.fadeStart", 0.0) + 0.01)),
                        ],
                        startPoint: .top, endPoint: .bottom
                    )
                )
                // Optional dark scrim over the art for extra card legibility.
                Color.black.opacity(dev.d("backdrop.scrim", 0.0))
            }
        }
        // Fade between covers when the playing track (or the dev album chooser)
        // changes, so the backdrop crossfades rather than hard-cutting.
        .id(url)
        .transition(.opacity)
        .allowsHitTesting(false)
    }
}
