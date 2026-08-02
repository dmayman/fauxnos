//
//  SettingsControl.swift
//  Fauxnos
//
//  The settings menu that drops from the gear icon in the nav-bar trailing slot
//  (wired up in `GroupsListView`: the toolbar button, its captured frame, and the
//  floating `settingsMenuLayer`). Its one row restarts the fauxnos-server process.
//  Because a restart drops audio in every room for a few seconds, the tap routes
//  through a confirmation dialog rather than firing immediately.
//
//  The menu is the same Liquid Glass card as the source picker (`SourcePickerMenu`
//  in `GroupCard`) and floats over the list the same way — anchored to its
//  trigger's global frame — so the two menus feel identical.
//

import SwiftUI

/// The glass dropdown: one "Restart fauxnos" row on the same Liquid Glass card
/// as the source picker. Kept narrow (it holds a single action) but otherwise
/// styled row-for-row like `SourcePickerMenu`.
struct SettingsMenu: View {
    /// Called when the restart row is tapped — the host closes the menu and
    /// raises the confirmation dialog.
    let onRestart: () -> Void

    /// Width of the floating card; `GroupsListView.settingsMenuLayer` offsets by
    /// the same value to right-align it under the gear. Narrow — it holds one row.
    static let width: CGFloat = 196
    private static let shape = RoundedRectangle(cornerRadius: 16, style: .continuous)

    var body: some View {
        Button {
            Haptics.select()
            onRestart()
        } label: {
            HStack(spacing: Space.sm) {
                TablerIcon(glyph: .refresh, size: 17)
                    .foregroundStyle(FX.text)
                    .frame(width: 20)
                Text("Restart fauxnos")
                    .font(FxFont.fustat(15, .bold))
                    .foregroundStyle(FX.text)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, Space.md)
            .padding(.vertical, Space.sm)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .padding(.vertical, Space.xs)
        .frame(width: Self.width, alignment: .leading)
        .fixedSize(horizontal: false, vertical: true)
        .modifier(GlassCard(shape: Self.shape))
        .shadow(color: .black.opacity(0.18), radius: 14, y: 5)
    }
}

/// Rounded-rect Liquid Glass card, matching `GroupCard`'s private `GlassCard`
/// (that one isn't visible here). iOS 26 refracts the content behind the
/// floating menu; earlier OSes fall back to a clipped `.thinMaterial` blur.
private struct GlassCard: ViewModifier {
    let shape: RoundedRectangle
    func body(content: Content) -> some View {
        if #available(iOS 26.0, *) {
            content.glassEffect(.regular, in: shape)
        } else {
            content
                .background(.thinMaterial, in: shape)
                .overlay(shape.strokeBorder(FX.lineStrong, lineWidth: 1))
        }
    }
}

#Preview("Settings menu") {
    ZStack {
        FX.bg.ignoresSafeArea()
        SettingsMenu(onRestart: {})
    }
}
