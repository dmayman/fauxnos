//
//  GroupCard.swift
//  Fauxnos
//
//  The reusable per-group card — FX-17's deliverable and the surface that
//  volume (FX-18) and source switching (FX-19) will hang off. It turns the M1
//  read-only row into a living now-playing surface: album art + track meta,
//  transport (play/pause/next/prev), a read-only progress bar, and the M1
//  per-device volume display (control deferred to FX-18).
//
//  Mirrors the web `GroupCard.jsx` contract:
//    - Transport controls only for the Spotify source with real metadata
//      (go-librespot is the only thing the transport endpoint drives).
//    - Play/pause is optimistic; the MQTT `playback` echo is the source of
//      truth and reconciles the local pending flag.
//    - Position interpolates client-side between MQTT updates so the bar moves.
//

import SwiftUI

struct GroupCard: View {
    @EnvironmentObject private var store: FauxnosStore
    let group: SpeakerGroup

    private var homeId: String? { store.homeClientId(of: group) }
    private var track: Track? { store.track(for: group) }
    private var playback: Playback? { store.playback(for: group) }
    private var source: String? { store.currentSource(of: group) }
    private var hasMeta: Bool { track?.hasMeta == true }

    /// Transport is only meaningful for the Spotify source with metadata —
    /// the server proxies these commands to go-librespot. Mirrors the web's
    /// `hasControls = sourceId === 'spotify' && hasMeta`.
    private var hasControls: Bool { source == "spotify" && hasMeta }

