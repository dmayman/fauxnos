//
//  GroupsListView.swift
//  Fauxnos
//
//  The control-core screen: a live list of speaker groups. Membership and
//  sources come from /api/groups; now-playing / transport / active-idle reflect
//  MQTT in real time with no manual refresh. Each group renders as a `GroupCard`
//  (FX-17). Volume and source-switch affordances land in FX-18 / FX-19.
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
                    GroupCard(group: group)
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
