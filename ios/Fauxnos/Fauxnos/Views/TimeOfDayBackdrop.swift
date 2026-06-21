//
//  TimeOfDayBackdrop.swift
//  Fauxnos
//
//  FX-87: the null-state "cover". When nothing is playing there's no album art
//  to blur, so we GENERATE a stand-in cover whose colors are derived from the
//  current time of day in PST — deep navy at night, amber/peach at dawn, pale
//  cool blue at midday, orange→magenta→purple at dusk. Crucially it's rendered
//  to a real raster `UIImage` (a multi-hue, flowing, diagonal composition, not a
//  single fade) and then handed to `BlurArtBackdrop` as a `.generated` source —
//  so it goes through the *exact same* scale → blur → fade-mask → opacity path
//  as a real cover, and even crossfades (FX-79 slide+fade) when a track starts
//  and the real art overtakes it.
//
//  Two pieces:
//    • `TimeOfDayPalette` — interpolates between anchor "sky" palettes spaced
//      around the clock, so the hue glides through the day. `topLuma` feeds the
//      wordmark's contrast flip (FX-80) exactly as a cover's average luma does.
//    • `TimeOfDayArt` — paints the palette into a flowing diagonal field of
//      overlapping color blobs (Core Graphics), cached per hour-bucket + mode.
//

import SwiftUI
import UIKit

// MARK: - Clock

/// Hour-of-day (0…24, fractional) in PST. The null-state palette is referential
/// of *local listening time*, so it's pinned to America/Los_Angeles regardless
/// of the device's own timezone.
private func pstHour(_ date: Date) -> Double {
    var cal = Calendar(identifier: .gregorian)
    cal.timeZone = TimeZone(identifier: "America/Los_Angeles") ?? .current
    let p = cal.dateComponents([.hour, .minute], from: date)
    return Double(p.hour ?? 0) + Double(p.minute ?? 0) / 60.0
}

// MARK: - Palette

/// A time-of-day color set (multi-hue, warm+cool) plus an approximate
/// "behind the nav bar" luma for the wordmark's contrast decision.
struct TimeOfDayPalette {
    /// RGB blobs in 0…1, brightest/most-prominent first; the last is the base.
    let rgb: [(r: Double, g: Double, b: Double)]

    var colors: [Color] { rgb.map { Color(.sRGB, red: $0.r, green: $0.g, blue: $0.b) } }
    var uiColors: [UIColor] { rgb.map { UIColor(red: $0.r, green: $0.g, blue: $0.b, alpha: 1) } }

    /// Approx luma of the region behind the nav bar (top of the screen), 0…1.
    /// The top is dominated by the first blob over the field, so weight it there.
    var topLuma: Double {
        let mean = rgb.map(Self.luma).reduce(0, +) / Double(rgb.count)
        return 0.6 * Self.luma(rgb[0]) + 0.4 * mean
    }

