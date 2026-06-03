//
//  CardDrag.swift
//  Fauxnos
//
//  The lift-to-regroup interaction (FX-33). Replaces the old system
//  drag-and-drop (a tiny row handle + `.draggable`/`.dropDestination`) with a
//  custom, fully-owned gesture so the *actual* card lifts and floats:
//
//    press-hold → the grabbed element scales down on a time-based ramp (modern
//      iPhones have no 3D-Touch force sensor, and the Simulator/Preview canvas
//      never report force, so hold-duration is the honest analog of "force")
//    cross the lift threshold → a haptic + a spring "detent" (dip a touch more,
//      then settle back to 100%) marks passing the detent, all while pressed
//    lifted → the element detaches into a floating preview that *looks like a
//      single-device card* and tracks the finger, no longer locked in x/y
//    over a sibling card → that card lights its bright drop-zone stroke
//    release over a target → the dragged device joins the target group
//
//  A single device card lifts as a whole (the card IS the device). A
//  multi-device card lifts per *row* — the dragged row also becomes the
//  single-device-card preview. The press gesture is an `onLongPressGesture`
//  (it yields to the enclosing ScrollView on movement and to descendant
//  controls — slider / buttons / source trigger — in their own regions, so
//  scrolling and volume edits are unaffected); a simultaneous zero-distance
//  drag rides the same touch and is read only once lifted, while the list's
//  scroll is frozen for the duration of the drag.
//

import SwiftUI

/// The shared coordinate space all card frames and drag locations live in, so
/// hit-testing a lifted device against drop zones is apples-to-apples.
let kCardSpace = "fxCardSpace"

// MARK: - Card frame reporting

/// Every `GroupCard` publishes its frame (keyed by group id) up to the list,
/// which hands them to the drag controller for drop-zone hit-testing.
struct CardFrameKey: PreferenceKey {
    static let defaultValue: [String: CGRect] = [:]
    static func reduce(value: inout [String: CGRect], nextValue: () -> [String: CGRect]) {
        value.merge(nextValue(), uniquingKeysWith: { $1 })
    }
}

extension CGRect { var center: CGPoint { CGPoint(x: midX, y: midY) } }

// MARK: - Drag controller

/// List-level state for an in-flight lift: which device is airborne, where the
/// finger is, which card it's hovering, and the floating preview to render.
@MainActor
final class CardDragController: ObservableObject {
    /// Lift-gesture scale keyframes, shared with `LiftToRegroup` so the shadow
    /// mapping and the animation agree on the exact same numbers.
    static let pressedScale: CGFloat = 0.98   // scale at the end of the press ramp
    static let draggingScale: CGFloat = 1.02  // resting scale while floating

    @Published var cardFrames: [String: CGRect] = [:]
    @Published var draggingClientId: String?
    @Published var dragLocation: CGPoint = .zero
    @Published var hoverGroupId: String?
    /// Finger is over empty background (no card), which — for a device that's a
    /// member of a group — is the "remove from group" drop zone. Drives the
    /// background drop-zone tint in `GroupsListView`.
    @Published var hoverBackground = false
    @Published var preview: AnyView?
    @Published var previewWidth: CGFloat = 0
    @Published var previewScale: CGFloat = 1
    /// Float opacity — 1 while dragging; faded to 0 as the float glides into a
    /// destination card on a successful drop (so it dissolves as the card grows
    /// the real row), then restored on reset.
    @Published var previewOpacity: CGFloat = 1

    /// Raised the instant an in-row control (volume slider, scrub bar) takes the
    /// touch, so the lift gesture knows the press belongs to that control and
    /// must not arm the drag. Single-touch on iOS, so a plain shared flag is safe.
    @Published var controlsEngaged = false

    /// Normalized lift, 0 at rest scale (1×) → 1 at the drag scale (clamped). The
    /// float shadow is derived from this single value, so size/offset/opacity all
    /// track the one scale. Baseline is 1× — the resting card's own scale — so at
    /// 1× the float shadow equals the resting card's shadow *exactly*: a returning
    /// card that settles to 1× is pixel- AND shadow-identical to the card it lands
    /// on, so the swap is invisible. Below 1× (press / detent) clamps to 0, the
    /// small resting shadow, so the preview also never flashes when it appears.
    var previewLift: CGFloat {
        let t = (previewScale - 1) / (Self.draggingScale - 1)
        return max(0, min(1, t))
    }

    /// The group the dragged device came from — excluded as a drop target.
    var sourceGroupId: String?
    /// True when the dragged device belongs to a group it can be removed from
    /// (its source group has more than one member). Gates the background as a
    /// "remove from group" drop zone — a standalone device has nothing to leave.
    var canLeaveGroup = false
    /// Finger position relative to the preview center, so it tracks naturally.
    var grabOffset: CGSize = .zero

