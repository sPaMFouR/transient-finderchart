import SwiftUI

struct SectionHeader: View {
    let systemName: String
    let title: String

    var body: some View {
        HStack(spacing: 7) {
            Image(systemName: systemName)
                .foregroundStyle(Palette.cyan)
            Text(title.uppercased())
                .font(AppFont.body(11))
                .foregroundStyle(Palette.textSecondary)
        }
    }
}

struct NumericSlider: View {
    let title: String
    let unit: String
    @Binding var value: Double
    let range: ClosedRange<Double>
    let step: Double
    let digits: Int

    var body: some View {
        GridRow {
            Text(title)
                .font(AppFont.body(12))
                .foregroundStyle(Palette.textSecondary)
                .frame(width: 76, alignment: .leading)
            Slider(value: $value, in: range, step: step)
                .tint(Palette.violet)
            Text("\(Fmt.fixed(value, digits)) \(unit)")
                .font(AppFont.mono(11))
                .foregroundStyle(Palette.textPrimary)
                .frame(width: 74, alignment: .trailing)
                .monospacedDigit()
        }
    }
}

struct LabeledToggle: View {
    let title: String
    @Binding var value: Bool

    var body: some View {
        Toggle(title, isOn: $value)
            .toggleStyle(.checkbox)
            .font(AppFont.body(12))
            .foregroundStyle(Palette.textSecondary)
    }
}

struct ActionButton: View {
    let title: String
    let systemName: String
    let disabled: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Label(title, systemImage: systemName)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 9)
                .background(Palette.accentGradient)
                .foregroundStyle(Palette.base)
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        }
        .buttonStyle(.plain)
        .disabled(disabled)
        .opacity(disabled ? 0.55 : 1.0)
    }
}
