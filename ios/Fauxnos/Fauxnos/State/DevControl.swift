//
//  DevControl.swift
//  Fauxnos
//
//  A general-purpose dev-time control bus (FX-77). A tuning surface on a Mac
//  (see `ios/devtools/dev-control.html`) publishes a JSON snapshot to the MQTT
//  topic `dev/control/state`; the app — in DEBUG only — subscribes through the
//  existing FauxnosStore socket and merges the values into this shared store.
//
//  Views read tunables by key with a baked fallback, e.g.
//  `DevControl.shared.d("backdrop.blur", 60)`, so:
//    • release builds never receive dev/control traffic and every read returns
//      its fallback — i.e. the baked shipping constant, identical to today;
//    • DEBUG builds re-render live as sliders move on the Mac.
//
//  It is deliberately schema-free: the bus merges whatever keys arrive, and a
//  view consumes the keys it knows. Adding a new tunable means adding a control
//  to the Mac page and a keyed read in a view — no change here. This first use
//  is the FX-77 album-art backdrop, but nothing about the bus is specific to it.
//

import Foundation
import Combine

/// Shared, observable bag of dev-tuning values. Present in all builds but only
/// ever populated in DEBUG (release has no publisher feeding it), so observing
/// it is free in release — the dictionaries stay empty and every read falls
/// back to its baked default.
final class DevControl: ObservableObject {
    static let shared = DevControl()

    /// Numeric knobs (sliders, or toggles encoded as 0/1), keyed by dotted name.
    @Published private(set) var numbers: [String: Double] = [:]
    /// String knobs (e.g. a chosen album-art URL), keyed by dotted name.
    @Published private(set) var strings: [String: String] = [:]

    private init() {}

    /// Numeric tunable, or `fallback` when unset (always, in release).
    func d(_ key: String, _ fallback: Double) -> Double { numbers[key] ?? fallback }

    /// CGFloat convenience for the many SwiftUI knobs (blur radius, scale, …).
    func f(_ key: String, _ fallback: CGFloat) -> CGFloat { CGFloat(d(key, Double(fallback))) }

    /// Boolean tunable (0/1 encoded), or `fallback` when unset.
    func b(_ key: String, _ fallback: Bool) -> Bool {
        guard let v = numbers[key] else { return fallback }
        return v != 0
    }

    /// String tunable, or nil when unset/empty.
    func s(_ key: String) -> String? {
        guard let v = strings[key], !v.isEmpty else { return nil }
        return v
    }

    #if DEBUG
    /// Merge a decoded `dev/control/state` snapshot. An empty string value
    /// clears its key, so the Mac page can "unset" a chosen album.
    func apply(numbers n: [String: Double], strings s: [String: String]) {
        for (k, v) in n { numbers[k] = v }
        for (k, v) in s {
            if v.isEmpty { strings.removeValue(forKey: k) } else { strings[k] = v }
        }
    }

    /// Drop every tuned value, reverting all keyed reads to their baked
    /// fallbacks. Used when the FX-85 debug toggle disables the bus.
    func clearAll() {
        numbers = [:]
        strings = [:]
    }
    #endif
}

#if DEBUG
/// Decodes the `dev/control/state` payload and applies it to a `DevControl`.
/// The Mac page publishes `{ "numbers": { … }, "strings": { … } }`; both halves
/// optional. Tolerant of JSON number/bool ambiguity.
enum DevControlPayload {
    static func apply(_ data: Data, to control: DevControl) {
        guard let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
        let numbers = (obj["numbers"] as? [String: Any])?.compactMapValues { v -> Double? in
            if let n = v as? NSNumber { return n.doubleValue }   // covers Double, Int, Bool
            if let s = v as? String { return Double(s) }
            return nil
        } ?? [:]
        let strings = (obj["strings"] as? [String: Any])?.compactMapValues { $0 as? String } ?? [:]
        control.apply(numbers: numbers, strings: strings)
    }
}
#endif
