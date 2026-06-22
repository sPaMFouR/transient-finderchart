import SwiftUI

struct ControlSidebar: View {
    @ObservedObject var vm: PipelineViewModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                targetSection
                archiveImageSection
                injectedSourceSection
                contrastSection
                slitSection
                catalogSection
                saveSection
            }
            .padding(16)
        }
        .frame(width: 320)
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
        .onChange(of: vm.params.targetName) { _, _ in vm.scheduleLiveRender() }
    }

    private var archiveImageSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(systemName: "photo", title: "Archive Image")
            Picker("Survey", selection: $vm.params.survey) {
                ForEach(vm.surveys, id: \.self) { Text($0).tag($0) }
            }
            .onChange(of: vm.params.survey) { _, _ in vm.reconcileBand() }
            Picker("Filter", selection: filterChoice) {
                ForEach(vm.filterChoices, id: \.self) { Text($0).tag($0) }
            }
            Grid(alignment: .leading, horizontalSpacing: 8, verticalSpacing: 8) {
                NumericField(title: "Field", unit: "arcmin", value: $vm.params.sizeArcmin, digits: 2)
                NumericField(title: "Pixel scale", unit: "\"/pix", value: $vm.params.pixelScaleArcsec, digits: 3)
            }
            ActionButton(title: "Load Image", systemName: "square.and.arrow.down", disabled: vm.isRunning, action: vm.loadImage)
        }
        .glassCard()
    }

    private var injectedSourceSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(systemName: "sparkle.magnifyingglass", title: "Injected SN")
            LabeledToggle(title: "Injected SN", value: $vm.params.showInjectedSource)
            Grid(alignment: .leading, horizontalSpacing: 8, verticalSpacing: 8) {
                NumericField(title: "Brightness", unit: "mag", value: $vm.params.psfMagnitude, digits: 1)
                NumericField(title: "FWHM", unit: "\"", value: $vm.params.psfFwhmArcsec, digits: 2)
                NumericSlider(title: "Inset zoom", unit: "x", value: $vm.params.insetZoomFactor, range: 3.0...12.0, step: 1.0, digits: 0)
            }
            Picker("PSF model", selection: $vm.params.psfModel) {
                Text("moffat").tag("moffat")
                Text("empirical core").tag("empirical core")
                Text("empirical hybrid").tag("empirical hybrid")
            }
        }
        .glassCard()
        .onChange(of: vm.params.psfMagnitude) { _, _ in vm.scheduleLiveRender() }
        .onChange(of: vm.params.psfModel) { _, _ in vm.scheduleLiveRender() }
        .onChange(of: vm.params.psfFwhmArcsec) { _, _ in vm.scheduleLiveRender() }
        .onChange(of: vm.params.insetZoomFactor) { _, _ in vm.scheduleLiveRender() }
        .onChange(of: vm.params.showInjectedSource) { _, _ in vm.scheduleLiveRender() }
    }

    private var contrastSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(systemName: "camera.filters", title: "Contrast")
            Toggle("Auto contrast", isOn: $vm.params.autoContrast)
                .toggleStyle(.checkbox)
            Picker("Colormap", selection: $vm.params.colormap) {
                Text("gray_r").tag("gray_r")
                Text("inferno").tag("inferno")
                Text("icefire").tag("icefire")
                Text("twilight").tag("twilight")
                Text("jet").tag("jet")
                Text("turbo").tag("turbo")
                Text("Hiroshige").tag("Hiroshige")
                Text("viridis").tag("viridis")
                Text("RdBu").tag("RdBu")
            }
            Picker("Label color", selection: $vm.params.annotationColor) {
                Text("xkcd:bright red").tag("xkcd:bright red")
                Text("xkcd:dodger blue").tag("xkcd:dodger blue")
                Text("xkcd:black").tag("xkcd:black")
                Text("xkcd:white").tag("xkcd:white")
                Text("xkcd:turquoise").tag("xkcd:turquoise")
                Text("xkcd:bright yellow").tag("xkcd:bright yellow")
            }
            Picker("Stretch", selection: $vm.params.contrastStretch) {
                Text("arcsinh").tag("arcsinh")
                Text("linear").tag("linear")
                Text("sqrt").tag("sqrt")
                Text("log").tag("log")
            }
            Grid(alignment: .leading, horizontalSpacing: 8, verticalSpacing: 8) {
                NumericSlider(title: "Contrast", unit: "%", value: $vm.params.contrastPercentile, range: 95.0...99.9, step: 0.1, digits: 1)
            }
            HStack {
                TextField("vmin", value: $vm.params.vmin, format: .number.precision(.fractionLength(0...4)))
                    .textFieldStyle(.roundedBorder)
                    .disabled(vm.params.autoContrast)
                TextField("vmax", value: $vm.params.vmax, format: .number.precision(.fractionLength(0...4)))
                    .textFieldStyle(.roundedBorder)
                    .disabled(vm.params.autoContrast)
            }
            LabeledToggle(title: "Crosshair", value: $vm.params.showCrosshair)
            LabeledToggle(title: "Compass", value: $vm.params.showCompass)
        }
        .glassCard()
        .onChange(of: vm.params.showCrosshair) { _, _ in vm.scheduleLiveRender() }
        .onChange(of: vm.params.showCompass) { _, _ in vm.scheduleLiveRender() }
        .onChange(of: vm.params.autoContrast) { _, _ in vm.scheduleLiveRender() }
        .onChange(of: vm.params.contrastStretch) { _, _ in vm.scheduleLiveRender() }
        .onChange(of: vm.params.colormap) { _, _ in vm.scheduleLiveRender() }
        .onChange(of: vm.params.annotationColor) { _, _ in vm.scheduleLiveRender() }
        .onChange(of: vm.params.contrastPercentile) { _, _ in vm.scheduleLiveRender() }
        .onChange(of: vm.params.vmin) { _, _ in vm.scheduleLiveRender() }
        .onChange(of: vm.params.vmax) { _, _ in vm.scheduleLiveRender() }
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
                NumericField(title: "Width", unit: "\"", value: $vm.params.slitWidthArcsec, digits: 1)
                NumericField(title: "Length", unit: "\"", value: $vm.params.slitLengthArcsec, digits: 0)
                NumericField(title: "PA", unit: "deg", value: $vm.params.slitPaDeg, digits: 1)
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
            Grid(alignment: .leading, horizontalSpacing: 8, verticalSpacing: 8) {
                GridRow {
                    Text("Mag Cut-Off")
                        .font(AppFont.body(11))
                        .foregroundStyle(Palette.textSecondary)
                    TextField("", value: $vm.params.catalogMaxMagnitude, format: .number.precision(.fractionLength(0...2)))
                        .textFieldStyle(.roundedBorder)
                }
                GridRow {
                    Text("Distance")
                        .font(AppFont.body(11))
                        .foregroundStyle(Palette.textSecondary)
                    TextField("arcsec", value: $vm.params.catalogMaxDistanceArcsec, format: .number.precision(.fractionLength(0...1)))
                        .textFieldStyle(.roundedBorder)
                }
            }
            HStack(spacing: 8) {
                ActionButton(title: "Load Catalog", systemName: "star.circle", disabled: vm.isRunning || !vm.hasLoadedImage, action: vm.queryCatalog)
                Button {
                    vm.clearCatalog()
                } label: {
                    Label("Clear", systemImage: "xmark.circle")
                        .font(AppFont.body(12).weight(.semibold))
                        .padding(.horizontal, 10)
                        .frame(height: 34)
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
                Button {
                    vm.clearCatalogSelection()
                } label: {
                    Label("Clear Selection", systemImage: "xmark.circle")
                        .font(AppFont.body(12).weight(.semibold))
                        .padding(.horizontal, 10)
                        .frame(height: 30)
                }
                .buttonStyle(.plain)
                .foregroundStyle(Palette.textSecondary)
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
                        VStack(alignment: .trailing, spacing: 2) {
                            if let mag = source.magnitude {
                                Text("\(Fmt.fixed(mag, 2)) \(source.magnitudeBand)")
                                    .font(AppFont.mono(10))
                                    .foregroundStyle(Palette.cyan)
                            }
                            if let separation = source.separationArcsec {
                                Text("\(Fmt.fixed(separation, 2))\"")
                                    .font(AppFont.mono(10))
                                    .foregroundStyle(Palette.cyan)
                            }
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

    private var filterChoice: Binding<String> {
        Binding(
            get: { vm.selectedFilterChoice },
            set: { vm.setFilterChoice($0) }
        )
    }
}
