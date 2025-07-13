//
//  ContentView.swift
//  WSTest
//
//  Created by David Mayman on 5/25/25.
//

import SwiftUI

struct ContentView: View {
    @State private var position = CGSize.zero
    @State private var dragOffset = CGSize.zero
    @State private var isTouching = false
    
    private let normalSize: CGFloat = 20
    private let touchedSize: CGFloat = 100
    
    var body: some View {
        ZStack {
            Color.white
                .edgesIgnoringSafeArea(.all)
            
            let scale = isTouching ? touchedSize / normalSize : 1.0
            
            Circle()
                .fill(Color.black)
                .frame(width: normalSize, height: normalSize)
                .scaleEffect(scale, anchor: .center)
                .offset(x: position.width + dragOffset.width, y: position.height + dragOffset.height)
                .gesture(
                    DragGesture(minimumDistance: 0)
                        .onChanged { value in
                            dragOffset = value.translation
                            if !isTouching {
                                withAnimation(.easeInOut(duration: 0.1)) {
                                    isTouching = true
                                }
                            }
                        }
                        .onEnded { value in
                            position.width += value.translation.width
                            position.height += value.translation.height
                            dragOffset = .zero
                            withAnimation(.easeInOut(duration: 0.1)) {
                                isTouching = false
                            }
                        }
                )
        }
    }
}

#Preview {
    ContentView()
}
