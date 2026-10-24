//
//  NoiseArt.swift
//  Fauxnos
//
//  Generated "album art" for the Noise source — the iOS port of the web's
//  lib/noiseArt.js: a gradient square in the colour's shades, soft highlights
//  and shadows in the corners, and the wave-sine glyph in the middle. Rendered
//  once per colour to a PNG in Caches and handed out as a file:// URL string,
//  so it runs through exactly the same path as a Spotify cover: the card's
//  FlippingAlbumArt, AlbumArtColorStore's tint, and the blurred backdrop.
//

import UIKit

enum NoiseArt {
    private struct Look {
        let from: UIColor, to: UIColor
        /// (corner, colour, strength); corners: 0 tl, 1 tr, 2 bl, 3 br.
        let glows: [(Int, UIColor, CGFloat)]
        let glyph: UIColor
    }

    // Same shades as the web. White is a cool pearl rather than pure grey so
    // the art tint has a hue to pick up.
    private static let looks: [String: Look] = [
        "brown": Look(from: UIColor(rgb: 0xA8734A), to: UIColor(rgb: 0x3B2314),
                      glows: [(0, UIColor(rgb: 0xE6C39C), 0.65), (3, UIColor(rgb: 0x160C06), 0.7), (1, UIColor(rgb: 0xC2652F), 0.35)],
                      glyph: UIColor(red: 1, green: 0.957, blue: 0.91, alpha: 0.92)),
        "pink": Look(from: UIColor(rgb: 0xF2A3C0), to: UIColor(rgb: 0x7E2B55),
                     glows: [(1, UIColor(rgb: 0xFFE2EC), 0.7), (2, UIColor(rgb: 0x3A0F25), 0.6), (0, UIColor(rgb: 0xE0607F), 0.3)],
                     glyph: UIColor(red: 1, green: 0.96, blue: 0.976, alpha: 0.94)),
        "white": Look(from: UIColor(rgb: 0xF4F6FC), to: UIColor(rgb: 0x9AA4C4),
                      glows: [(0, UIColor(rgb: 0xFFFFFF), 0.8), (3, UIColor(rgb: 0x5E6786), 0.55), (2, UIColor(rgb: 0xC9CFE6), 0.4)],
                      glyph: UIColor(red: 0.204, green: 0.227, blue: 0.314, alpha: 0.85)),
    ]

    private static var cache: [String: String] = [:]

    /// file:// URL string of the art for a noise colour (white / pink / brown).
    static func urlString(for color: String?) -> String {
        let key = looks[color ?? ""] != nil ? color! : "brown"
        if let hit = cache[key] { return hit }
        let url = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("fx_noise_\(key)_v1.png")
        if !FileManager.default.fileExists(atPath: url.path),
           let data = render(looks[key]!).pngData() {
            try? data.write(to: url)
        }
        cache[key] = url.absoluteString
        return url.absoluteString
    }

    private static func render(_ look: Look) -> UIImage {
        let size: CGFloat = 512
        return UIGraphicsImageRenderer(size: CGSize(width: size, height: size)).image { ctx in
            let cg = ctx.cgContext
            let space = CGColorSpaceCreateDeviceRGB()
            if let base = CGGradient(colorsSpace: space, colors: [look.from.cgColor, look.to.cgColor] as CFArray, locations: [0, 1]) {
                cg.drawLinearGradient(base, start: .zero, end: CGPoint(x: size, y: size), options: [])
            }
            let corners = [CGPoint(x: 0, y: 0), CGPoint(x: size, y: 0), CGPoint(x: 0, y: size), CGPoint(x: size, y: size)]
            for (corner, color, strength) in look.glows {
                let glow = CGGradient(colorsSpace: space,
                                      colors: [color.withAlphaComponent(strength).cgColor, color.withAlphaComponent(0).cgColor] as CFArray,
                                      locations: [0, 1])!
                let p = corners[corner]
                cg.drawRadialGradient(glow, startCenter: p, startRadius: 0, endCenter: p, endRadius: size * 0.8, options: [])
            }
            // Tabler's outline wave-sine (24×24 viewBox), converted from its SVG
            // path to absolute curves, drawn at ~40% of the tile.
            let scale = size * 0.4 / 24
            cg.translateBy(x: size / 2 - 12 * scale, y: size / 2 - 12 * scale)
            cg.scaleBy(x: scale, y: scale)
            let wave = UIBezierPath()
            wave.move(to: CGPoint(x: 21, y: 12))
            wave.addLine(to: CGPoint(x: 19, y: 12))
            wave.addCurve(to: CGPoint(x: 17.239, y: 10), controlPoint1: CGPoint(x: 18.106, y: 12), controlPoint2: CGPoint(x: 17.338, y: 11.143))
            wave.addCurve(to: CGPoint(x: 14.49, y: 4), controlPoint1: CGPoint(x: 16.943, y: 6.55), controlPoint2: CGPoint(x: 16.49, y: 4))
            wave.addCurve(to: CGPoint(x: 11.99, y: 12), controlPoint1: CGPoint(x: 12.49, y: 4), controlPoint2: CGPoint(x: 11.99, y: 7.582))
            wave.addCurve(to: CGPoint(x: 9.49, y: 20), controlPoint1: CGPoint(x: 11.99, y: 16.418), controlPoint2: CGPoint(x: 11.49, y: 20))
            wave.addCurve(to: CGPoint(x: 6.741, y: 14), controlPoint1: CGPoint(x: 7.49, y: 20), controlPoint2: CGPoint(x: 7.038, y: 17.453))
            wave.addCurve(to: CGPoint(x: 4.978, y: 12), controlPoint1: CGPoint(x: 6.641, y: 12.853), controlPoint2: CGPoint(x: 5.874, y: 12))
            wave.addLine(to: CGPoint(x: 2.978, y: 12))
            wave.lineWidth = 2
            wave.lineCapStyle = .round
            wave.lineJoinStyle = .round
            look.glyph.setStroke()
            wave.stroke()
        }
    }
}
