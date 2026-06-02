//
//  Theme.swift
//  Fauxnos
//
//  The design-token layer for the control-core surface (FX-33). It ports the
//  web UI's `fx-*` design language — the neutral-dark palette, the strict
//  4/8/12/16/24/32 spacing scale, the radii and motion curves — into native
//  SwiftUI so the iOS app reads as a deliberately-designed product rather than
//  a wired-up prototype, while staying native (system materials, SF Symbols,
//  haptics) instead of literally cloning web pixels.
//
//  Colors adapt to light/dark via `Color(uiColor:)` dynamic providers so the
//  whole surface tracks the system appearance, mirroring the web's
//  `[data-theme]` / `prefers-color-scheme` behavior. The album-art-derived
//  accent system lives in AlbumArtColor.swift and layers on top of these.
//

import SwiftUI
import UIKit

// MARK: - Palette

/// Fauxnos neutral palette. Values mirror the web `index.css` `--fx-*` tokens
/// (dark: #060606 ground, #141414/#1C1C1C/#262626 surfaces; light inverse) so
/// the two clients share one visual ground truth.
enum FX {
    // Surfaces
    static let bg        = dynamic(dark: 0x060606, light: 0xF9F9F9)
    static let surface1  = dynamic(dark: 0x141414, light: 0xFFFFFF)
    static let surface2  = dynamic(dark: 0x1C1C1C, light: 0xF5F5F5)
    static let surface3  = dynamic(dark: 0x262626, light: 0xEAEAEA)

    // Hairlines (alpha over the surface) — web --fx-line / --fx-line-strong
    static let line       = dynamicAlpha(dark: (0xFFFFFF, 0.06), light: (0x000000, 0.08))
    static let lineStrong = dynamicAlpha(dark: (0xFFFFFF, 0.12), light: (0x000000, 0.16))

    // Text ramp — web --fx-text / --fx-text-2 / --fx-text-3. Light-mode primary
    // is #4A4A4A (a soft near-black), NOT a hard #1F1F1F: the web deliberately
    // keeps the lightest text gentle so the neutral surface doesn't feel harsh.
    static let text  = dynamic(dark: 0xF2F2F2, light: 0x4A4A4A)
    static let text2 = dynamic(dark: 0xA0A0A0, light: 0x7A7A7A)
    static let text3 = dynamic(dark: 0x6A6A6A, light: 0xA0A0A0)

    // Status
    static let ok   = dynamic(dark: 0x7BB186, light: 0x3E7A4D)
    static let warn = dynamic(dark: 0xD6A85F, light: 0x8E6618)
    static let err  = dynamic(dark: 0xD4736B, light: 0x9E443C)

    // MARK: dynamic helpers

    static func dynamic(dark: Int, light: Int) -> Color {
        Color(uiColor: UIColor { trait in
            trait.userInterfaceStyle == .dark ? UIColor(rgb: dark) : UIColor(rgb: light)
        })
    }

    static func dynamicAlpha(dark: (Int, CGFloat), light: (Int, CGFloat)) -> Color {
        Color(uiColor: UIColor { trait in
            let (rgb, a) = trait.userInterfaceStyle == .dark ? dark : light
            return UIColor(rgb: rgb, alpha: a)
        })
    }
}

extension UIColor {
    convenience init(rgb: Int, alpha: CGFloat = 1) {
        self.init(
            red:   CGFloat((rgb >> 16) & 0xFF) / 255,
            green: CGFloat((rgb >> 8) & 0xFF) / 255,
            blue:  CGFloat(rgb & 0xFF) / 255,
            alpha: alpha
        )
    }
}

// MARK: - Type (Fustat, the web's brand typeface)

/// Fauxnos uses Fustat across the surface, matching the web `--fx-font`. The
/// variable font ships named instances (`Fustat-Regular…ExtraBold`); we address
/// them by PostScript name so weight selection is exact. The card ramp mirrors
/// `index.css` `.fx-title-track` / `.fx-meta-track` / `.fx-name-device` /
/// `.fx-time-track`, scaled for a phone-width card while preserving hierarchy.
enum FxFont {
    static func fustat(_ size: CGFloat, _ weight: Weight = .regular) -> Font {
        .custom(weight.ps, size: size)
    }
    enum Weight {
        case regular, medium, semibold, bold, extrabold
        var ps: String {
            switch self {
            case .regular:   return "Fustat-Regular"
            case .medium:    return "Fustat-Medium"
            case .semibold:  return "Fustat-SemiBold"
            case .bold:      return "Fustat-Bold"
            case .extrabold: return "Fustat-ExtraBold"
            }
        }
    }
    static let titleTrack = fustat(21, .bold)        // web 28 — track title
    static let metaTrack  = fustat(17, .semibold)    // web 20 — artist · album
    static let nameDevice = fustat(19, .bold)        // web 20 — device-row name
    static let timeTrack  = fustat(13, .medium)      // web 14 — progress timecode
    static let emptyCta   = fustat(15, .medium)      // web 16 — V4 zero-state CTA
}

// MARK: - Spacing / radii / motion

/// Strict spacing scale, matching the web `--fx-1…6` (4/8/12/16/24/32).
enum Space {
    static let xs: CGFloat  = 4
    static let sm: CGFloat  = 8
    static let md: CGFloat  = 12
    static let lg: CGFloat  = 16
    static let xl: CGFloat  = 24
    static let xxl: CGFloat = 32
}

enum Radius {
    static let sm: CGFloat    = 8
    static let card: CGFloat  = 30   // web .fx-group-card-v2 = 36, eased for phone width
    static let inner: CGFloat = 28   // floating rows sub-card under the media region
    static let art: CGFloat   = 12   // web .fx-group-media-art = 12
}

extension Animation {
    /// The web `--fx-ease` cubic-bezier(0.2, 0.7, 0.2, 1), as a spring tuned to
    /// feel native on touch. Used for card / drop-target / reveal transitions.
    static var fxEase: Animation { .spring(response: 0.34, dampingFraction: 0.82) }
    static var fxQuick: Animation { .easeOut(duration: 0.18) }

    /// Card press feedback — a low-damping spring whose overshoot on release
    /// gives the bouncy settle. Mirrors the web `.is-pressed` transition
    /// `transform 260ms cubic-bezier(0.34, 1.55, 0.64, 1)` (the 1.55 control
    /// point is the overshoot). Used for the signature "tactile control" press.
    static var fxPress: Animation { .spring(response: 0.28, dampingFraction: 0.55) }
}

// MARK: - Haptics

/// Thin wrapper over UIKit feedback generators so interaction polish (the
/// "feel native" half of FX-33) is one call site away. Generators are cheap to
/// create per-event; we don't pre-warm since these fire on discrete gestures.
enum Haptics {
    static func tap()      { UIImpactFeedbackGenerator(style: .light).impactOccurred() }
    static func select()   { UISelectionFeedbackGenerator().selectionChanged() }
    static func lift()     { UIImpactFeedbackGenerator(style: .medium).impactOccurred() }
    static func commit()   { UIImpactFeedbackGenerator(style: .rigid).impactOccurred() }
    static func success()  { UINotificationFeedbackGenerator().notificationOccurred(.success) }
}
