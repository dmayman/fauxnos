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

    @Environment(\.scenePhase) private var scenePhase
    /// When the app went to the background; cards re-sort if it was away long.
    @State private var backgroundedAt: Date?

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
                .onChange(of: scenePhase) { _, phase in
                    switch phase {
                    case .background:
                        backgroundedAt = Date()
                    case .active:
                        if let t = backgroundedAt, Date().timeIntervalSince(t) > 5 * 60 {
                            store.settleCardOrder()
                        }
                        backgroundedAt = nil
                    default:
                        break
                    }
                }
        }
    }
}