    /// Anchor palettes around the 24h clock (local PST hour). Each is five RGB
    /// hues — deliberately mixing warm and cool so the blurred field has real
    /// color contrast (like the reference wallpapers), not a single tint. Hour 24
    /// repeats hour 0 so the wrap stays continuous.
    private static let anchors: [(hour: Double, rgb: [(r: Double, g: Double, b: Double)])] = [
        (0,  [(0.106, 0.165, 0.420), (0.227, 0.122, 0.369), (0.078, 0.188, 0.247), (0.043, 0.063, 0.200), (0.020, 0.024, 0.059)]),  // deep night
        (5,  [(0.294, 0.165, 0.400), (0.478, 0.227, 0.420), (0.612, 0.353, 0.431), (0.141, 0.102, 0.302), (0.086, 0.106, 0.251)]),  // pre-dawn violet
        (7,  [(0.941, 0.639, 0.369), (0.969, 0.765, 0.604), (0.910, 0.353, 0.549), (0.478, 0.290, 0.612), (0.227, 0.290, 0.549)]),  // dawn amber/peach/magenta
        (10, [(0.428, 0.690, 0.910), (0.624, 0.847, 0.941), (0.902, 0.949, 0.980), (0.941, 0.824, 0.604), (0.725, 0.659, 0.878)]),  // bright morning
        (13, [(0.353, 0.651, 0.910), (0.682, 0.878, 0.961), (0.949, 0.973, 0.988), (0.961, 0.902, 0.753), (0.812, 0.839, 0.941)]),  // pale midday sky
        (17, [(0.961, 0.722, 0.369), (0.941, 0.537, 0.290), (0.925, 0.416, 0.525), (0.969, 0.863, 0.682), (0.604, 0.416, 0.627)]),  // golden afternoon
        (19, [(0.941, 0.478, 0.227), (0.910, 0.290, 0.549), (0.761, 0.227, 0.620), (0.369, 0.165, 0.549), (0.165, 0.137, 0.388)]),  // dusk orange→magenta
        (21, [(0.639, 0.227, 0.549), (0.431, 0.165, 0.549), (0.165, 0.165, 0.420), (0.106, 0.094, 0.271), (0.043, 0.039, 0.141)]),  // twilight purple
        (24, [(0.106, 0.165, 0.420), (0.227, 0.122, 0.369), (0.078, 0.188, 0.247), (0.043, 0.063, 0.200), (0.020, 0.024, 0.059)]),  // == hour 0 (wrap)
    ]

    /// Interpolated palette at an explicit fractional hour.
    static func at(hour h: Double) -> TimeOfDayPalette {
        var a = anchors[0], b = anchors[anchors.count - 1]
        for i in 0..<(anchors.count - 1) where h >= anchors[i].hour && h < anchors[i + 1].hour {
            a = anchors[i]; b = anchors[i + 1]; break
        }
        let span = max(b.hour - a.hour, 0.0001)
        let t = min(max((h - a.hour) / span, 0), 1)
        let n = min(a.rgb.count, b.rgb.count)
        let rgb = (0..<n).map { i -> (r: Double, g: Double, b: Double) in
            (lerp(a.rgb[i].r, b.rgb[i].r, t),
             lerp(a.rgb[i].g, b.rgb[i].g, t),
             lerp(a.rgb[i].b, b.rgb[i].b, t))
        }
        return TimeOfDayPalette(rgb: rgb)
    }

    /// Palette for the current PST wall-clock time (smooth, for the wordmark).
    static func current(_ now: Date = Date()) -> TimeOfDayPalette { at(hour: pstHour(now)) }

    private static func luma(_ c: (r: Double, g: Double, b: Double)) -> Double {
        0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b
    }
    private static func lerp(_ x: Double, _ y: Double, _ t: Double) -> Double { x + (y - x) * t }
}

// MARK: - Generated art

/// Paints the time-of-day palette into a flowing, multi-hue raster "cover" that
/// `BlurArtBackdrop` then treats exactly like an album cover. Cached per
/// hour-bucket + color mode so it renders once and the hourly change reads as a
/// gentle cover swap.
enum TimeOfDayArt {
    /// Portrait canvas. Small is fine — it's scaled up and heavily blurred, so
    /// detail is wasted; this keeps the one-time CG render cheap.
    private static let canvas = CGSize(width: 720, height: 1280)
    private static var cache: [String: UIImage] = [:]

    /// The generated cover for the current PST time, plus a stable key (changes
    /// only when the hour bucket or mode changes — so it doesn't thrash the
    /// crossfade machinery on every render).
    static func current(date: Date = Date(), dark: Bool) -> (image: UIImage, key: String) {
        let bucket = Int(pstHour(date).rounded(.down))
        let key = "h\(bucket)-\(dark ? "d" : "l")"
        if let img = cache[key] { return (img, key) }
        let pal = TimeOfDayPalette.at(hour: Double(bucket) + 0.5)   // mid-bucket hue
        let img = render(pal, hour: Double(bucket))
        cache[key] = img
        return (img, key)
    }

