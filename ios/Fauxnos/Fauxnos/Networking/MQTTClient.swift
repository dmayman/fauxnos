//
//  MQTTClient.swift
//  Fauxnos
//
//  ── Library choice: raw URLSessionWebSocketTask, not CocoaMQTT ───────────────
//
//  The web client (`useMqtt.js`) talks MQTT-over-websocket to mosquitto's :9001
//  listener via mqtt.js. The obvious Swift equivalents are CocoaMQTT (which
//  wraps Starscream for the websocket transport) or a hand-rolled codec over
//  Apple's own URLSessionWebSocketTask. This client deliberately takes the
//  second path:
//
//    • M1 is receive-only. We SUBSCRIBE to status topics and parse inbound
//      PUBLISH — no QoS>0 publishing, no retained-publish authoring, no TLS,
//      no will. That's a small, well-bounded slice of MQTT 3.1.1: CONNECT,
//      SUBSCRIBE, PINGREQ, and inbound PUBLISH/CONNACK/SUBACK/PINGRESP. Hand-
//      rolling it is a few hundred lines, all of which we control.
//    • Adding a SwiftPM dependency means editing the (hand-authored) Xcode
//      project's package graph without the Xcode GUI, plus carrying a
//      third-party transitive (Starscream) into a security-conscious codebase.
//      URLSessionWebSocketTask is first-party, already permitted by ATS via the
//      local-networking exception, and needs zero project surgery.
//    • Reconnect/keepalive/backoff are things we'd want to own and tune anyway.
//
//  If a later milestone needs heavier MQTT (QoS2, TLS client certs, large
//  retained publishes), revisiting CocoaMQTT is reasonable — the codec here is
//  intentionally minimal, not a general-purpose library.
//
//  Wire framing: MQTT-over-websocket carries raw MQTT control packets inside
//  binary websocket frames, negotiated with the "mqtt" subprotocol. A single
//  frame may hold a partial packet or several packets, so we accumulate bytes
//  in `rxBuffer` and parse whole packets out of it.
//

import Foundation

/// Coarse connection lifecycle surfaced to the UI (FX-86 offline toast).
/// `.connecting` covers the initial dial and every reconnect attempt — the
/// socket opening through CONNACK — and drives the toast's spinner. `.connected`
/// is a live, CONNACK-accepted session (toast hidden). `.disconnected` is the
/// gap between attempts (backoff wait) or a deliberate close — a static
/// "Offline" with no spinner. Since the client reconnects forever with backoff,
/// a down broker reads as `.connecting` during each attempt and `.disconnected`
/// during the widening waits between them.
enum MQTTConnectionState: Equatable {
    case connecting
    case connected
    case disconnected
}

final class MQTTClient: NSObject {
    // MARK: Callbacks (always delivered on the main thread)
    var onMessage: ((_ topic: String, _ payload: Data) -> Void)?
    var onStateChange: ((MQTTConnectionState) -> Void)?

    // MARK: Config
    private let url: URL
    private let topics: [String]
    private let clientId: String
    private let keepAlive: UInt16 = 30   // seconds

    // MARK: State (mutated only on `delegateQueue`, a serial OperationQueue)
    private var session: URLSession!
    private let delegateQueue = OperationQueue()
    private var task: URLSessionWebSocketTask?
    private var rxBuffer = Data()
    private var mqttConnected = false      // CONNACK accepted (publish gate)
    private var connectionState: MQTTConnectionState = .disconnected
    private var shouldRun = false          // user intends to stay connected
    private var reconnectAttempt = 0
    private var pingTimer: DispatchSourceTimer?
    private var nextPacketId: UInt16 = 0

    init(url: URL, topics: [String], clientId: String = "fauxnos-ios-\(UUID().uuidString.prefix(8))") {
        self.url = url
        self.topics = topics
        self.clientId = clientId
        super.init()
        delegateQueue.maxConcurrentOperationCount = 1   // serialize all callbacks
        delegateQueue.name = "fauxnos.mqtt"
        self.session = URLSession(configuration: .default, delegate: self, delegateQueue: delegateQueue)
    }

    // MARK: - Public lifecycle

    func connect() {
        delegateQueue.addOperation { [weak self] in
            guard let self, !self.shouldRun else { return }
            self.shouldRun = true
            self.openSocket()
        }
    }

    func disconnect() {
        delegateQueue.addOperation { [weak self] in
            guard let self else { return }
            self.shouldRun = false
            self.sendRaw([0xE0, 0x00])   // DISCONNECT
            self.teardown(notify: true)
        }
    }

