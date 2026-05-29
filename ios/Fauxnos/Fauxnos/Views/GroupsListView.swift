//
//  GroupsListView.swift
//  Fauxnos
//
//  The one M1 screen: a read-only, live list of speaker groups. Membership and
//  sources come from /api/groups; volume / now-playing / active-idle reflect
//  MQTT in real time with no manual refresh. No control affordances yet — that's
//  a later milestone.
//

import SwiftUI

struct GroupsListView: View {
    @EnvironmentObject private var store: FauxnosStore

    var body: some View {
        NavigationStack {
            content
                .navigationTitle("Fauxnos")
                .toolbar {
                    ToolbarItem(placement: .topBarTrailing) {
                        ConnectionBadge(connected: store.mqttConnected)
                    }
                }
                .refreshable { await store.refresh() }
        }
    }

    @ViewBuilder
    private var content: some View {
        if store.groups.isEmpty {
            emptyOrError
        } else {
            List {
                ForEach(store.groups) { group in
                    GroupRow(group: group)
                        .listRowSeparator(.hidden)
                        .listRowInsets(EdgeInsets(top: 6, leading: 16, bottom: 6, trailing: 16))
                }
                if let updated = store.lastUpdated {
                    Text("Updated \(updated.formatted(date: .omitted, time: .standard))")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                        .frame(maxWidth: .infinity, alignment: .center)
                        .listRowSeparator(.hidden)
                }
            }
            .listStyle(.plain)
        }
    }

    @ViewBuilder
    private var emptyOrError: some View {
        if store.isLoading && store.apiError == nil {
            ProgressView("Connecting to \(store.config.host)…")
        } else if let error = store.apiError {
            ContentUnavailableView {
                Label("Can't reach the server", systemImage: "wifi.exclamationmark")
            } description: {
                Text("\(store.config.host)\n\(error)")
            } actions: {
                Button("Retry") { Task { await store.refresh() } }
                    .buttonStyle(.borderedProminent)
            }
        } else {
            ContentUnavailableView("No groups", systemImage: "hifispeaker.2",
                                   description: Text("No connected devices reported by \(store.config.host)."))
        }
    }
}

// MARK: - Group row

private struct GroupRow: View {
    @EnvironmentObject private var store: FauxnosStore
    let group: SpeakerGroup

    private var homeId: String? { store.homeClientId(of: group) }

    /// Display title: friendly group name if the server has one, else the home
    /// device's hostname. Friendly per-device names live in /api/clients, which
    /// is out of M1 scope — so a hostname (e.g. "fauxnos001") is the fallback.
    private var title: String {
        if let name = group.name, !name.isEmpty { return name }
        if let home = homeId, let client = group.clients.first(where: { $0.id == home }) {
            return client.host.name
        }
        return group.clients.first?.host.name ?? group.id
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                Image(systemName: group.clients.count > 1 ? "hifispeaker.2.fill" : "hifispeaker.fill")
                    .font(.title3)
                    .foregroundStyle(store.isPlaying(group) ? Color.accentColor : .secondary)
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(.headline)
                    sourceLine
                }
                Spacer()
                if store.isPlaying(group) {
                    Image(systemName: "waveform")
                        .foregroundStyle(Color.accentColor)
                        .symbolEffect(.variableColor.iterative, options: .repeating)
                }
            }

            if let track = store.track(for: group), track.hasMeta {
                Text([track.title, track.artist].compactMap { $0 }.joined(separator: " — "))
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }

            ForEach(group.clients) { client in
                DeviceVolumeRow(name: client.host.name,
                                volume: store.volume(for: client),
                                showName: group.clients.count > 1)
            }
        }
        .padding(14)
        .background(.background.secondary, in: RoundedRectangle(cornerRadius: 14))
    }

    @ViewBuilder
    private var sourceLine: some View {
        let source = store.currentSource(of: group)
        let memberCount = group.clients.count
        Text(memberLine(source: source, members: memberCount))
            .font(.caption)
            .foregroundStyle(.secondary)
    }

    private func memberLine(source: String?, members: Int) -> String {
        var parts: [String] = []
        if let source, !source.isEmpty { parts.append(source.capitalized) }
        parts.append(members == 1 ? "1 device" : "\(members) devices")
        return parts.joined(separator: " · ")
    }
}

// MARK: - Per-device volume (read-only)

private struct DeviceVolumeRow: View {
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

// MARK: - Connection badge

private struct ConnectionBadge: View {
    let connected: Bool
    var body: some View {
        HStack(spacing: 5) {
            Circle()
                .fill(connected ? Color.green : Color.orange)
                .frame(width: 8, height: 8)
            Text(connected ? "Live" : "Offline")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .accessibilityLabel(connected ? "Real-time connected" : "Real-time disconnected")
    }
}

#Preview {
    GroupsListView().environmentObject(FauxnosStore())
}
