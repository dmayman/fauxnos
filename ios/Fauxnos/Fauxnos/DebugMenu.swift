//
//  DebugMenu.swift
//  Fauxnos
//
//  A shake-to-reveal debug menu (DEBUG builds only). Today it hosts a single
//  switch: whether the FX-77 dev-control bus (`dev/control/state`) is applied.
//
//  Why this exists (FX-85): the Mac tuning page publishes a *retained* snapshot
//  to `dev/control/state`, so a freshly-flashed DEBUG build would pick up a
//  stale demo album on every launch and overlay a fake "now playing" card. The
//  toggle defaults OFF — the snapshot is received but ignored — and a shake
//  brings the menu up to turn the demo/tuning bus back on when you actually want
//  to tune the backdrop. Gating lives in `FauxnosStore.handle`.
//
//  Everything dev-specific is `#if DEBUG`; the `shakeDebugMenu()` modifier is a
//  no-op in Release, which never subscribes to `dev/control/state` anyway.
//

import SwiftUI

/// Attaches the shake-to-open debug menu. No-op in Release.
struct ShakeDebugModifier: ViewModifier {
    #if DEBUG
    @State private var showMenu = false
    #endif

    func body(content: Content) -> some View {
        #if DEBUG
        content
            .onReceive(NotificationCenter.default.publisher(for: .fauxnosDeviceShaken)) { _ in
                showMenu = true
            }
            .sheet(isPresented: $showMenu) { DebugMenuView() }
        #else
        content
        #endif
    }
}

extension View {
    /// Reveal the debug menu on a device shake (DEBUG only; no-op in Release).
    func shakeDebugMenu() -> some View { modifier(ShakeDebugModifier()) }
}

#if DEBUG
import Combine
import UIKit

/// Persisted DEBUG-only switches. `devControlEnabled` gates the FX-77
/// dev-control bus — including the demo "now playing" card it overlays for
/// backdrop tuning. Defaults to off (a fresh install never sets the key).
final class DebugSettings: ObservableObject {
    static let shared = DebugSettings()
    private static let key = "fauxnos.debug.devControlEnabled"

    @Published var devControlEnabled: Bool {
        didSet { UserDefaults.standard.set(devControlEnabled, forKey: Self.key) }
    }

    private init() {
        devControlEnabled = UserDefaults.standard.bool(forKey: Self.key)  // false when unset
    }
}

extension Notification.Name {
    static let fauxnosDeviceShaken = Notification.Name("fauxnos.deviceShaken")
}

/// App-wide shake detection. Motion events bubble up the responder chain to the
/// key window, so catching them here covers every screen without per-view
/// wiring. DEBUG-only, so Release never swizzles UIKit.
extension UIWindow {
    open override func motionEnded(_ motion: UIEvent.EventSubtype, with event: UIEvent?) {
        if motion == .motionShake {
            NotificationCenter.default.post(name: .fauxnosDeviceShaken, object: nil)
        }
        super.motionEnded(motion, with: event)
    }
}

struct DebugMenuView: View {
    @ObservedObject private var settings = DebugSettings.shared
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Toggle("Dev demo card", isOn: $settings.devControlEnabled)
                } footer: {
                    Text("Applies the dev-control tuning bus (dev/control/state), "
                         + "including the demo “now playing” card used to tune the "
                         + "backdrop without live Spotify. Off ignores that channel "
                         + "entirely — the fix for a freshly-flashed build showing a "
                         + "fake card.")
                }
            }
            .navigationTitle("Debug")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }
}
#endif
