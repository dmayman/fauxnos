//
//  FauxnosApp.swift
//  Fauxnos
//
//  App entry. Owns the single FauxnosStore and kicks off REST + MQTT on launch.
//

import SwiftUI

@main
struct FauxnosApp: App {
    @StateObject private var store: FauxnosStore = {
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("-previewData") {
            return .preview(modes: PreviewData.demoModes)
        }
        #endif
        return FauxnosStore()
    }()

    init() { AppFonts.register() }

    var body: some Scene {
        WindowGroup {
            GroupsListView()
                .environmentObject(store)
                .task { if store.lastUpdated == nil { store.start() } }
                // Build the Tabler custom-icon map off-main at launch so the
                // first source-picker open is instant rather than blocking the
                // main thread on the font-charset walk (FX-76).
                .task { TablerIconCatalog.shared.warm() }
                // Shake to reveal the debug menu (FX-85). No-op in Release.
                .shakeDebugMenu()
        }
    }
}
