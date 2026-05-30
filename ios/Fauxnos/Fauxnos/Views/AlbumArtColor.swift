//
//  AlbumArtColor.swift
//  Fauxnos
//
//  The album-art-derived accent system — the web UI's signature visual move,
//  ported natively (FX-33). Each playing card tints itself from the dominant
//  hue of its album art: the accent drives meta text, the progress fill, the
//  play button, and the slider tints; a muted shade of the same hue tints the
//  card background. Idle / no-art cards stay neutral.
//
//  The extraction mirrors `useAlbumArtColor.js` exactly — downscale to 32×32,
//  bin pixels into 36 hue buckets in OKLCH, pick the highest sum-of-chroma
//  bucket ("most-saturated dominant hue", robust against near-gray covers and
//  outliers). The OKLCH→clamp→sRGB projection mirrors `buildArtTokens` with the
//  baked 2026-05-25 tuning constants, so the iOS tint matches web byte-for-byte
//  in intent.
//

import SwiftUI
import UIKit

// MARK: - Raw extracted color (OKLCH)

struct OKLCH: Equatable {
    var l: Double   // 0…1
    var c: Double   // 0…~0.4
    var h: Double   // 0…360
}

// MARK: - Projected palette a card consumes

/// The handful of colors a tinted card actually paints with, already clamped
/// for legibility against the active appearance. `nil`-free: callers that have
/// no art fall back to `.neutral`.
struct ArtPalette: Equatable {
    var accent: Color
    var accentSoft: Color
    var cardTint: Color
    var trackTint: Color

    /// Neutral palette for idle / no-art / extraction-failed cards.
    static let neutral = ArtPalette(
        accent: FX.text,
        accentSoft: FX.surface3,
        cardTint: FX.surface2,
        trackTint: FX.surface3
    )
}

// MARK: - Color math (sRGB ↔ OKLab/OKLCH), from Björn Ottosson

private func srgbToLinear(_ c: Double) -> Double {
    c <= 0.04045 ? c / 12.92 : pow((c + 0.055) / 1.055, 2.4)
}
private func linearToSrgb(_ c: Double) -> Double {
    let v = c <= 0.0031308 ? c * 12.92 : 1.055 * pow(c, 1 / 2.4) - 0.055
    return min(1, max(0, v))
}

private func rgbToOklch(_ r: Double, _ g: Double, _ b: Double) -> OKLCH {
    let lr = srgbToLinear(r), lg = srgbToLinear(g), lb = srgbToLinear(b)
    let l_ = cbrt(0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb)
    let m_ = cbrt(0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb)
    let s_ = cbrt(0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb)
    let L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    let a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    let bb = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    let C = (a * a + bb * bb).squareRoot()
    var h = atan2(bb, a) * 180 / .pi
    if h < 0 { h += 360 }
    return OKLCH(l: L, c: C, h: h)
}

private func oklchToColor(_ o: OKLCH, alpha: Double = 1) -> Color {
    let hr = o.h * .pi / 180
    let a = o.c * cos(hr), b = o.c * sin(hr)
    let l_ = o.l + 0.3963377774 * a + 0.2158037573 * b
    let m_ = o.l - 0.1055613458 * a - 0.0638541728 * b
    let s_ = o.l - 0.0894841775 * a - 1.2914855480 * b
    let l = l_ * l_ * l_, m = m_ * m_ * m_, s = s_ * s_ * s_
    let r = linearToSrgb( 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s)
    let g = linearToSrgb(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s)
    let bl = linearToSrgb(-0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)
    return Color(.sRGB, red: r, green: g, blue: bl, opacity: alpha)
}

// MARK: - Baked tuning (web DEFAULT_TUNING, dialed 2026-05-25)

private enum Tune {
    static let cardTintLDark = 0.33, cardTintCminDark = 0.005, cardTintCmaxDark = 0.035
    static let cardTintLLight = 0.95, cardTintCminLight = 0.0, cardTintCmaxLight = 0.025
    static let accentLminDark = 0.77, accentLmaxDark = 0.85
    static let accentLminLight = 0.69, accentLmaxLight = 0.70
    static let accentCmin = 0.075, accentCmax = 0.11
    static let trackAlphaDark = 0.12, trackAlphaLight = 0.19
}

private func clamp(_ lo: Double, _ v: Double, _ hi: Double) -> Double { max(lo, min(hi, v)) }

