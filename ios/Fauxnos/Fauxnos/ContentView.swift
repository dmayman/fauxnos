import SwiftUI

struct ContentView: View {
    @State private var isLoading = true
    
    var body: some View {
        NavigationView {
            ZStack {
                ReactWebView(isLoading: $isLoading)
                
                if isLoading {
                    VStack {
                        ProgressView()
                            .progressViewStyle(CircularProgressViewStyle(tint: .blue))
                            .scaleEffect(1.5)
                        
                        Text("Loading & Debugging...")
                            .foregroundColor(.secondary)
                            .padding(.top)
                    }
                }
            }
            .navigationTitle("Debug React App")
            .navigationBarTitleDisplayMode(.inline)
        }
    }
}
