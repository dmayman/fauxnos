//
//  VolumeIcon.swift
//  Fauxnos
//
//  The custom speaker glyph from the web UI (`VolumeSlider.jsx`'s `VolumeIcon`),
//  ported faithfully. It's not a Tabler icon — the web hand-rolled an SVG so the
//  speaker body reads as a solid fill while the waves stay crisp strokes (filled
//  wave crescents smudge at 16px). Three states, exactly as the web:
//    high → body + two wave arcs
//    low  → body + one wave arc
//    mute → body + an X     (used only at volume 0)
//
//  Rather than hand-translate the SVG to SwiftUI shapes, we ship a minimal
//  path-data parser (`SVGPath`) and feed it the web's exact `d` strings from a
//  24×24 viewBox, then scale to the requested size. Reusable for any future
//  custom SVG glyph we want to mirror from the web.
//

import SwiftUI

struct VolumeIcon: View {
    enum State { case high, low, mute }

    var level: Int
    var size: CGFloat = 18
    var tint: Color = FX.text2

    /// Mirrors the web `volIconState`: mute reserved for 0 only.
    private var state: State {
        if level <= 0 { return .mute }
        if level < 40 { return .low }
        return .high
    }

    // Exact path data from VolumeSlider.jsx (24×24 viewBox).
    private static let body =
        "M11 4.3L6.4 8H4a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.4l4.6 3.7a1 1 0 0 0 1.6-.8V5.1a1 1 0 0 0-1.6-.8z"
    private static let waveInner = "M16 9a4 4 0 0 1 0 6"
    private static let waveOuter = "M19 6a8 8 0 0 1 0 12"
    private static let muteA = "M17 9l5 6"
    private static let muteB = "M22 9l-5 6"

