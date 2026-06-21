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
    var cardTint: Color        // outer card background tint (web --art-card-tint)
    var innerSurface: Color    // floating rows sub-card bg (web --art-inner-surface)
    var trackTint: Color

    /// Neutral palette for idle / no-art / extraction-failed cards.
    static let neutral = ArtPalette(
        accent: FX.text,
        accentSoft: FX.surface3,
        cardTint: FX.surface1,
        innerSurface: FX.surface1,
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
    static let innerSurfaceLDark = 0.19
}

/// Project a raw extracted OKLCH color onto a card-ready palette.
///
/// FX-77: every knob reads from `DevControl` with a MODE-SCOPED key
/// (`<base>.dark` / `<base>.light`), so a Mac tuning page can dial dark and
/// light independently and live; release falls back to the baked defaults
/// below (dark = the values the user dialed in 2026-06-03, light = the prior
/// look). The former OKLCH min/max clamp bands collapse to single values:
/// lightness is a fixed target, chroma a single ceiling (`min(source, cap)`)
/// so saturated covers cap while neutral covers stay muted.
///
/// The media tint and the device sub-card tint are INDEPENDENT — each its own
/// lightness + chroma — so the device portion can read differently from the
/// outer card. chroma 0 yields a neutral gray (tint via lightness + the card's
/// fill transparency only); chroma > 0 an actual album tint. Light mode
/// defaults to a white device sub-card.
func buildArtPalette(from raw: OKLCH, dark: Bool) -> ArtPalette {
    let dev = DevControl.shared
    let m = dark ? "dark" : "light"
    func k(_ base: String, _ fallback: Double) -> Double { dev.d("\(base).\(m)", fallback) }

    let accentL = k("accent.lightness", dark ? 0.81 : 0.64)
    let accentC = min(raw.c, k("accent.chroma", dark ? 0.13 : 0.105))
    let trackA  = k("track.alpha", dark ? 0.125 : 0.19)

    let mediaL  = k("media.lightness", dark ? 0.315 : 1.0)
    let mediaC  = min(raw.c, k("media.chroma", dark ? 0.03 : 0.025))
    let deviceL = k("device.lightness", dark ? 0.21 : 1.0)     // light: white
    let deviceC = min(raw.c, k("device.chroma", 0.0))          // neutral gray both modes

    let accent = OKLCH(l: accentL, c: accentC, h: raw.h)
    return ArtPalette(
        accent: oklchToColor(accent),
        accentSoft: oklchToColor(accent, alpha: dark ? 0.18 : 0.10),
        cardTint: oklchToColor(OKLCH(l: mediaL, c: mediaC, h: raw.h)),
        innerSurface: oklchToColor(OKLCH(l: deviceL, c: deviceC, h: raw.h)),
        trackTint: oklchToColor(accent, alpha: trackA)
    )
}

// MARK: - Dominant color + average brightness, extracted from a UIImage

/// One downscaled pixel pass over the cover yields two independent signals:
///   • `dominant` — the most-saturated hue bucket (the card accent); nil for
///     near-grayscale covers, exactly as before.
///   • `avgLuma`  — the mean Rec.601 luma over all opaque pixels (0…1), used to
///     decide whether the blurred backdrop behind the nav bar is light or dark
///     so the wordmark can flip white↔dark for contrast (FX-80). Always present.
struct ArtAnalysis: Equatable {
    var dominant: OKLCH?
    var avgLuma: Double
}

private func analyze(_ image: UIImage) -> ArtAnalysis? {
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
    var lumaSum = 0.0, lumaCount = 0

    var i = 0
    while i < data.count {
        let alpha = data[i + 3]
        if alpha >= 200 {
            let r = Double(data[i]) / 255, g = Double(data[i + 1]) / 255, b = Double(data[i + 2]) / 255
            // Perceptual luma over every opaque pixel (incl. grays) — the backdrop
            // brightness estimate, in the same sRGB space the backdrop composites in.
            lumaSum += 0.299 * r + 0.587 * g + 0.114 * b
            lumaCount += 1
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

    let avgLuma = lumaCount > 0 ? lumaSum / Double(lumaCount) : 0

    var bestIdx = -1, bestScore = 0.0
    for (idx, b) in buckets.enumerated() where b.sumC > bestScore {
        bestScore = b.sumC; bestIdx = idx
    }
    let dominant: OKLCH? = bestIdx >= 0 ? {
        let b = buckets[bestIdx]
        return OKLCH(l: b.sumL / Double(b.count), c: b.sumC / Double(b.count), h: b.sumH / Double(b.count))
    }() : nil
    return ArtAnalysis(dominant: dominant, avgLuma: avgLuma)
}

// MARK: - Async loader / cache

/// Loads album art and extracts its dominant OKLCH color, memoized by URL so
/// identical covers across cards extract once. Mirrors the web hook's
/// module-level cache. UIImage download + pixel work runs off the main actor.
@MainActor
final class AlbumArtColorStore: ObservableObject {
    static let shared = AlbumArtColorStore()

    @Published private(set) var colors: [String: OKLCH] = [:]
    /// Average cover brightness (0…1), keyed by URL — present whenever a cover
    /// decoded, even for grayscale covers that yield no dominant hue (FX-80).
    @Published private(set) var lumas: [String: Double] = [:]
    private var inFlight: Set<String> = []
    private var failed: Set<String> = []

    func color(for urlString: String?) -> OKLCH? {
        guard let urlString else { return nil }
        return colors[urlString]
    }

    /// Average cover brightness for `urlString`, once extracted (nil while loading).
    func luma(for urlString: String?) -> Double? {
        guard let urlString else { return nil }
        return lumas[urlString]
    }

    /// Kick off extraction for `urlString` if we haven't already. Idempotent.
    func ensure(_ urlString: String?) {
        guard let urlString, let url = URL(string: urlString) else { return }
        if lumas[urlString] != nil || colors[urlString] != nil || inFlight.contains(urlString) || failed.contains(urlString) { return }
        inFlight.insert(urlString)
        Task.detached(priority: .utility) {
            let analysis: ArtAnalysis? = await {
                guard let (data, _) = try? await URLSession.shared.data(from: url),
                      let img = UIImage(data: data) else { return nil }
                return analyze(img)
            }()
            await self.store(analysis, for: urlString)
        }
    }

    private func store(_ analysis: ArtAnalysis?, for urlString: String) {
        inFlight.remove(urlString)
        guard let analysis else { failed.insert(urlString); return }
        // Brightness is always recorded; a missing dominant hue just leaves the
        // card neutral (the `colors` lookup), but the backdrop is still measured.
        lumas[urlString] = analysis.avgLuma
        if let dominant = analysis.dominant { colors[urlString] = dominant }
    }
}

#if DEBUG
extension AlbumArtColorStore {
    /// Pre-seed extracted colors for Xcode Previews so cards theme instantly and
    /// deterministically — no network, no async extraction. Seeded URLs also make
    /// `ensure(_:)` a no-op (it early-returns when a color already exists), so the
    /// injected hue sticks. In-file because `colors` is `private(set)`.
    func preloadForPreview(_ map: [String: OKLCH]) {
        for (url, color) in map { colors[url] = color }
    }
}
#endif
