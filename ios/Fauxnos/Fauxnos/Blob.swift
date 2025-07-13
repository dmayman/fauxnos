import SwiftUI

struct Blob: View {
    @State private var position = CGSize.zero
    @State private var dragOffset = CGSize.zero
    @State private var homePosition = CGSize.zero
    @State private var isTouching = false
    @State private var isTapped = false
    @State private var forceTouch = false
    @State private var ambientTimer: Timer?
    @State private var movementOffset: CGFloat = 0
    @State private var movementSpeed: CGFloat = 0.3
    @State private var movementAmplitude: CGFloat = 30
    @State private var xFrequency: CGFloat = 1.0
    @State private var yFrequency: CGFloat = 0.7
    
    let id: String
    let initialHomePosition: CGSize
    let normalSize: CGFloat
    let touchedSize: CGFloat
    let color: Color
    let label: String
    
    var onPositionChange: ((String, CGSize) -> Void)?
    var onTouchStateChange: ((String, Bool) -> Void)?
    var onTapStateChange: ((String, Bool) -> Void)?
    var onForceTouch: ((String, Bool) -> Void)?
    var onHomePositionChange: ((String, CGSize) -> Void)?
    
    init(
        id: String,
        label: String,
        initialHomePosition: CGSize = .zero,
        normalSize: CGFloat = 8,
        touchedSize: CGFloat = 84,
        color: Color = .white,
        onPositionChange: ((String, CGSize) -> Void)? = nil,
        onTouchStateChange: ((String, Bool) -> Void)? = nil,
        onTapStateChange: ((String, Bool) -> Void)? = nil,
        onForceTouch: ((String, Bool) -> Void)? = nil,
        onHomePositionChange: ((String, CGSize) -> Void)? = nil
    ) {
        self.id = id
        self.label = label
        self.initialHomePosition = initialHomePosition
        self.normalSize = normalSize
        self.touchedSize = touchedSize
        self.color = color
        self.onPositionChange = onPositionChange
        self.onTouchStateChange = onTouchStateChange
        self.onTapStateChange = onTapStateChange
        self.onForceTouch = onForceTouch
        self.onHomePositionChange = onHomePositionChange
        self._homePosition = State(initialValue: initialHomePosition)
        self._position = State(initialValue: initialHomePosition)
        
        // Generate unique random movement parameters for each circle
        let idHash = abs(id.hashValue)
        self._movementOffset = State(initialValue: CGFloat(idHash % 1000) / 100.0)
        self._movementSpeed = State(initialValue: 0.2 + CGFloat(idHash % 100) / 500.0) // 0.2 to 0.4
        self._movementAmplitude = State(initialValue: 20 + CGFloat(idHash % 50)) // 20 to 70
        self._xFrequency = State(initialValue: 0.8 + CGFloat(idHash % 40) / 100.0) // 0.8 to 1.2
        self._yFrequency = State(initialValue: 0.5 + CGFloat(idHash % 60) / 100.0) // 0.5 to 1.1
    }
    
    private var scale: CGFloat {
        if forceTouch {
            return (touchedSize * 1.2) / normalSize
        } else if isTouching {
            return touchedSize / normalSize
        } else if isTapped {
            return (touchedSize * 0.8) / normalSize
        } else {
            return 1.0
        }
    }
    
    private var circleColor: Color {
        if forceTouch {
            return color.opacity(0.8)
        } else if isTapped {
            return color.opacity(0.6)
        } else {
            return color
        }
    }
    
