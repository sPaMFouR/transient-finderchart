import AppKit
import SwiftUI

@main
struct findingchart_macapp: App {
    @StateObject private var vm = PipelineViewModel()

    var body: some Scene {
        Window("Transient Finderchart", id: "main") {
            ContentView(vm: vm)
                .frame(minWidth: 980, minHeight: 640)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(HaloBackground())
                .background(WindowConfigurator())
                .preferredColorScheme(.dark)
                .task {
                    vm.loadMetadata()
                }
        }
        .windowResizability(.contentMinSize)
    }
}

struct WindowConfigurator: NSViewRepresentable {
    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        DispatchQueue.main.async {
            configure(view.window)
        }
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        DispatchQueue.main.async {
            configure(nsView.window)
        }
    }

    private func configure(_ window: NSWindow?) {
        guard let window else { return }
        window.styleMask.insert(.resizable)
        window.minSize = NSSize(width: 980, height: 640)
        window.maxSize = NSSize(width: 10000, height: 10000)
    }
}

struct ContentView: View {
    @ObservedObject var vm: PipelineViewModel

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 0) {
                ControlSidebar(vm: vm)
                PlotPanel(vm: vm)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            statusBar
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var statusBar: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(statusColor)
                .frame(width: 8, height: 8)
                .shadow(color: statusColor.opacity(0.8), radius: 5)
            Text(vm.status)
                .font(AppFont.body(12))
                .foregroundStyle(Palette.textSecondary)
            Spacer()
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 9)
        .background(Color.black.opacity(0.22))
        .overlay(alignment: .top) {
            Rectangle().fill(Color.white.opacity(0.08)).frame(height: 0.5)
        }
    }

    private var statusColor: Color {
        if vm.errorText != nil { return Palette.pink }
        if vm.isRunning { return Palette.amber }
        return Palette.cyan
    }
}
