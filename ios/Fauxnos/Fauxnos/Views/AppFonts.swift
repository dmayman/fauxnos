//
//  AppFonts.swift
//  Fauxnos
//
//  Registers the bundled fonts at launch. We register programmatically via
//  CoreText (process scope) rather than relying on Info.plist `UIAppFonts`, so
//  font loading is self-contained in code and survives plist churn. Idempotent:
//  re-registering an already-registered font is a harmless no-op.
//
//  Fonts live in Resources/Fonts/ and are flattened into the bundle root by the
//  synchronized file group, so they resolve by bare name here.
//

import CoreText
import Foundation

enum AppFonts {
    /// Brand typeface + the Tabler outline/filled icon webfonts.
    private static let files = ["Fustat", "tabler-icons", "tabler-icons-filled"]

    static func register() {
        for name in files {
            guard let url = Bundle.main.url(forResource: name, withExtension: "ttf") else {
                assertionFailure("Missing bundled font: \(name).ttf")
                continue
            }
            CTFontManagerRegisterFontsForURL(url as CFURL, .process, nil)
        }
    }
}