    var body: some View {
        VStack(spacing: 8) {
            ZStack {
                // Background circle (32x32, 10% opacity)
                Circle()
                    .fill(color.opacity(0.1))
                    .frame(width: 32, height: 32)
                
                // Main blob circle
                Circle()
                    .fill(circleColor)
                    .frame(width: normalSize, height: normalSize)
                    .scaleEffect(scale, anchor: .center)
            }
            
            // Text label below the blob
            Text(label)
                .font(.system(size: 12, weight: .medium))
                .foregroundColor(color)
                .offset(y: isTouching ? max(0, (touchedSize - 32) / 2) : 0) // Push down when blob grows
        }
        .offset(x: position.width + dragOffset.width, y: position.height + dragOffset.height)
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { value in
                        dragOffset = value.translation
                        
                        if !isTouching {
                            withAnimation(.easeInOut(duration: 0.1)) {
                                isTouching = true
                            }
                            onTouchStateChange?(id, true)
                            stopAmbientMovement()
                        }
                        
                        let currentPosition = CGSize(
                            width: homePosition.width + dragOffset.width,
                            height: homePosition.height + dragOffset.height
                        )
                        onPositionChange?(id, currentPosition)
                    }
                    .onEnded { value in
                        // Update position to current drag location first
                        position = CGSize(
                            width: homePosition.width + value.translation.width,
                            height: homePosition.height + value.translation.height
                        )
                        dragOffset = .zero
                        
                        withAnimation(.easeInOut(duration: 0.1)) {
                            isTouching = false
                        }
                        onTouchStateChange?(id, false)
                        
                        // Snap back to home position with spring animation
                        withAnimation(.spring(response: 0.6, dampingFraction: 0.7)) {
                            position = homePosition
                        }
                        
                        onPositionChange?(id, homePosition)
                        startAmbientMovement()
                        
                        // Handle tap detection (small movement)
                        let distance = sqrt(value.translation.width * value.translation.width + 
                                          value.translation.height * value.translation.height)
                        if distance < 5 {
                            handleTap()
                        }
                    }
            )
            .onAppear {
                startAmbientMovement()
                setupNotifications()
            }
            .onDisappear {
                stopAmbientMovement()
                removeNotifications()
            }
    }
    
    private func handleTap() {
        withAnimation(.easeInOut(duration: 0.15)) {
            isTapped = true
        }
        onTapStateChange?(id, true)
        
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) {
            withAnimation(.easeInOut(duration: 0.15)) {
                isTapped = false
            }
            onTapStateChange?(id, false)
        }
    }
    
    // MARK: - Ambient Movement
    private func startAmbientMovement() {
        stopAmbientMovement()
        ambientTimer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { _ in
            updateAmbientPosition()
        }
    }
    
    private func stopAmbientMovement() {
        ambientTimer?.invalidate()
        ambientTimer = nil
    }
    
    private func updateAmbientPosition() {
        guard !isTouching else { return }
        
        let time = Date().timeIntervalSince1970 + movementOffset
        
        // Create unique movement pattern for each circle
        let xMovement = sin(time * movementSpeed * xFrequency) * movementAmplitude
        let yMovement = cos(time * movementSpeed * yFrequency) * movementAmplitude * 0.6
        
        // Add some secondary harmonics for more organic movement
        let secondaryX = sin(time * movementSpeed * xFrequency * 2.3) * (movementAmplitude * 0.3)
        let secondaryY = cos(time * movementSpeed * yFrequency * 1.7) * (movementAmplitude * 0.2)
        
        let newHomePosition = CGSize(
            width: initialHomePosition.width + xMovement + secondaryX,
            height: initialHomePosition.height + yMovement + secondaryY
        )
        
        // Smooth animation to new home position
        withAnimation(.easeInOut(duration: 0.2)) {
            homePosition = newHomePosition
            if !isTouching {
                position = newHomePosition
            }
        }
        
        onHomePositionChange?(id, newHomePosition)
    }
    
    // MARK: - Notifications (simplified)
    private func setupNotifications() {
        // No longer needed since we removed collision displacement
    }
    
    private func removeNotifications() {
        // No longer needed since we removed collision displacement
    }
    
    // MARK: - Public Methods
    func triggerForceTouch(_ active: Bool) {
        withAnimation(.easeInOut(duration: 0.1)) {
            forceTouch = active
        }
        onForceTouch?(id, active)
    }
    
    func updateHomePosition(_ newHome: CGSize) {
        homePosition = newHome
        if !isTouching {
            withAnimation(.spring(response: 0.6, dampingFraction: 0.7)) {
                position = newHome
            }
        }
    }
    
    func getCurrentPosition() -> CGSize {
        return isTouching ? CGSize(width: homePosition.width + dragOffset.width, 
                                  height: homePosition.height + dragOffset.height) : position
    }
}