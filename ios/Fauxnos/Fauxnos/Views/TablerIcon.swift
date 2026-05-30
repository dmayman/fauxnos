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
        case chevronDown, microphone, broadcastTower, externalLink, headphones, x
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