    var isDragging: Bool { draggingClientId != nil }

    /// Recompute the hovered drop zone from the current finger location; a light
    /// tap fires when entering a fresh target (the "this is droppable" cue). A
    /// non-source card under the finger is a join target; empty background (no
    /// card at all) is a remove-from-group target, but only for a groupable device.
    func updateHover() {
        var joinTarget: String?
        var overAnyCard = false
        for (gid, frame) in cardFrames where frame.contains(dragLocation) {
            overAnyCard = true
            if gid != sourceGroupId { joinTarget = gid }
        }
        let background = joinTarget == nil && !overAnyCard && canLeaveGroup

        if joinTarget != hoverGroupId {
            if joinTarget != nil { Haptics.tap() }
            hoverGroupId = joinTarget
        }
        if background != hoverBackground {
            if background { Haptics.tap() }   // entered the remove zone
            hoverBackground = background
        }
    }

    func reset() {
        draggingClientId = nil
        sourceGroupId = nil
        canLeaveGroup = false
        hoverGroupId = nil
        hoverBackground = false
        preview = nil
        previewWidth = 0
        previewScale = 1
        previewOpacity = 1
        grabOffset = .zero
    }
}

// MARK: - Lift-to-regroup gesture

struct LiftToRegroup: ViewModifier {
    @EnvironmentObject private var store: FauxnosStore
    @EnvironmentObject private var controller: CardDragController
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    let client: SnapClient
    let groupId: String
    /// Single cards lift in place (the card is already a device card); rows lift
    /// centered under the finger (the preview is a synthesized device card).
    let inPlace: Bool
    /// True when the float is a pixel match for the lifted element (V2 whole card),
    /// so the return hard-swaps; false (media device-panel, multi row) crossfades.
    let matchesSource: Bool

    @State private var lifted = false
    @State private var scale: CGFloat = 1
    @State private var selfFrame: CGRect = .zero
    @State private var restWidth: CGFloat = 0      // unscaled layout width (immune to the ramp scaleEffect)
    @State private var currentLocation: CGPoint = .zero

    private let liftDuration = 0.34
    private let holdScale = CardDragController.pressedScale    // scale at the end of the press ramp
    private let detentDip: CGFloat = 0.97                     // momentary dip as the detent pops
    private let dragScale = CardDragController.draggingScale   // resting scale while floating (lifted a touch proud)
    private let moveTolerance: CGFloat = 14                    // pre-lift travel that hands off to scroll

    func body(content: Content) -> some View {
        content
            .scaleEffect(reduceMotion ? 1 : scale)
            .opacity(lifted ? 0 : 1)            // source vacates; a placeholder fills its slot
            .overlay {
                // Placeholder fades in over 0.34s as the device lifts; on drop /
                // return it's removed instantly (asymmetric) so the swap stays
                // clean. The animation is scoped here so the source's own opacity
                // (above) still vacates instantly.
                ZStack {
                    if lifted {
                        placeholder.transition(.asymmetric(insertion: .opacity, removal: .identity))
                    }
                }
                .animation(.easeInOut(duration: 0.34), value: lifted)
            }
            .background(
                GeometryReader { geo in
                    Color.clear
                        .onAppear {
                            selfFrame = geo.frame(in: .named(kCardSpace))
                            restWidth = geo.size.width
                        }
                        .onChange(of: geo.frame(in: .named(kCardSpace))) { _, new in selfFrame = new }
                        // geo.size is the layout size — unaffected by the press-ramp
                        // scaleEffect — so it stays the true resting card width.
                        .onChange(of: geo.size.width) { _, new in restWidth = new }
                }
            )
            .onLongPressGesture(minimumDuration: liftDuration, maximumDistance: moveTolerance) {
                fireLift()
            } onPressingChanged: { pressing in
                if pressing { startRamp() } else if !lifted { cancelRamp() }
            }
            .simultaneousGesture(
                DragGesture(minimumDistance: 0, coordinateSpace: .named(kCardSpace))
                    .onChanged { v in
                        currentLocation = v.location
                        if lifted {
                            controller.dragLocation = v.location
                            controller.updateHover()
                        }
                    }
                    .onEnded { _ in if lifted { performDrop() } }
            )
            // A slider/scrub bar in this row grabbed the touch — abort any press
            // ramp already underway so the card doesn't creep down mid-scrub.
            .onChange(of: controller.controlsEngaged) { _, engaged in
                if engaged && !lifted { cancelRamp() }
            }
    }

