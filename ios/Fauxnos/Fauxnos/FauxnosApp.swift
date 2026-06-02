//
//  FauxnosApp.swift
//  Fauxnos
//
//  App entry. Owns the single FauxnosStore and kicks off REST + MQTT on launch.
//

import SwiftUI

@main
struct FauxnosApp: App {
    @StateObject private var store = FauxnosStore()

    init() { AppFonts.register() }

    var body: some Scene {
        WindowGroup {
            GroupsListView()
                .environmentObject(store)
                .task { store.start() }
                // Build the Tabler custom-icon map off-main at launch so the
                // first source-picker open is instant rather than blocking the
                // main thread on the font-charset walk (FX-76).
                .task { TablerIconCatalog.shared.warm() }
        }
    }
}
