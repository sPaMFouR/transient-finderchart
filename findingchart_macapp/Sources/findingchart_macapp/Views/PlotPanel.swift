import AppKit
import SwiftUI

struct PlotPanel: View {
    @ObservedObject var vm: PipelineViewModel

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider().overlay(Color.white.opacity(0.08))
            ZStack {
                Color.black.opacity(0.22)
                chartImage
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            diagnostics
        }
        .glassCard(padding: 0)
        .padding([.top, .trailing, .bottom], 16)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: 3) {
                Text(vm.result?.target?.name ?? "Finding Chart")
                    .font(AppFont.title(22))
                    .foregroundStyle(Palette.textPrimary)
                Text(subtitle)
                    .font(AppFont.body(12))
                    .foregroundStyle(Palette.textSecondary)
            }
            Spacer()
            if let count = vm.result?.catalogCount {
                Text("\(count) catalog sources")
                    .font(AppFont.mono(12))
                    .foregroundStyle(Palette.cyan)
            }
        }
        .padding(16)
    }

    @ViewBuilder
    private var chartImage: some View {
        if let path = vm.result?.imagePath, let image = NSImage(contentsOfFile: path) {
            Image(nsImage: image)
                .resizable()
                .scaledToFit()
                .padding(14)
        } else {
            VStack(spacing: 12) {
                Image(systemName: "photo.on.rectangle.angled")
                    .font(.system(size: 44))
                    .foregroundStyle(Palette.textTertiary)
                Text("Press Render Chart")
                    .font(AppFont.title(18))
                    .foregroundStyle(Palette.textSecondary)
            }
        }
    }

    private var diagnostics: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let error = vm.errorText {
                Text(error)
                    .font(AppFont.mono(11))
                    .foregroundStyle(Palette.pink)
                    .textSelection(.enabled)
            } else if let url = vm.result?.sourceURL, !url.isEmpty {
                Text(url)
                    .font(AppFont.mono(10))
                    .foregroundStyle(Palette.textTertiary)
                    .lineLimit(2)
                    .textSelection(.enabled)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(Color.white.opacity(0.035))
    }

    private var subtitle: String {
        let survey = vm.result?.survey ?? vm.params.survey
        let band = vm.result?.band ?? vm.params.band
        let scale = vm.result?.pixelScaleArcsec ?? vm.params.pixelScaleArcsec
        return "\(survey) \(band)  |  \(Fmt.fixed(scale, 3)) arcsec/pix"
    }
}