    /// The "what was here" slot left behind while the device floats: an adaptive
    /// translucent neutral (`Color(.label).opacity(0.15)` — black in light, white
    /// in dark) so the slot reads cleanly over any album-art backdrop without
    /// clashing. No border, no shadow. A single card leaves a card-radius rounded
    /// rect; a multi-card row leaves a full pill (web `border-radius: 999px`) so
    /// the gap reads as a device slot.
    @ViewBuilder
    private var placeholder: some View {
        let fill = Color(.label).opacity(0.15)
        if inPlace {
            RoundedRectangle(cornerRadius: Radius.card, style: .circular).fill(fill)
        } else {
            Capsule().fill(fill)
        }
    }

    private func startRamp() {
        guard !reduceMotion, !lifted, !controller.controlsEngaged else { return }
        withAnimation(.linear(duration: liftDuration)) { scale = holdScale }
    }

    private func cancelRamp() {
        withAnimation(.fxQuick) { scale = 1 }
    }

    private func fireLift() {
        // Bail if a slider/scrub bar owns the touch — the long press completed,
        // but the press was a control interaction, not a grab.
        guard !lifted, !controller.controlsEngaged else { return }
        lifted = true
        scale = 1                              // source is hidden; reset for re-show
        Haptics.lift()

        // For an in-place (single-card) lift the card's own press-ramp scaleEffect
        // shrinks its measured frame in `cardFrames`, which would render the float
        // ~2% narrow and pop it wider on return. `restWidth` is the unscaled layout
        // width, so the float matches the resting card to the pixel. A row lift
        // reads the parent card's width, which the row's own ramp never touches.
        let width = inPlace
            ? (restWidth > 0 ? restWidth : selfFrame.width)
            : (controller.cardFrames[groupId]?.width ?? selfFrame.width)
        let center = inPlace ? selfFrame.center : currentLocation
        controller.draggingClientId = client.id
        controller.sourceGroupId = groupId
        // A device in a multi-member group can be dropped on the background to
        // leave it; a standalone device has no group to leave.
        controller.canLeaveGroup = (store.groups.first(where: { $0.id == groupId })?.clients.count ?? 0) > 1
        controller.previewWidth = width
        controller.grabOffset = CGSize(width: currentLocation.x - center.x,
                                       height: currentLocation.y - center.y)
        controller.dragLocation = currentLocation
        // A single-device card carries its source trigger on the name row; the
        // floating preview must keep it so the lifted card matches the resting
        // card's dimensions exactly (without it the name row collapses to text
        // height and the preview reads shorter). Rows lifted out of a multi-card
        // never have a trigger, so it's gated on the in-place (single-card) lift.
        let source = inPlace
            ? store.groups.first(where: { $0.id == groupId }).flatMap { store.currentSource(of: $0) }
            : nil
        controller.preview = AnyView(
            DeviceDragPreview(client: client, source: source, showSource: inPlace)
                .environmentObject(store)
        )

        // Detent: the preview appears at exactly `detentDip` — the single floor of
        // the dip, the ONLY number that scales the card down in this moment — then
        // springs straight up to the slightly-enlarged drag scale (the low-damping
        // settle overshoots), so the card reads as a click past the detent and a
        // lift proud of the page. No intermediate `holdScale` start and no second
        // spring stage, so `detentDip` has full, sole control of the dip depth.
        controller.previewScale = reduceMotion ? dragScale : detentDip
        if !reduceMotion {
            withAnimation(.spring(response: 0.30, dampingFraction: 0.55)) { controller.previewScale = dragScale }
        }
        controller.updateHover()
    }

    private func performDrop() {
        if let target = controller.hoverGroupId, let g = store.groups.first(where: { $0.id == target }) {
            Haptics.success()
            let home = store.homeClientId(of: g) ?? g.id
            lifted = false                       // source slot is leaving; drop its placeholder
            // The destination card grows a row to accept the device (animated
            // inside `joinGroup`); meanwhile the float glides down into that card
            // and dissolves, so it reads as landing in its new home rather than
            // vanishing in place.
            let landing = controller.cardFrames[target].map {
                CGPoint(x: $0.midX + controller.grabOffset.width,
                        y: $0.maxY + controller.grabOffset.height)
            }
            Task { await store.joinGroup(clientId: client.id, targetHomeClientId: home) }
            withAnimation(.fxEase) {
                if let landing { controller.dragLocation = landing }
                controller.previewScale = 0.92
                controller.previewOpacity = 0
            } completion: {
                controller.reset()
            }
        } else if controller.hoverBackground {
            // Dropped on empty background — leave the group, returning the device
            // to its own. The list re-renders it as a standalone card.
            Haptics.success()
            Task { await store.returnHome(clientId: client.id) }
            lifted = false
            withAnimation(.fxEase) { controller.reset() }
        } else {
            returnToOrigin()
        }
    }

