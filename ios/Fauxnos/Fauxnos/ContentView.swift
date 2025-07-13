import SwiftUI

struct ContentView: View {
    var body: some View {
        GeometryReader { geometry in
            ZStack {
                Color.black
                    .edgesIgnoringSafeArea(.all)
                
                // Room blobs with labels
                Blob(
                    id: "living_room",
                    label: "Living Room",
                    initialHomePosition: CGSize(width: -80, height: -120),
                    color: .white
                )
                
                Blob(
                    id: "kitchen",
                    label: "Kitchen",
                    initialHomePosition: CGSize(width: 80, height: 120),
                    color: .white
                )
                
                Blob(
                    id: "outdoor",
                    label: "Outdoor",
                    initialHomePosition: CGSize(width: 0, height: 0),
                    color: .white
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
