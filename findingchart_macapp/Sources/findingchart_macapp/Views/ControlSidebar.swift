import SwiftUI

struct ControlSidebar: View {
    @ObservedObject var vm: PipelineViewModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                targetSection
                archiveImageSection
                overlaySection
                slitSection
                catalogSection
                saveSection
            }
            .padding(16)
        }
        .frame(width: 380)
    }

    private var targetSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(systemName: "scope", title: "Target")
            Toggle("Resolve TNS name", isOn: $vm.params.resolveTNS)
                .toggleStyle(.switch)
            TextField("IAU/ZTF name", text: $vm.params.queryName)
                .textFieldStyle(.roundedBorder)
            TextField("Chart label", text: $vm.params.targetName)
                .textFieldStyle(.roundedBorder)
            HStack {
                TextField("RA", text: $vm.params.raText)
                    .textFieldStyle(.roundedBorder)
                TextField("Dec", text: $vm.params.decText)
                    .textFieldStyle(.roundedBorder)
            }
            .disabled(vm.params.resolveTNS)
            ActionButton(title: "Load Target", systemName: "scope", disabled: vm.isRunning, action: vm.loadTarget)
        }
        .glassCard()
    }

    private var archiveImageSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(systemName: "photo", title: "Archive Image")
            Picker("Survey", selection: $vm.params.survey) {
                ForEach(vm.surveys, id: \.self) { Text($0).tag($0) }
            }
            .onChange(of: vm.params.survey) { _, _ in vm.reconcileBand() }
            Picker("Mode", selection: $vm.params.mode) {
                ForEach(vm.modes, id: \.self) { Text($0).tag($0) }
            }
            .onChange(of: vm.params.mode) { _, _ in vm.reconcileBand() }
            Picker("Band", selection: $vm.params.band) {
                ForEach(vm.bands, id: \.self) { Text($0).tag($0) }
            }
            Grid(alignment: .leading, horizontalSpacing: 8, verticalSpacing: 8) {
                NumericSlider(title: "Field", unit: "arcmin", value: $vm.params.sizeArcmin, range: 0.2...20.0, step: 0.1, digits: 1)
                NumericSlider(title: "Pixel", unit: "\"/pix", value: $vm.params.pixelScaleArcsec, range: 0.05...2.0, step: 0.01, digits: 2)
            }
            ActionButton(title: "Load Image", systemName: "square.and.arrow.down", disabled: vm.isRunning, action: vm.loadImage)
        }
        .glassCard()
    }

    private var overlaySection: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(systemName: "slider.horizontal.3", title: "Overlays")
            Grid(alignment: .leading, horizontalSpacing: 8, verticalSpacing: 8) {
                NumericSlider(title: "SN flux", unit: "", value: $vm.params.psfBrightness, range: 0.0...10.0, step: 0.1, digits: 1)
                NumericSlider(title: "FWHM", unit: "\"", value: $vm.params.psfFwhmArcsec, range: 0.2...5.0, step: 0.1, digits: 1)
            }
            LabeledToggle(title: "Injected SN", value: $vm.params.showInjectedSource)
            LabeledToggle(title: "Crosshair", value: $vm.params.showCrosshair)
            LabeledToggle(title: "Compass", value: $vm.params.showCompass)
            Toggle("Auto contrast", isOn: $vm.params.autoContrast)
                .toggleStyle(.checkbox)
        }
        .glassCard()
        .onChange(of: vm.params.psfBrightness) { _, _ in vm.scheduleLiveRender() }
        .onChange(of: vm.params.psfFwhmArcsec) { _, _ in vm.scheduleLiveRender() }
        .onChange(of: vm.params.showInjectedSource) { _, _ in vm.scheduleLiveRender() }
        .onChange(of: vm.params.showCrosshair) { _, _ in vm.scheduleLiveRender() }
        .onChange(of: vm.params.showCompass) { _, _ in vm.scheduleLiveRender() }
        .onChange(of: vm.params.autoContrast) { _, _ in vm.scheduleLiveRender() }
    }

    private var slitSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(systemName: "rectangle.dashed", title: "Slit")
            LabeledToggle(title: "Show slit", value: $vm.params.showSlit)
            LabeledToggle(title: "Use parallactic PA", value: $vm.params.useParallacticPA)
            Picker("Observatory", selection: $vm.params.observatoryName) {
                ForEach(vm.observatories, id: \.self) { Text($0).tag($0) }
            }
            DatePicker("Observation", selection: observationDate, displayedComponents: [.date, .hourAndMinute])
                .font(AppFont.body(12))
                .foregroundStyle(Palette.textSecondary)
            Grid(alignment: .leading, horizontalSpacing: 8, verticalSpacing: 8) {
                NumericSlider(title: "Width", unit: "\"", value: $vm.params.slitWidthArcsec, range: 0.2...10.0, step: 0.1, digits: 1)
                NumericSlider(title: "Length", unit: "\"", value: $vm.params.slitLengthArcsec, range: 2.0...120.0, step: 1.0, digits: 0)
                NumericSlider(title: "PA", unit: "deg", value: $vm.params.slitPaDeg, range: 0.0...360.0, step: 1.0, digits: 0)
            }
        }
        .glassCard()
        .onChange(of: vm.params.showSlit) { _, _ in vm.scheduleLiveRender() }
        .onChange(of: vm.params.useParallacticPA) { _, _ in vm.scheduleLiveRender() }
        .onChange(of: vm.params.observatoryName) { _, _ in vm.scheduleLiveRender() }
        .onChange(of: vm.params.observationTimeISO) { _, _ in vm.scheduleLiveRender() }
        .onChange(of: vm.params.slitWidthArcsec) { _, _ in vm.scheduleLiveRender() }
        .onChange(of: vm.params.slitLengthArcsec) { _, _ in vm.scheduleLiveRender() }
        .onChange(of: vm.params.slitPaDeg) { _, _ in vm.scheduleLiveRender() }
    }

    private var catalogSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(systemName: "star.circle", title: "Catalog")
            Picker("Catalog", selection: $vm.params.catalogName) {
                Text("Gaia DR3").tag("Gaia DR3")
                Text("Pan-STARRS DR2").tag("Pan-STARRS DR2")
                Text("Gaia + Pan-STARRS").tag("Gaia DR3 + Pan-STARRS DR2")
            }
            TextField("Max magnitude", value: $vm.params.catalogMaxMagnitude, format: .number)
                .textFieldStyle(.roundedBorder)
            HStack(spacing: 8) {
                ActionButton(title: "Load Catalog", systemName: "star.circle", disabled: vm.isRunning || !vm.hasLoadedImage, action: vm.queryCatalog)
                Button {
                    vm.clearCatalog()
                } label: {
                    Image(systemName: "xmark.circle")
                        .frame(width: 34, height: 34)
                }
                .buttonStyle(.plain)
                .foregroundStyle(Palette.textSecondary)
                .help("Clear catalog overlay")
                .disabled(vm.isRunning || vm.catalogSources.isEmpty)
            }
            ScrollView {
                catalogList
            }
            .frame(maxHeight: 204)
            .background(Color.black.opacity(0.12))
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            if !vm.selectedCatalogDetail.isEmpty {
                Text(vm.selectedCatalogDetail)
                    .font(AppFont.mono(11))
                    .foregroundStyle(Palette.textSecondary)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(10)
                    .background(Color.black.opacity(0.18))
                    .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            }
        }
        .glassCard()
    }

    private var catalogList: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(vm.catalogSources) { source in
                Button {
                    vm.selectCatalogSource(source)
                } label: {
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(source.label)
                                .font(AppFont.body(11))
                                .foregroundStyle(Palette.textPrimary)
                                .lineLimit(1)
                            Text(source.catalog)
                                .font(AppFont.body(10))
                                .foregroundStyle(Palette.textTertiary)
                        }
                        Spacer()
                        if let mag = source.magnitude {
                            Text("\(Fmt.fixed(mag, 2)) \(source.magnitudeBand)")
                                .font(AppFont.mono(10))
                                .foregroundStyle(Palette.cyan)
                        }
                    }
                    .padding(8)
                    .background(vm.params.selectedCatalogSourceID == source.id ? Palette.violet.opacity(0.18) : Color.white.opacity(0.035))
                    .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                }
                .buttonStyle(.plain)
            }
        }
    }

    private var saveSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(systemName: "square.and.arrow.down", title: "Save")
            ActionButton(title: "Save PDF (2000 dpi)", systemName: "doc.richtext", disabled: vm.isRunning || !vm.hasLoadedImage, action: vm.exportPDF)
            ActionButton(title: "Save JPG (300 dpi)", systemName: "photo", disabled: vm.isRunning || !vm.hasLoadedImage, action: vm.exportJPG)
        }
        .glassCard()
    }

    private var observationDate: Binding<Date> {
        Binding(
            get: {
                ISO8601DateFormatter().date(from: vm.params.observationTimeISO) ?? Date()
            },
            set: { date in
                vm.params.observationTimeISO = ISO8601DateFormatter().string(from: date)
            }
        )
    }
}