/// Project a raw extracted OKLCH color onto a card-ready palette, applying the
/// mode-specific legibility clamps. Mirrors `buildArtTokens`.
func buildArtPalette(from raw: OKLCH, dark: Bool) -> ArtPalette {
    if dark {
        let accentL = clamp(Tune.accentLminDark, raw.l, Tune.accentLmaxDark)
        let accentC = clamp(Tune.accentCmin, raw.c, Tune.accentCmax)
        let tintC = clamp(Tune.cardTintCminDark, raw.c, Tune.cardTintCmaxDark)
        let accent = OKLCH(l: accentL, c: accentC, h: raw.h)
        return ArtPalette(
            accent: oklchToColor(accent),
            accentSoft: oklchToColor(accent, alpha: 0.18),
            cardTint: oklchToColor(OKLCH(l: Tune.cardTintLDark, c: tintC, h: raw.h)),
            trackTint: oklchToColor(accent, alpha: Tune.trackAlphaDark)
        )
    }
    let accentL = clamp(Tune.accentLminLight, raw.l, Tune.accentLmaxLight)
    let accentC = clamp(Tune.accentCmin, raw.c, Tune.accentCmax)
    let tintC = clamp(Tune.cardTintCminLight, raw.c, Tune.cardTintCmaxLight)
    let accent = OKLCH(l: accentL, c: accentC, h: raw.h)
    return ArtPalette(
        accent: oklchToColor(accent),
        accentSoft: oklchToColor(accent, alpha: 0.10),
        cardTint: oklchToColor(OKLCH(l: Tune.cardTintLLight, c: tintC, h: raw.h)),
        trackTint: oklchToColor(accent, alpha: Tune.trackAlphaLight)
    )
}

// MARK: - Dominant-color extraction from a UIImage

/// Downscale to 32×32, histogram pixels into 36 hue buckets, return the bucket
/// with the highest summed chroma. Returns nil for near-grayscale covers.
private func extractDominant(from image: UIImage) -> OKLCH? {
    let sz = 32
    guard let cg = image.cgImage else { return nil }
    let space = CGColorSpaceCreateDeviceRGB()
    var data = [UInt8](repeating: 0, count: sz * sz * 4)
    guard let ctx = CGContext(
        data: &data, width: sz, height: sz, bitsPerComponent: 8, bytesPerRow: sz * 4,
        space: space, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
    ) else { return nil }
    ctx.draw(cg, in: CGRect(x: 0, y: 0, width: sz, height: sz))

    var buckets = [(count: Int, sumC: Double, sumL: Double, sumH: Double)](
        repeating: (0, 0, 0, 0), count: 36)

    var i = 0
    while i < data.count {
        let alpha = data[i + 3]
        if alpha >= 200 {
            let r = Double(data[i]) / 255, g = Double(data[i + 1]) / 255, b = Double(data[i + 2]) / 255
            let o = rgbToOklch(r, g, b)
            if o.c >= 0.04, o.l > 0.1, o.l < 0.95 {     // skip near-gray + cover edges
                let bin = Int(o.h / 10) % 36
                buckets[bin].count += 1
                buckets[bin].sumC += o.c
                buckets[bin].sumL += o.l
                buckets[bin].sumH += o.h
            }
        }
        i += 4
    }

    var bestIdx = -1, bestScore = 0.0
    for (idx, b) in buckets.enumerated() where b.sumC > bestScore {
        bestScore = b.sumC; bestIdx = idx
    }
    guard bestIdx >= 0 else { return nil }
    let b = buckets[bestIdx]
    return OKLCH(l: b.sumL / Double(b.count), c: b.sumC / Double(b.count), h: b.sumH / Double(b.count))
}

// MARK: - Async loader / cache

/// Loads album art and extracts its dominant OKLCH color, memoized by URL so
/// identical covers across cards extract once. Mirrors the web hook's
/// module-level cache. UIImage download + pixel work runs off the main actor.
@MainActor
final class AlbumArtColorStore: ObservableObject {
    static let shared = AlbumArtColorStore()

    @Published private(set) var colors: [String: OKLCH] = [:]
    private var inFlight: Set<String> = []
    private var failed: Set<String> = []

    func color(for urlString: String?) -> OKLCH? {
        guard let urlString else { return nil }
        return colors[urlString]
    }

    /// Kick off extraction for `urlString` if we haven't already. Idempotent.
    func ensure(_ urlString: String?) {
        guard let urlString, let url = URL(string: urlString) else { return }
        if colors[urlString] != nil || inFlight.contains(urlString) || failed.contains(urlString) { return }
        inFlight.insert(urlString)
        Task.detached(priority: .utility) {
            let extracted: OKLCH? = await {
                guard let (data, _) = try? await URLSession.shared.data(from: url),
                      let img = UIImage(data: data) else { return nil }
                return extractDominant(from: img)
            }()
            await self.store(extracted, for: urlString)
        }
    }

    private func store(_ color: OKLCH?, for urlString: String) {
        inFlight.remove(urlString)
        if let color { colors[urlString] = color } else { failed.insert(urlString) }
    }
}
