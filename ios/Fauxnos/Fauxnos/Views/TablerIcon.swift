//
//  TablerIcon.swift
//  Fauxnos
//
//  The Tabler icon set, matching the web UI (which uses @tabler/icons-react,
//  pinned at 3.44.0). Rather than bundle hundreds of SVGs, we ship the two
//  Tabler webfonts — `tabler-icons.ttf` (outline) and `tabler-icons-filled.ttf`
//  (filled) — and render each icon as its glyph by Unicode codepoint, exactly
//  the way the web's `@tabler/icons-webfont` CSS does. The filled font's
//  internal family was renamed to `tabler-icons-filled` so the two can be
//  addressed independently (both ship with the same `tabler-icons` family name
//  upstream). Fonts are registered at launch — see AppFonts.register().
//
//  Codepoints below are lifted from Tabler 3.44.0's `tabler-icons.css` /
//  `tabler-icons-filled.css`. The card uses the same `*Filled` variants the web
//  imports; volume + unlink exist only as outline glyphs upstream.
//

import SwiftUI

struct TablerIcon: View {
    enum Glyph {
        // Filled (tabler-icons-filled)
        case brandSpotify, play, pause, trackPrev, trackNext
        case chevronDown, microphone, broadcastTower, externalLink, headphones, x, home
        // Outline (tabler-icons)
        case volumeHigh, volumeLow, volumeOff, unlink

        var codepoint: UInt32 {
            switch self {
            case .brandSpotify:   return 0xfe86
            case .play:           return 0xf691
            case .pause:          return 0xf690
            case .trackPrev:      return 0xf697
            case .trackNext:      return 0xf696
            case .chevronDown:    return 0x101e5
            case .microphone:     return 0xfe0f
            case .broadcastTower: return 0xfe81
            case .externalLink:   return 0x101da
            case .headphones:     return 0xfa3c
            case .x:              return 0x101c6
            case .home:           return 0xfe2b
            case .volumeHigh:     return 0xeb51   // volume (2 waves)
            case .volumeLow:      return 0xeb4f   // volume-2 (1 wave)
            case .volumeOff:      return 0xf1c3   // volume-off
            case .unlink:         return 0xeb46
            }
        }

        var filled: Bool {
            switch self {
            case .volumeHigh, .volumeLow, .volumeOff, .unlink: return false
            default: return true
            }
        }

        var family: String { filled ? "tabler-icons-filled" : "tabler-icons" }
    }

    let glyph: Glyph
    var size: CGFloat = 20

    var body: some View {
        Text(String(UnicodeScalar(glyph.codepoint)!))
            .font(.custom(glyph.family, size: size))
            // Icon fonts carry their own metrics; keep the glyph from being
            // squeezed by surrounding line-spacing.
            .fixedSize()
    }
}

// MARK: - Semantic source → glyph (mirrors web SourceIcon)

func sourceTablerGlyph(_ id: String?) -> TablerIcon.Glyph {
    switch id {
    case "spotify": return .brandSpotify
    case "airplay": return .broadcastTower
    case "analog":  return .microphone
    case .some:     return .externalLink
    default:        return .headphones
    }
}

/// Speaker glyph that ramps with level — mute only at 0 (web VolumeIcon states).
func volumeTablerGlyph(_ v: Int) -> TablerIcon.Glyph {
    if v == 0 { return .volumeOff }
    if v < 40 { return .volumeLow }
    return .volumeHigh
}

// MARK: - Arbitrary Tabler icons by name (custom source icons)

import CoreText

/// Resolves an arbitrary Tabler icon *name* (e.g. "home", "disc") to its glyph
/// codepoint in the bundled webfonts, so the custom icons users pick per source
/// (web `source.icon` = "outline:home" / "filled:disc") render natively instead
/// of falling back. The webfonts carry PostScript glyph names matching Tabler's
/// slugs; we build a name→codepoint map once per family by walking the font's
/// own character set, then cache it.
///
/// Building that map walks the font's whole character set (~6k glyphs, two
/// CoreText calls each) — far too heavy to run synchronously on the main thread
/// inside a SwiftUI `body`, which is exactly what caused the first-source-picker-
/// open hitch (FX-76: the first custom-icon render blocked the main thread for
/// the full walk; every later open hit the cache and felt instant). So the build
/// now runs once OFF the main thread — warmed at launch — and `codepoint` is a
/// pure, non-blocking cache read: it returns nil until the map is ready (callers
/// render the semantic fallback) and `ready` publishes so observers re-render and
/// swap in the real glyph the moment the warm-up lands.
@MainActor
final class TablerIconCatalog: ObservableObject {
    static let shared = TablerIconCatalog()

    /// Flips true once both families' maps are built off-main. `@Published` so an
    /// observing `SourceIcon` re-renders and trades its fallback for the real glyph.
    @Published private(set) var ready = false

    private var maps: [String: [String: UInt32]] = [:]
    private var warming = false