    /// Display title: friendly group name if the server has one, else the home
    /// device's hostname (friendly per-device names are FX-22 / M3).
    private var title: String {
        if let name = group.name, !name.isEmpty { return name }
        if let home = homeId, let client = group.clients.first(where: { $0.id == home }) {
            return client.host.name
        }
        return group.clients.first?.host.name ?? group.id
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header
            nowPlaying
            if hasControls { transport }
            volumeRows
        }
        .padding(14)
        .background(.background.secondary, in: RoundedRectangle(cornerRadius: 14))
    }

    // MARK: - Header (title + active indicator)

    private var header: some View {
        HStack(spacing: 10) {
            Image(systemName: group.clients.count > 1 ? "hifispeaker.2.fill" : "hifispeaker.fill")
                .font(.title3)
                .foregroundStyle(store.isPlaying(group) ? Color.accentColor : .secondary)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.headline)
                Text(subtitle)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            if store.isPlaying(group) {
                Image(systemName: "waveform")
                    .foregroundStyle(Color.accentColor)
                    .symbolEffect(.variableColor.iterative, options: .repeating)
            }
        }
    }

    private var subtitle: String {
        var parts: [String] = []
        if let source, !source.isEmpty { parts.append(source.capitalized) }
        let n = group.clients.count
        parts.append(n == 1 ? "1 device" : "\(n) devices")
        return parts.joined(separator: " · ")
    }

    // MARK: - Now playing (art + track meta, or idle state)

    @ViewBuilder
    private var nowPlaying: some View {
        HStack(spacing: 12) {
            albumArt
            if hasMeta {
                VStack(alignment: .leading, spacing: 3) {
                    Text(track?.title ?? "—")
                        .font(.subheadline.weight(.semibold))
                        .lineLimit(1)
                    if let sub = trackSubtitle {
                        Text(sub)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                }
            } else {
                Text("Nothing playing")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
        }
    }

    private var trackSubtitle: String? {
        let parts = [track?.artist, track?.album].compactMap { $0 }.filter { !$0.isEmpty }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    /// 56pt art tile. Loads the track's `artUrl` async; falls back to a
    /// source-appropriate glyph while loading, on failure, or when idle.
    private var albumArt: some View {
        let url = hasMeta ? track?.artUrl.flatMap(URL.init(string:)) : nil
        return RoundedRectangle(cornerRadius: 8)
            .fill(.quaternary)
            .frame(width: 56, height: 56)
            .overlay {
                if let url {
                    AsyncImage(url: url) { phase in
                        switch phase {
                        case .success(let image):
                            image.resizable().scaledToFill()
                        default:
                            sourceGlyph
                        }
                    }
                } else {
                    sourceGlyph
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private var sourceGlyph: some View {
        Image(systemName: glyphName(for: source))
            .font(.title2)
            .foregroundStyle(.secondary)
    }

    private func glyphName(for source: String?) -> String {
        switch source {
        case "spotify": return "music.note"
        case "airplay": return "airplayaudio"
        case "analog":  return "mic.fill"
        case .some:     return "dot.radiowaves.left.and.right"
        default:        return "headphones"
        }
    }

    // MARK: - Transport

    private var transport: some View {
        VStack(spacing: 10) {
            progressBar
            HStack(spacing: 36) {
                TransportButton(systemName: "backward.fill", size: 20, label: "Previous") {
                    Task { await store.sendPlayback(.prev, for: group) }
                }
                PlayPauseButton(group: group)
                TransportButton(systemName: "forward.fill", size: 20, label: "Next") {
                    Task { await store.sendPlayback(.next, for: group) }
                }
            }
            .frame(maxWidth: .infinity)
        }
    }

    // MARK: - Progress (read-only; seek is out of FX-17 scope)

    @ViewBuilder
    private var progressBar: some View {
        let duration = Double(track?.durationMs ?? 0)
        if duration > 0 {
            TimelineView(.periodic(from: .now, by: 0.5)) { context in
                let pos = interpolatedPosition(at: context.date, duration: duration)
                let fraction = min(max(pos / duration, 0), 1)
                VStack(spacing: 4) {
                    GeometryReader { geo in
                        ZStack(alignment: .leading) {
                            Capsule().fill(.quaternary)
                            Capsule().fill(Color.accentColor)
                                .frame(width: geo.size.width * fraction)
                        }
                    }
                    .frame(height: 4)
                    HStack {
                        Text(fmtTime(pos)).font(.caption2.monospacedDigit()).foregroundStyle(.tertiary)
                        Spacer()
                        Text(fmtTime(duration)).font(.caption2.monospacedDigit()).foregroundStyle(.tertiary)
                    }
                }
            }
        }
    }

    /// Interpolate playback position client-side between MQTT updates, mirroring
    /// the web `useInterpolatedPosition`. `updatedAt` and `positionMs` are both
    /// epoch/relative milliseconds.
    private func interpolatedPosition(at now: Date, duration: Double) -> Double {
        guard let pb = playback else { return 0 }
        let base = Double(pb.positionMs ?? 0)
        guard pb.isPlaying == true else { return min(base, duration) }
        let t0 = pb.updatedAt ?? (now.timeIntervalSince1970 * 1000)
        let elapsed = (now.timeIntervalSince1970 * 1000) - t0
        return min(max(base + elapsed, 0), duration)
    }

    private func fmtTime(_ ms: Double) -> String {
        let total = Int(max(ms, 0) / 1000)
        return String(format: "%d:%02d", total / 60, total % 60)
    }

    // MARK: - Per-device volume (read-only — control is FX-18)

    private var volumeRows: some View {
        ForEach(group.clients) { client in
            DeviceVolumeRow(name: client.host.name,
                            volume: store.volume(for: client),
                            showName: group.clients.count > 1)
        }
    }
}

// MARK: - Transport buttons

/// Play/pause with optimistic state: flips immediately on tap, then defers to
/// the MQTT `playback` echo. The pending flag clears whenever a fresh playback
/// payload arrives (`updatedAt` changes), mirroring the web MediaCard.
private struct PlayPauseButton: View {
    @EnvironmentObject private var store: FauxnosStore
    let group: SpeakerGroup
    @State private var pending: Bool?

    private var actualPlaying: Bool { store.playback(for: group)?.isPlaying == true }
    private var displayed: Bool { pending ?? actualPlaying }

    var body: some View {
        Button {
            pending = !displayed
            Task { await store.sendPlayback(.playpause, for: group) }
        } label: {
            Image(systemName: displayed ? "pause.fill" : "play.fill")
                .font(.title)
                .frame(width: 44, height: 44)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .foregroundStyle(Color.accentColor)
        .accessibilityLabel(displayed ? "Pause" : "Play")
        .onChange(of: store.playback(for: group)?.updatedAt) { _, _ in
            // The echo landed — let MQTT be the source of truth again.
            pending = nil
        }
    }
}

private struct TransportButton: View {
    let systemName: String
    let size: CGFloat
    let label: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: systemName)
                .font(.system(size: size))
                .frame(width: 44, height: 44)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .foregroundStyle(.primary)
        .accessibilityLabel(label)
    }
}

// MARK: - Per-device volume (read-only)

struct DeviceVolumeRow: View {
    let name: String
    let volume: Int
    let showName: Bool

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: volume == 0 ? "speaker.slash.fill" : "speaker.wave.2.fill")
                .font(.caption)
                .foregroundStyle(.secondary)
                .frame(width: 18)
            if showName {
                Text(name)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .frame(width: 96, alignment: .leading)
                    .lineLimit(1)
            }
            ProgressView(value: Double(volume), total: 100)
                .tint(.secondary)
            Text("\(volume)")
                .font(.caption.monospacedDigit())
                .foregroundStyle(.tertiary)
                .frame(width: 28, alignment: .trailing)
        }
    }
}
