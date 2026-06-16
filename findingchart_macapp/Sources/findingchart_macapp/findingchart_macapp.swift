import AppKit
import SwiftUI

@main
struct findingchart_macapp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var vm = PipelineViewModel()
    private let defaultWindowSize = CGSize(width: 1200, height: 785)

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
        .defaultSize(width: defaultWindowSize.width, height: defaultWindowSize.height)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }
}

struct WindowConfigurator: NSViewRepresentable {
    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        DispatchQueue.main.async {
            configure(view.window, coordinator: context.coordinator)
        }
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        DispatchQueue.main.async {
            configure(nsView.window, coordinator: context.coordinator)
        }
    }

    private func configure(_ window: NSWindow?, coordinator: Coordinator) {
        guard let window else { return }
        window.styleMask.insert(.resizable)
        window.minSize = NSSize(width: 980, height: 640)
        window.maxSize = NSSize(width: 10000, height: 10000)
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        if !coordinator.didSetInitialSize {
            window.setContentSize(NSSize(width: 1200, height: 785))
            window.center()
            coordinator.didSetInitialSize = true
        }
    }

    final class Coordinator {
        var didSetInitialSize = false
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
            Image(systemName: "arrow.up.left.and.arrow.down.right")
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(Palette.textTertiary)
                .help("Drag a window edge or corner to resize.")
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