    /// Codepoint for `base` (a bare slug like "device-tv") in the given family,
    /// or nil if the map isn't built yet (caller shows a semantic fallback) or
    /// the font doesn't carry the slug (e.g. a first-party "custom:" icon). Never
    /// builds — a pure cache read, safe to call from a SwiftUI `body`.
    func codepoint(base: String, filled: Bool) -> UInt32? {
        maps[filled ? "tabler-icons-filled" : "tabler-icons"]?[base]
    }

    /// Build both families' name→codepoint maps once, off the main thread, then
    /// publish `ready`. Idempotent — safe to call from launch and lazily from any
    /// `SourceIcon` that appears before the warm-up was kicked.
    func warm() {
        guard !ready, !warming else { return }
        warming = true
        Task.detached(priority: .utility) {
            let outline = TablerIconCatalog.build("tabler-icons")
            let filled = TablerIconCatalog.build("tabler-icons-filled")
            await MainActor.run {
                let c = TablerIconCatalog.shared
                c.maps["tabler-icons"] = outline
                c.maps["tabler-icons-filled"] = filled
                c.warming = false
                c.ready = true
            }
        }
    }

    private nonisolated static func build(_ family: String) -> [String: UInt32] {
        let ctFont = CTFontCreateWithName(family as CFString, 16, nil)
        let cgFont = CTFontCopyGraphicsFont(ctFont, nil)
        let charset = CTFontCopyCharacterSet(ctFont) as CharacterSet
        var map: [String: UInt32] = [:]

        // CharacterSet bitmap: 8192 bytes for the BMP, then (planeByte + 8192
        // bytes) per non-empty supplementary plane. A set bit = a member
        // codepoint; resolving its glyph name gives the Tabler slug.
        let data = [UInt8](charset.bitmapRepresentation)
        var offset = 0
        func scan(planeBase: UInt32) {
            guard offset + 8192 <= data.count else { return }
            for byteIndex in 0..<8192 {
                let byte = data[offset + byteIndex]
                if byte == 0 { continue }
                for bit in 0..<8 where (byte & (1 << bit)) != 0 {
                    let cp = planeBase + UInt32(byteIndex * 8 + bit)
                    resolve(cp)
                }
            }
            offset += 8192
        }
        func resolve(_ cp: UInt32) {
            guard let scalar = UnicodeScalar(cp) else { return }
            var utf16 = Array(String(scalar).utf16)
            var glyphs = [CGGlyph](repeating: 0, count: utf16.count)
            guard CTFontGetGlyphsForCharacters(ctFont, &utf16, &glyphs, utf16.count),
                  let glyph = glyphs.first, glyph != 0,
                  let name = cgFont.name(for: glyph) as String? else { return }
            map[name] = cp
        }

        scan(planeBase: 0)                               // BMP
        while offset < data.count {                      // supplementary planes
            let plane = UInt32(data[offset]); offset += 1
            scan(planeBase: plane << 16)
        }
        return map
    }
}

/// Renders an arbitrary Tabler glyph by name (style "outline"/"filled" + slug),
/// falling back to a semantic source glyph if the font doesn't carry it.
struct SourceIcon: View {
    /// Raw `source.icon` value, e.g. "outline:home" / "filled:disc" (or nil).
    var icon: String?
    /// Source id, for the semantic fallback (spotify/airplay/analog/…).
    var sourceId: String?
    var size: CGFloat = 20

    // Observe the catalog so this icon re-renders (swapping the fallback for the
    // real custom glyph) the instant the off-main warm-up publishes `ready`.
    @ObservedObject private var catalog = TablerIconCatalog.shared

    var body: some View {
        if let parsed = Self.parse(icon),
           let cp = catalog.codepoint(base: parsed.base, filled: parsed.filled),
           let scalar = UnicodeScalar(cp) {
            Text(String(scalar))
                .font(.custom(parsed.filled ? "tabler-icons-filled" : "tabler-icons", size: size))
                .fixedSize()
        } else {
            // Map not ready (or font lacks the slug) → semantic fallback. Kick the
            // warm-up as a safety net in case it wasn't started at launch; it's
            // idempotent and never blocks the main thread.
            TablerIcon(glyph: sourceTablerGlyph(sourceId), size: size)
                .onAppear { catalog.warm() }
        }
    }

    /// "outline:home" → (base: "home", filled: false). Anything without a known
    /// outline/filled prefix (e.g. "custom:…") returns nil → semantic fallback.
    private static func parse(_ icon: String?) -> (base: String, filled: Bool)? {
        guard let icon, !icon.isEmpty else { return nil }
        let parts = icon.split(separator: ":", maxSplits: 1)
        if parts.count == 2 {
            let style = parts[0], base = String(parts[1])
            if style == "filled" { return (base, true) }
            if style == "outline" { return (base, false) }
            return nil   // "custom:" and anything else isn't in the webfont
        }
        return (icon, false)   // bare slug → treat as outline
    }
}
