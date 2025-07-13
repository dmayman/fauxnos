import SwiftUI

struct ContentView: View {
    @State private var position: CGSize = .zero
    @State private var isPressed = false
    
    var body: some View {
        GeometryReader { geometry in
            ZStack {
                Color.white
                    .edgesIgnoringSafeArea(.all)
                
                Circle()
                    .fill(Color.black)
                    .frame(width: isPressed ? 100 : 20, 
                          height: isPressed ? 100 : 20)
                    .offset(position)
                    .gesture(
                        DragGesture()
                            .onChanged { gesture in
                                self.position = gesture.translation
                            }
                    )
                    .simultaneousGesture(
                        DragGesture(minimumDistance: 0)
                            .onChanged { _ in
                                withAnimation(.spring()) {
                                    isPressed = true
                                }
                            }
                            .onEnded { _ in
                                withAnimation(.spring()) {
                                    isPressed = false
                                }
                            }
                    )
            }
            .frame(width: geometry.size.width, height: geometry.size.height)
        }
    }
}

struct ContentView_Previews: PreviewProvider {
    static var previews: some View {
        ContentView()
    }
}