    private static func render(_ pal: TimeOfDayPalette, hour: Double) -> UIImage {
        let size = canvas
        let fmt = UIGraphicsImageRendererFormat.default()
        fmt.opaque = true
        fmt.scale = 1
        return UIGraphicsImageRenderer(size: size, format: fmt).image { rctx in
            let cg = rctx.cgContext
            let cs = CGColorSpaceCreateDeviceRGB()
            let cols = pal.uiColors
            let maxDim = Double(max(size.width, size.height))

            // Solid darkest base so any feathered edge has something behind it.
            cols[cols.count - 1].setFill()
            cg.fill(CGRect(origin: .zero, size: size))

            // The field is a band of diagonal color stripes: a single multi-stop
            // gradient whose stops cycle the palette in an INTERLEAVED order
            // (warm → deep → accent → light → cool …) so neighbouring bands always
            // contrast. Running it on a diagonal means any crop (scaledToFill +
            // the 1.25 zoom) still cuts across several hues — that's what keeps it
            // multi-color everywhere, like the reference wallpapers, instead of a
            // single tint. The angle wobbles slightly by the hour.
            let order = [0, 4, 2, 1, 3, 0, 4, 2]              // interleaved hues
            let bandColors = order.map { cols[$0 % cols.count] }
            // Slightly uneven stop spacing → organic band widths (not a ruler).
            let locs = (0..<bandColors.count).map { i -> CGFloat in
                let base = Double(i) / Double(bandColors.count - 1)
                return CGFloat(min(max(base + sin(Double(i) * 2.3 + hour) * 0.035, 0), 1))
            }
            drawBands(cg, cs: cs, size: size, colors: bandColors,
                      locations: locs, angleDeg: 118 + sin(hour * 0.5) * 8)

            // A couple of broad radial accents bend the straight bands into a
            // softer, flowing wave once blurred (and add depth top vs. bottom).
            drawRadial(cg, cs: cs,
                       center: CGPoint(x: 0.22 * Double(size.width), y: 0.14 * Double(size.height)),
                       radius: CGFloat(maxDim * 0.85),
                       color: cols[0].withAlphaComponent(0.55))
            drawRadial(cg, cs: cs,
                       center: CGPoint(x: 0.82 * Double(size.width), y: 0.66 * Double(size.height)),
                       radius: CGFloat(maxDim * 0.80),
                       color: cols[min(4, cols.count - 1)].withAlphaComponent(0.55))
        }
    }

    /// A multi-stop linear gradient (the diagonal color bands) drawn corner to
    /// corner at `angleDeg`. The line is long enough (1.4×) that the angled
    /// gradient still covers the whole canvas.
    private static func drawBands(_ cg: CGContext, cs: CGColorSpace, size: CGSize,
                                  colors: [UIColor], locations: [CGFloat], angleDeg: Double) {
        guard let grad = CGGradient(colorsSpace: cs,
                                    colors: colors.map { $0.cgColor } as CFArray,
                                    locations: locations) else { return }
        let a = angleDeg * .pi / 180
        let dx = CGFloat(cos(a)), dy = CGFloat(sin(a))
        let c = CGPoint(x: size.width / 2, y: size.height / 2)
        let half = max(size.width, size.height) * 1.4
        cg.drawLinearGradient(grad,
                              start: CGPoint(x: c.x - dx * half, y: c.y - dy * half),
                              end: CGPoint(x: c.x + dx * half, y: c.y + dy * half),
                              options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])
    }

    private static func drawRadial(_ cg: CGContext, cs: CGColorSpace, center: CGPoint,
                                   radius: CGFloat, color: UIColor) {
        guard let grad = CGGradient(colorsSpace: cs,
                                    colors: [color.cgColor, color.withAlphaComponent(0).cgColor] as CFArray,
                                    locations: [0, 1]) else { return }
        cg.drawRadialGradient(grad, startCenter: center, startRadius: 0,
                              endCenter: center, endRadius: radius, options: [])
    }
}