    var body: some View {
        let s = size / 24
        let stroke = StrokeStyle(lineWidth: 2 * s, lineCap: .round, lineJoin: .round)
        let xf = CGAffineTransform(scaleX: s, y: s)
        ZStack {
            SVGPath.parse(Self.body).applying(xf).fill(tint)
            switch state {
            case .high:
                SVGPath.parse(Self.waveInner).applying(xf).stroke(tint, style: stroke)
                SVGPath.parse(Self.waveOuter).applying(xf).stroke(tint, style: stroke)
            case .low:
                SVGPath.parse(Self.waveInner).applying(xf).stroke(tint, style: stroke)
            case .mute:
                SVGPath.parse(Self.muteA).applying(xf).stroke(tint, style: stroke)
                SVGPath.parse(Self.muteB).applying(xf).stroke(tint, style: stroke)
            }
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}

// MARK: - Minimal SVG path-data → SwiftUI Path

/// Parses the subset of SVG path commands the Fauxnos custom glyphs use
/// (M/m L/l H/h V/v C/c A/a Z/z), in the source viewBox coordinate space.
/// Elliptical arcs are flattened to line segments via the SVG endpoint→center
/// conversion, which sidesteps SwiftUI's arc-direction ambiguity and renders
/// crisply at icon sizes.
enum SVGPath {
    static func parse(_ d: String) -> Path {
        var path = Path()
        var nums: [CGFloat] = []
        var cmd: Character = " "
        var cur = CGPoint.zero
        var start = CGPoint.zero
        let scanner = Scanner(d)

        func flush() {
            guard cmd != " " else { nums.removeAll(); return }
            let rel = cmd.isLowercase
            let c = Character(cmd.uppercased())
            var i = 0
            func next() -> CGFloat { defer { i += 1 }; return nums[i] }
            switch c {
            case "M":
                guard i + 1 < nums.count else { break }
                var m = CGPoint(x: next(), y: next())
                if rel { m.x += cur.x; m.y += cur.y }
                path.move(to: m); cur = m; start = m
                // Any further coordinate pairs after a moveto are implicit linetos.
                while i + 1 < nums.count {
                    var p = CGPoint(x: next(), y: next())
                    if rel { p.x += cur.x; p.y += cur.y }
                    path.addLine(to: p); cur = p
                }
            case "L":
                while i + 1 < nums.count {
                    var p = CGPoint(x: next(), y: next()); if rel { p.x += cur.x; p.y += cur.y }
                    path.addLine(to: p); cur = p
                }
            case "H":
                while i < nums.count {
                    let x = next(); let nx = rel ? cur.x + x : x
                    cur.x = nx; path.addLine(to: cur)
                }
            case "V":
                while i < nums.count {
                    let y = next(); let ny = rel ? cur.y + y : y
                    cur.y = ny; path.addLine(to: cur)
                }
            case "C":
                while i + 5 < nums.count {
                    var c1 = CGPoint(x: next(), y: next())
                    var c2 = CGPoint(x: next(), y: next())
                    var p = CGPoint(x: next(), y: next())
                    if rel {
                        c1.x += cur.x; c1.y += cur.y; c2.x += cur.x; c2.y += cur.y; p.x += cur.x; p.y += cur.y
                    }
                    path.addCurve(to: p, control1: c1, control2: c2); cur = p
                }
            case "A":
                while i + 6 < nums.count {
                    let rx = next(), ry = next(), rot = next(), fa = next(), fs = next()
                    var p = CGPoint(x: next(), y: next()); if rel { p.x += cur.x; p.y += cur.y }
                    appendArc(&path, from: cur, to: p, rx: rx, ry: ry,
                              rotDeg: rot, largeArc: fa != 0, sweep: fs != 0)
                    cur = p
                }
            case "Z":
                path.closeSubpath(); cur = start
            default: break
            }
            nums.removeAll()
        }

        while let tok = scanner.nextToken() {
            switch tok {
            case .command(let ch):
                flush()
                cmd = ch
                if ch == "Z" || ch == "z" { flush() }
            case .number(let v):
                nums.append(v)
            }
        }
        flush()
        return path
    }

    /// SVG endpoint→center arc conversion, sampled to line segments.
    private static func appendArc(_ path: inout Path, from p1: CGPoint, to p2: CGPoint,
                                  rx rx0: CGFloat, ry ry0: CGFloat,
                                  rotDeg: CGFloat, largeArc: Bool, sweep: Bool) {
        guard rx0 != 0, ry0 != 0 else { path.addLine(to: p2); return }
        var rx = abs(rx0), ry = abs(ry0)
        let phi = rotDeg * .pi / 180
        let cosP = cos(phi), sinP = sin(phi)
        let dx = (p1.x - p2.x) / 2, dy = (p1.y - p2.y) / 2
        let x1 = cosP * dx + sinP * dy
        let y1 = -sinP * dx + cosP * dy
        let lambda = (x1 * x1) / (rx * rx) + (y1 * y1) / (ry * ry)
        if lambda > 1 { let s = lambda.squareRoot(); rx *= s; ry *= s }
        let sign: CGFloat = (largeArc != sweep) ? 1 : -1
        let num = max(0, rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1)
        let den = rx * rx * y1 * y1 + ry * ry * x1 * x1
        let coef = sign * (den == 0 ? 0 : (num / den).squareRoot())
        let cxp = coef * rx * y1 / ry
        let cyp = -coef * ry * x1 / rx
        let cx = cosP * cxp - sinP * cyp + (p1.x + p2.x) / 2
        let cy = sinP * cxp + cosP * cyp + (p1.y + p2.y) / 2

        func angle(_ ux: CGFloat, _ uy: CGFloat, _ vx: CGFloat, _ vy: CGFloat) -> CGFloat {
            let dot = ux * vx + uy * vy
            let len = (ux * ux + uy * uy).squareRoot() * (vx * vx + vy * vy).squareRoot()
            var a = acos(min(1, max(-1, dot / len)))
            if ux * vy - uy * vx < 0 { a = -a }
            return a
        }
        let theta1 = angle(1, 0, (x1 - cxp) / rx, (y1 - cyp) / ry)
        var dtheta = angle((x1 - cxp) / rx, (y1 - cyp) / ry, (-x1 - cxp) / rx, (-y1 - cyp) / ry)
        if !sweep, dtheta > 0 { dtheta -= 2 * .pi }
        if sweep, dtheta < 0 { dtheta += 2 * .pi }

        let steps = max(2, Int((abs(dtheta) / (.pi / 16)).rounded(.up)))
        for s in 1...steps {
            let t = theta1 + dtheta * CGFloat(s) / CGFloat(steps)
            let ex = cosP * rx * cos(t) - sinP * ry * sin(t) + cx
            let ey = sinP * rx * cos(t) + cosP * ry * sin(t) + cy
            path.addLine(to: CGPoint(x: ex, y: ey))
        }
    }

    // MARK: tokenizer

    private enum Token { case command(Character); case number(CGFloat) }

    private final class Scanner {
        private let chars: [Character]
        private var idx = 0
        init(_ s: String) { chars = Array(s) }

        func nextToken() -> Token? {
            while idx < chars.count, chars[idx] == " " || chars[idx] == "," || chars[idx] == "\n" || chars[idx] == "\t" {
                idx += 1
            }
            guard idx < chars.count else { return nil }
            let ch = chars[idx]
            if ch.isLetter {
                idx += 1
                return .command(ch)
            }
            // number: optional sign, digits, dot, exponent
            var str = ""
            if ch == "-" || ch == "+" { str.append(ch); idx += 1 }
            while idx < chars.count {
                let c = chars[idx]
                if c.isNumber || c == "." { str.append(c); idx += 1 }
                else if c == "e" || c == "E" {
                    str.append(c); idx += 1
                    if idx < chars.count, chars[idx] == "-" || chars[idx] == "+" { str.append(chars[idx]); idx += 1 }
                } else { break }
            }
            return .number(CGFloat(Double(str) ?? 0))
        }
    }
}