    /// Public outbound QoS-0 PUBLISH — the app's write path (FX-18 volume and
    /// future control writes). Dispatched on the internal serial queue and
    /// gated on a live CONNACK; a publish issued while disconnected is dropped
    /// (callers already hold optimistic UI state and the value re-sends on the
    /// next user move). Fire-and-forget, matching web's `useMqtt` QoS-0 publish.
    func publish(topic: String, payload: Data) {
        delegateQueue.addOperation { [weak self] in
            guard let self, self.mqttConnected else { return }
            self.sendPublish(topic: topic, payload: payload)
        }
    }

    // MARK: - Socket management (delegateQueue only)

    private func openSocket() {
        setState(.connecting)
        rxBuffer.removeAll(keepingCapacity: true)
        let task = session.webSocketTask(with: url, protocols: ["mqtt"])
        self.task = task
        task.resume()
        receiveLoop()
        // CONNECT is sent from `urlSession(_:webSocketTask:didOpenWithProtocol:)`
        // once the handshake completes.
    }

    private func teardown(notify: Bool) {
        pingTimer?.cancel()
        pingTimer = nil
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
        mqttConnected = false
        // We're between attempts now (the reconnect path schedules a delayed
        // openSocket, which flips back to .connecting). A deliberate disconnect
        // stays here. Either way the live socket is gone → .disconnected.
        if notify { setState(.disconnected) }
    }

    private func scheduleReconnect() {
        guard shouldRun else { return }
        reconnectAttempt += 1
        let delay = min(pow(2.0, Double(min(reconnectAttempt, 5))), 30.0)   // 2,4,8,16,30…
        delegateQueue.schedule(after: delay) { [weak self] in
            guard let self, self.shouldRun, self.task == nil else { return }
            self.openSocket()
        }
    }

    // MARK: - Receive loop

    private func receiveLoop() {
        task?.receive { [weak self] result in
            guard let self else { return }
            // Completion runs on the session's (serial) delegateQueue.
            switch result {
            case .failure:
                self.handleSocketDrop()
            case .success(let message):
                switch message {
                case .data(let d): self.rxBuffer.append(d)
                case .string(let s): self.rxBuffer.append(Data(s.utf8))
                @unknown default: break
                }
                self.drainPackets()
                self.receiveLoop()
            }
        }
    }

    private func handleSocketDrop() {
        teardown(notify: true)
        scheduleReconnect()
    }

    // MARK: - Packet parsing

    private func drainPackets() {
        while true {
            guard rxBuffer.count >= 2 else { return }
            let bytes = [UInt8](rxBuffer)
            // Decode the variable-length "remaining length" starting at byte 1.
            var multiplier = 1
            var remaining = 0
            var idx = 1
            var complete = false
            while idx < bytes.count {
                let b = bytes[idx]
                remaining += Int(b & 0x7F) * multiplier
                idx += 1
                if b & 0x80 == 0 { complete = true; break }
                multiplier *= 128
                if multiplier > 128 * 128 * 128 { // malformed; drop the connection
                    handleSocketDrop()
                    return
                }
            }
            guard complete else { return }            // varint not fully arrived
            let headerLen = idx
            let total = headerLen + remaining
            guard bytes.count >= total else { return } // body not fully arrived

            let type = bytes[0] >> 4
            let flags = bytes[0] & 0x0F
            let payload = Array(bytes[headerLen..<total])
            rxBuffer.removeFirst(total)

            switch type {
            case 2:  handleConnack(payload)
            case 3:  handlePublish(flags: flags, payload: payload)
            case 9:  break                  // SUBACK — nothing to do
            case 13: break                  // PINGRESP
            default: break                  // ignore anything else
            }
        }
    }

    private func handleConnack(_ payload: [UInt8]) {
        // Variable header: [ack flags, return code]. 0 == accepted.
        guard payload.count >= 2, payload[1] == 0 else {
            handleSocketDrop()
            return
        }
        mqttConnected = true
        reconnectAttempt = 0
        subscribe()
        // Prime initial state: ask every connected device to broadcast `hello`
        // (and its retained track/playback), mirroring useMqtt.js. This is a
        // get-request, not a control/write action. We're already on the
        // delegate queue with a live connection, so call the encoder directly.
        sendPublish(topic: "get/clients/all/status", payload: Data())
        startPing()
        setState(.connected)
    }

    private func handlePublish(flags: UInt8, payload: [UInt8]) {
        guard payload.count >= 2 else { return }
        let topicLen = (Int(payload[0]) << 8) | Int(payload[1])
        var cursor = 2
        guard payload.count >= cursor + topicLen else { return }
        let topicBytes = payload[cursor..<cursor + topicLen]
        cursor += topicLen
        guard let topic = String(bytes: topicBytes, encoding: .utf8) else { return }

        let qos = (flags >> 1) & 0x03
        var ackId: UInt16?
        if qos > 0 {
            guard payload.count >= cursor + 2 else { return }
            ackId = (UInt16(payload[cursor]) << 8) | UInt16(payload[cursor + 1])
            cursor += 2
        }
        let body = Data(payload[cursor...])
        if let ackId, qos == 1 {
            sendRaw([0x40, 0x02, UInt8(ackId >> 8), UInt8(ackId & 0xFF)])  // PUBACK
        }
        emitMessage(topic: topic, payload: body)
    }

