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

    var body: some Scene {
        WindowGroup {
            GroupsListView()
                .environmentObject(store)
                .task { store.start() }
        }
    }
}
