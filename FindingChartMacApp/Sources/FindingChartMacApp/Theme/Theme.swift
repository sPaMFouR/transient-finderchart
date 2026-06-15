import SwiftUI

enum Palette {
    static let base = Color(hex: 0x0A0B14)
    static let violet = Color(hex: 0x8B7BFF)
    static let cyan = Color(hex: 0x3FE0D0)
    static let pink = Color(hex: 0xFF6F93)
    static let amber = Color(hex: 0xF0B34B)
    static let textPrimary = Color.white
    static let textSecondary = Color(hex: 0xAEB2CC)
    static let textTertiary = Color(hex: 0x6F7494)

    static let accentGradient = LinearGradient(
        colors: [violet, cyan],
        startPoint: .leading,
        endPoint: .trailing
    )
}

extension Color {
    init(hex: UInt32, alpha: Double = 1) {
        self.init(
            .sRGB,
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255,
            opacity: alpha
        )
    }
}

enum AppFont {
    static func title(_ size: CGFloat) -> Font { .system(size: size, weight: .semibold, design: .rounded) }
    static func body(_ size: CGFloat) -> Font { .system(size: size, weight: .regular, design: .rounded) }
    static func mono(_ size: CGFloat) -> Font { .system(size: size, weight: .medium, design: .monospaced) }
}

struct HaloBackground: View {
    var body: some View {
        ZStack {
            Palette.base
            RadialGradient(colors: [Palette.violet.opacity(0.24), .clear], center: .topLeading, startRadius: 0, endRadius: 620)
            RadialGradient(colors: [Palette.cyan.opacity(0.18), .clear], center: .bottomTrailing, startRadius: 0, endRadius: 680)
            RadialGradient(colors: [Palette.pink.opacity(0.12), .clear], center: .topTrailing, startRadius: 0, endRadius: 420)
        }
        .ignoresSafeArea()
    }
}

struct GlassCard: ViewModifier {
    var padding: CGFloat = 14

    func body(content: Content) -> some View {
        content
            .padding(padding)
            .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(Color.white.opacity(0.045)))
            .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(Color.white.opacity(0.10), lineWidth: 0.5))
    }
}

extension View {
    func glassCard(padding: CGFloat = 14) -> some View {
        modifier(GlassCard(padding: padding))
    }
}
