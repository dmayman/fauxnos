import SwiftUI
import WebKit

struct ReactWebView: UIViewRepresentable {
    @Binding var isLoading: Bool
    
    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        
        // Set up custom URL scheme handler for your three assets
        let schemeHandler = SimpleAssetsSchemeHandler()
        configuration.setURLSchemeHandler(schemeHandler, forURLScheme: "app")
        
        configuration.allowsInlineMediaPlayback = true
        
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        
        #if DEBUG
        if #available(iOS 16.4, *) {
            webView.isInspectable = true
        }
        #endif
        
        loadIndexFromAssets(in: webView)
        
        return webView
    }
    
    func updateUIView(_ webView: WKWebView, context: Context) {}
    
    func makeCoordinator() -> Coordinator {
        Coordinator(parent: self)
    }
    
    private func loadIndexFromAssets(in webView: WKWebView) {
        guard let htmlData = NSDataAsset(name: "index")?.data,
              var htmlContent = String(data: htmlData, encoding: .utf8) else {
            print("❌ Could not load index.html from Assets")
            return
        }
        
        print("✅ Loaded index.html from Assets")
        
        // Replace all static file references to use our custom scheme
        htmlContent = htmlContent.replacingOccurrences(of: "=\"./static/js/", with: "=\"app://js/")
        htmlContent = htmlContent.replacingOccurrences(of: "=\"/static/js/", with: "=\"app://js/")
        htmlContent = htmlContent.replacingOccurrences(of: "=\"./static/css/", with: "=\"app://css/")
        htmlContent = htmlContent.replacingOccurrences(of: "=\"/static/css/", with: "=\"app://css/")
        
        // Handle single quotes too
        htmlContent = htmlContent.replacingOccurrences(of: "='./static/js/", with: "='app://js/")
        htmlContent = htmlContent.replacingOccurrences(of: "='/static/js/", with: "='app://js/")
        htmlContent = htmlContent.replacingOccurrences(of: "='./static/css/", with: "='app://css/")
        htmlContent = htmlContent.replacingOccurrences(of: "='/static/css/", with: "='app://css/")
        
        print("🔄 Modified HTML to use app:// scheme")
        print("📝 Modified HTML preview:")
        print(String(htmlContent.prefix(500)))
        
        webView.loadHTMLString(htmlContent, baseURL: URL(string: "app://"))
    }
    
    class Coordinator: NSObject, WKNavigationDelegate {
        let parent: ReactWebView
        
        init(parent: ReactWebView) {
            self.parent = parent
        }
        
        func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
            parent.isLoading = true
            print("🚀 WebView started loading")
        }
        
        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            parent.isLoading = false
            print("✅ WebView finished loading")
            
            // Check if React loaded
            webView.evaluateJavaScript("typeof React !== 'undefined' ? 'React loaded' : 'React not found'") { result, error in
                print("⚛️ React status: \(result ?? "unknown")")
            }
        }
        
        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            parent.isLoading = false
            print("❌ WebView failed: \(error.localizedDescription)")
        }
    }
}

class SimpleAssetsSchemeHandler: NSObject, WKURLSchemeHandler {
    func webView(_ webView: WKWebView, start urlSchemeTask: WKURLSchemeTask) {
        guard let url = urlSchemeTask.request.url else {
            urlSchemeTask.didFailWithError(NSError(domain: "InvalidURL", code: 404))
            return
        }
        
        let path = url.path
        print("🔍 Requesting: \(url.absoluteString)")
        
        // Determine which asset to load based on the path
        var assetName: String
        var mimeType: String
        
        if path.contains("/js/") || path.hasSuffix(".js") {
            assetName = "js"
            mimeType = "application/javascript"
            print("📦 Loading JS asset")
        } else if path.contains("/css/") || path.hasSuffix(".css") {
            assetName = "css"
            mimeType = "text/css"
            print("📦 Loading CSS asset")
        } else {
            assetName = "index"
            mimeType = "text/html"
            print("📦 Loading index asset")
        }
        
        guard let assetData = NSDataAsset(name: assetName)?.data else {
            print("❌ Asset '\(assetName)' not found for path: \(path)")
            urlSchemeTask.didFailWithError(NSError(domain: "AssetNotFound", code: 404))
            return
        }
        
        print("✅ Successfully loaded asset: \(assetName) (\(assetData.count) bytes)")
        
        let response = URLResponse(
            url: url,
            mimeType: mimeType,
            expectedContentLength: assetData.count,
            textEncodingName: mimeType.contains("text") ? "utf-8" : nil
        )
        
        urlSchemeTask.didReceive(response)
        urlSchemeTask.didReceive(assetData)
        urlSchemeTask.didFinish()
    }
    
    func webView(_ webView: WKWebView, stop urlSchemeTask: WKURLSchemeTask) {
        // Handle cancellation if needed
    }
}

// Usage View
struct AssetsContentView: View {
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
                        
                        Text("Loading React App from Assets...")
                            .foregroundColor(.secondary)
                            .padding(.top)
                    }
                }
            }
            .navigationTitle("React App")
            .navigationBarTitleDisplayMode(.inline)
        }
    }
}
