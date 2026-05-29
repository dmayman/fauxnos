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
            // ScrollView so pull-to-refresh still works while empty/erroring.
            ScrollView { emptyOrError.frame(maxWidth: .infinity).padding(.top, 80) }
        } else {
            // ScrollView + LazyVStack (not List) so the FX-20 drag-and-drop
            // grouping behaves predictably — List intercepts drags for its own
            // reordering and makes `.draggable`/`.dropDestination` flaky.
            ScrollView {
                LazyVStack(spacing: 12) {
                    ForEach(store.groups) { group in
                        GroupCard(group: group)
                    }
                    if let updated = store.lastUpdated {
                        Text("Updated \(updated.formatted(date: .omitted, time: .standard))")
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                            .frame(maxWidth: .infinity, alignment: .center)
                            .padding(.top, 4)
                    }
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 8)
            }
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
