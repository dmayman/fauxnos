//
//  PreviewData.swift
//  Fauxnos
//
//  Static fixtures for Xcode Previews / the canvas — no network, no MQTT. These
//  feed `FauxnosStore.preview(...)` (see the #if DEBUG extension in
//  FauxnosStore.swift) so the card views render real content offline while we
//  iterate on design. Built straight from the model memberwise inits, keyed by
//  the same `fauxnosNNN` ids the live server uses, so the store's lookups
//  (homeClientId / track(for:) / currentSource) resolve exactly as in prod.
//
//  Album art: real network covers don't load deterministically in the canvas, so
//  we synthesize vivid gradient covers into temp files and point the tracks at
//  those `file://` URLs (AsyncImage loads them offline on iOS 16+). We also
//  pre-seed `AlbumArtColorStore` with each cover's dominant hue so the art-tint
//  theming (card tint, accent, progress) renders instantly without waiting on
//  async extraction.
//
//  DEBUG-only: excluded from release builds.
//

#if DEBUG
import Foundation
import UIKit

enum PreviewData {

    // MARK: Synthetic album covers (generated → temp files → file:// URLs)

    /// Render a diagonal two-stop gradient with a soft top-left highlight, write
    /// it to a stable temp PNG, and return the file URL string. Regenerated each
    /// preview build (overwrites in place) — cheap and self-contained, so no
    /// binary art needs to be committed.
    private static func makeCover(_ name: String, _ top: UIColor, _ bottom: UIColor) -> String {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("fxprev_\(name).png")
        let size = CGSize(width: 600, height: 600)
        let image = UIGraphicsImageRenderer(size: size).image { ctx in
            let cg = ctx.cgContext
            let space = CGColorSpaceCreateDeviceRGB()
            if let grad = CGGradient(colorsSpace: space,
                                     colors: [top.cgColor, bottom.cgColor] as CFArray,
                                     locations: [0, 1]) {
                cg.drawLinearGradient(grad, start: .zero,
                                      end: CGPoint(x: size.width, y: size.height), options: [])
            }
            if let highlight = CGGradient(colorsSpace: space,
                                          colors: [UIColor.white.withAlphaComponent(0.18).cgColor,
                                                   UIColor.clear.cgColor] as CFArray,
                                          locations: [0, 1]) {
                let c = CGPoint(x: size.width * 0.3, y: size.height * 0.28)
                cg.drawRadialGradient(highlight, startCenter: c, startRadius: 0,
                                      endCenter: c, endRadius: size.width * 0.75, options: [])
            }
        }
        try? image.pngData()?.write(to: url)
        return url.absoluteString
    }

    static let cover000 = makeCover("midnight",
                                    UIColor(red: 0.30, green: 0.42, blue: 0.92, alpha: 1),
                                    UIColor(red: 0.10, green: 0.08, blue: 0.32, alpha: 1))
    static let cover002 = makeCover("redbone",
                                    UIColor(red: 0.96, green: 0.55, blue: 0.20, alpha: 1),
                                    UIColor(red: 0.40, green: 0.06, blue: 0.10, alpha: 1))

    /// Dominant hues seeded into `AlbumArtColorStore` so the art-tint theming is
    /// immediate and deterministic (roughly matching each generated cover).
    static let artColors: [String: OKLCH] = [
        cover000: OKLCH(l: 0.58, c: 0.16, h: 264),   // indigo / blue
        cover002: OKLCH(l: 0.62, c: 0.16, h: 35),    // warm orange / red
    ]

    // MARK: Devices

    static func client(_ id: String, vol: Int) -> SnapClient {
        SnapClient(
            id: id,
            connected: true,
            host: SnapHost(name: id, ip: nil, mac: nil),
            config: SnapClientConfig(volume: SnapVolume(percent: vol, muted: false))
        )
    }

    /// Friendly names, mirroring /api/clients (web `nameMap`).
    static let names: [String: String] = [
        "fauxnos000": "Living Room",
        "fauxnos001": "Kitchen",
        "fauxnos002": "Office",
        "fauxnos003": "Bedroom",
        "fauxnos004": "Patio",
        "fauxnos005": "Den",
    ]

    // MARK: Sources offered per group (web /api/groups `sources`)

    static let spotifyAndAnalog: [Source] = [
        Source(id: "spotify", label: "Spotify", type: "internal"),
        Source(id: "analog", label: "Analog In", type: "internal"),
    ]

    // MARK: Tracks / playback overlays (keyed by home client id)

    static let tracks: [String: Track] = [
        "fauxnos000": Track(source: "spotify", title: "Midnight City", artist: "M83",
                            album: "Hurry Up, We're Dreaming", artUrl: cover000,
                            durationMs: 240_000, uri: nil),
        "fauxnos002": Track(source: "spotify", title: "Redbone", artist: "Childish Gambino",
                            album: "Awaken, My Love!", artUrl: cover002,
                            durationMs: 326_000, uri: nil),
    ]

    /// Computed so `updatedAt` is fresh each time a preview builds — keeps the
    /// progress interpolation starting from roughly the seeded position.
    static var playback: [String: Playback] {
        let now = Date().timeIntervalSince1970 * 1000
        return [
            "fauxnos000": Playback(isPlaying: true, positionMs: 78_000, updatedAt: now),
            "fauxnos002": Playback(isPlaying: false, positionMs: 152_000, updatedAt: now),
        ]
    }

    static let modes: [String: String] = [
        "fauxnos000": "spotify",
        "fauxnos002": "spotify",
        "fauxnos003": "analog",
        "fauxnos004": "spotify",
    ]

    static let volumes: [String: Int] = [
        "fauxnos000": 34, "fauxnos001": 21, "fauxnos002": 38,
        "fauxnos003": 9, "fauxnos004": 55, "fauxnos005": 47,
    ]

    // MARK: Groups — one per card variant

    /// V1 — multi + media: "All" accent row over device rows, Spotify playing.
    static let groupV1 = SpeakerGroup(
        id: "fauxnos000", name: nil, streamId: "source_fauxnos000_spotify",
        muted: false, homeClientId: "fauxnos000",
        clients: [client("fauxnos000", vol: 34), client("fauxnos001", vol: 21)],
        sources: spotifyAndAnalog, availableStreams: nil
    )

    /// V2 — single, no media: just a device row (name · volume · source).
    static let groupV2 = SpeakerGroup(
        id: "fauxnos003", name: nil, streamId: "source_fauxnos003_analog",
        muted: false, homeClientId: "fauxnos003",
        clients: [client("fauxnos003", vol: 9)],
        sources: spotifyAndAnalog, availableStreams: nil
    )

    /// V3 — single + media: media region over one device row.
    static let groupV3 = SpeakerGroup(
        id: "fauxnos002", name: nil, streamId: "source_fauxnos002_spotify",
        muted: false, homeClientId: "fauxnos002",
        clients: [client("fauxnos002", vol: 38)],
        sources: spotifyAndAnalog, availableStreams: nil
    )

    /// V4 — multi, no media: the "Connect … in Spotify" zero-state over rows.
    static let groupV4 = SpeakerGroup(
        id: "fauxnos004", name: nil, streamId: "source_fauxnos004_spotify",
        muted: false, homeClientId: "fauxnos004",
        clients: [client("fauxnos004", vol: 55), client("fauxnos005", vol: 47)],
        sources: spotifyAndAnalog, availableStreams: nil
    )

    /// The full list, one of each variant.
    static let groups: [SpeakerGroup] = [groupV1, groupV3, groupV2, groupV4]
}
#endif