    // MARK: - Outbound packets

    private func sendConnect() {
        var vh = stringField("MQTT")
        vh.append(0x04)                                  // protocol level 3.1.1
        vh.append(0x02)                                  // connect flags: clean session
        vh.append(UInt8(keepAlive >> 8))
        vh.append(UInt8(keepAlive & 0xFF))
        var body = vh
        body.append(contentsOf: stringField(clientId))
        sendRaw(framed(type: 0x10, body: body))
    }

    private func subscribe() {
        guard !topics.isEmpty else { return }
        let pid = makePacketId()
        var body: [UInt8] = [UInt8(pid >> 8), UInt8(pid & 0xFF)]
        for topic in topics {
            body.append(contentsOf: stringField(topic))
            body.append(0x00)                            // requested QoS 0
        }
        sendRaw(framed(type: 0x82, body: body))          // SUBSCRIBE (flags 0010 required)
    }

    /// QoS-0 publish encoder. Must be called on `delegateQueue` with a live
    /// connection (the public `publish` and the CONNACK prime both guarantee
    /// that). QoS 0 carries no packet id and expects no PUBACK.
    private func sendPublish(topic: String, payload: Data) {
        var body = stringField(topic)
        body.append(contentsOf: payload)
        sendRaw(framed(type: 0x30, body: body))
    }

    private func startPing() {
        pingTimer?.cancel()
        let timer = DispatchSource.makeTimerSource(queue: DispatchQueue.global())
        timer.schedule(deadline: .now() + Double(keepAlive), repeating: Double(keepAlive))
        timer.setEventHandler { [weak self] in
            self?.sendRaw([0xC0, 0x00])                  // PINGREQ
        }
        timer.resume()
        pingTimer = timer
    }

    // MARK: - Encoding helpers

    /// MQTT string field: 2-byte big-endian length prefix + UTF-8 bytes.
    private func stringField(_ s: String) -> [UInt8] {
        let utf8 = [UInt8](s.utf8)
        return [UInt8(utf8.count >> 8), UInt8(utf8.count & 0xFF)] + utf8
    }

    /// Wrap a body in a fixed header: type/flags byte + remaining-length varint.
    private func framed(type: UInt8, body: [UInt8]) -> [UInt8] {
        var packet: [UInt8] = [type]
        var len = body.count
        repeat {
            var byte = UInt8(len % 128)
            len /= 128
            if len > 0 { byte |= 0x80 }
            packet.append(byte)
        } while len > 0
        packet.append(contentsOf: body)
        return packet
    }

    private func makePacketId() -> UInt16 {
        nextPacketId &+= 1
        if nextPacketId == 0 { nextPacketId = 1 }        // 0 is illegal
        return nextPacketId
    }

    private func sendRaw(_ bytes: [UInt8]) {
        // URLSessionWebSocketTask.send is safe to call from any thread.
        task?.send(.data(Data(bytes))) { [weak self] error in
            if error != nil { self?.delegateQueue.addOperation { self?.handleSocketDrop() } }
        }
    }

    // MARK: - Main-thread callback dispatch

    /// Update the lifecycle state and notify the UI, de-duping no-op transitions
    /// (e.g. a teardown that's already `.disconnected`) so the toast doesn't
    /// thrash. Runs on `delegateQueue`; the callback hops to main.
    private func setState(_ state: MQTTConnectionState) {
        guard connectionState != state else { return }
        connectionState = state
        DispatchQueue.main.async { [weak self] in self?.onStateChange?(state) }
    }

    private func emitMessage(topic: String, payload: Data) {
        DispatchQueue.main.async { [weak self] in self?.onMessage?(topic, payload) }
    }
}

// MARK: - URLSessionWebSocketDelegate

extension MQTTClient: URLSessionWebSocketDelegate {
    func urlSession(_ session: URLSession,
                    webSocketTask: URLSessionWebSocketTask,
                    didOpenWithProtocol protocol: String?) {
        // Handshake complete — start the MQTT session.
        sendConnect()
    }

    func urlSession(_ session: URLSession,
                    webSocketTask: URLSessionWebSocketTask,
                    didCloseWith closeCode: URLSessionWebSocketTask.CloseCode,
                    reason: Data?) {
        handleSocketDrop()
    }
}

// MARK: - OperationQueue delayed scheduling

private extension OperationQueue {
    func schedule(after seconds: Double, _ block: @escaping () -> Void) {
        let work = DispatchWorkItem(block: block)
        DispatchQueue.global().asyncAfter(deadline: .now() + seconds) { [weak self] in
            self?.addOperation { work.perform() }
        }
    }
}