    /// Released over no valid target: glide the floating preview back over the
    /// slot it lifted from (where the placeholder still sits) and settle it to 1×.
    /// At 1× the float is pixel- AND shadow-identical to the resting card (see
    /// `previewLift`), so the swap in the completion handler — reveal the real
    /// card, drop the float — happens in a single frame with NO crossfade: two
    /// identical frames make it invisible.
    private func returnToOrigin() {
        Haptics.tap()
        // Preview center = dragLocation − grabOffset, so the landing point that
        // puts the center back over the source slot is selfFrame.center + offset.
        let landing = CGPoint(x: selfFrame.center.x + controller.grabOffset.width,
                              y: selfFrame.center.y + controller.grabOffset.height)
        if matchesSource {
            // Float is pixel-identical to the slot — settle to 1× then swap in a
            // single frame on completion, no crossfade.
            withAnimation(.fxEase) {
                controller.dragLocation = landing
                controller.previewScale = 1
            } completion: {
                lifted = false           // real card reappears in its slot…
                controller.reset()       // …and the float is removed in the same frame
            }
        } else {
            // Float is a synthesized single-device card, not a pixel match for its
            // slot (a media card's device sub-panel, or a multi-card row), so
            // crossfade the real content back in as the float settles and fades.
            withAnimation(.fxEase) {
                controller.dragLocation = landing
                controller.previewScale = 1
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.30) {
                lifted = false
                withAnimation(.fxQuick) { controller.reset() }
            }
        }
    }
}

extension View {
    /// Make a card (single-device) or a device row liftable into a regroup drag.
    /// Passing a nil client is a no-op, so callers can gate inline.
    @ViewBuilder
    func liftToRegroup(client: SnapClient?, groupId: String, inPlace: Bool,
                       matchesSource: Bool = true) -> some View {
        if let client {
            modifier(LiftToRegroup(client: client, groupId: groupId, inPlace: inPlace,
                                   matchesSource: matchesSource))
        } else {
            self
        }
    }
}

// MARK: - Floating preview (looks like a single-device card)

/// The thing that floats under the finger while dragging — a compact
/// single-device card (name + a static volume fill), matching the resting
/// single-device card so a lifted row reads as "this device, on its own."
struct DeviceDragPreview: View {
    @EnvironmentObject private var store: FauxnosStore
    let client: SnapClient
    /// The group's active source, used to pick the trigger glyph (single-card
    /// lifts only — `showSource` gates whether the trigger renders at all).
    var source: String? = nil
    var showSource: Bool = false

    private var level: Int { store.volume(for: client) }

    var body: some View {
        VStack(alignment: .leading, spacing: Space.xs) {
            HStack(spacing: Space.md) {
                Text(store.displayName(for: client))
                    .font(FxFont.nameDevice).foregroundStyle(FX.text).lineLimit(1)
                Spacer(minLength: 0)
                if showSource { staticSourceTrigger }
            }
            HStack(spacing: Space.md) {
                VolumeIcon(level: level, size: 20, tint: FX.text2).frame(width: 22)
                GeometryReader { geo in
                    let pct = CGFloat(min(max(level, 0), 100)) / 100
                    ZStack(alignment: .leading) {
                        Capsule().fill(FX.surface3).frame(height: 6)
                        Capsule().fill(FX.text).frame(width: max(6, geo.size.width * pct), height: 6)
                    }
                    .frame(maxHeight: .infinity, alignment: .center)
                }
                // Match `FxSlider`'s 28pt track height so the capsule sits at the
                // same vertical center as a resting row — at 22pt it rode ~3pt
                // higher, pinching the gap below the title.
                .frame(height: 28)
            }
        }
        .padding(.horizontal, Space.xl)
        .padding(.vertical, Space.lg)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: Radius.card, style: .circular).fill(FX.surface1))
        .overlay(RoundedRectangle(cornerRadius: Radius.card, style: .circular).strokeBorder(FX.lineStrong, lineWidth: 1))
        // No shadow here — the float layer (GroupsListView.dragPreview) casts it,
        // with a radius driven by the live drag scale so it grows and shrinks
        // with the card during the press / detent / lift animation.
    }

    /// A non-interactive twin of `GroupCard.sourceTrigger` — icon + chevron, no
    /// label — matching its glyphs, spacing, 40pt height and horizontal padding
    /// so the lifted preview's name row keeps the resting card's exact height.
    private var staticSourceTrigger: some View {
        HStack(spacing: Space.xs) {
            TablerIcon(glyph: sourceTablerGlyph(source), size: 22)
            TablerIcon(glyph: .chevronDown, size: 14)
        }
        .foregroundStyle(FX.text)
        .frame(height: 40)
        .padding(.horizontal, Space.sm)
    }
}
