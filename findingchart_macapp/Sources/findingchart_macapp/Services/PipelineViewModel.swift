import Foundation

@MainActor
final class PipelineViewModel: ObservableObject {
    @Published var params = PipelineParams()
    @Published var result: PipelineResult?
    @Published var metadata: PipelineResult?
    @Published var catalogSources: [CatalogSourcePayload] = []
    @Published var selectedCatalogDetail = ""
    @Published var isRunning = false
    @Published var progress = 0.0
    @Published var status = "Ready."
    @Published var errorText: String?

    private let bridge = PythonBridge()
    private var progressTask: Task<Void, Never>?
    private var liveRenderTask: Task<Void, Never>?

    var hasLoadedImage: Bool {
        !params.imageCachePath.isEmpty
    }

    var surveys: [String] {
        metadata?.surveys ?? ["Pan-STARRS", "Legacy Survey", "DSS2", "2MASS"]
    }

    var bands: [String] {
        metadata?.bands?[params.survey]?[params.mode] ?? ["g", "r", "i", "z", "y"]
    }

    var filterChoices: [String] {
        var choices: [String] = []
        if let colorBands = metadata?.bands?[params.survey]?["Color composite"], !colorBands.isEmpty {
            choices.append("Color composite")
        }
        choices += metadata?.bands?[params.survey]?["Single band"] ?? ["g", "r", "i", "z", "y"]
        return choices
    }

    var selectedFilterChoice: String {
        if params.mode == "Color composite" {
            return "Color composite"
        }
        return params.band
    }

    var observatories: [String] {
        metadata?.observatories ?? ["La Palma"]
    }

    func loadMetadata() {
        Task {
            do {
                var request = PipelineParams()
                request.action = "metadata"
                metadata = try await bridge.run(request)
                reconcileBand()
            } catch {
                errorText = readable(error)
                status = "Metadata unavailable."
            }
        }
    }

    func loadTarget() {
        runBridge(action: "loadTarget", statusText: "Loading target...") { output in
            self.applyTarget(output.target)
            self.status = output.message ?? "Target loaded."
        }
    }

    func loadImage() {
        params.catalogCachePath = ""
        params.selectedCatalogSourceID = ""
        catalogSources = []
        selectedCatalogDetail = ""
        runBridge(action: "loadImage", statusText: "Loading archive image...") { output in
            self.applyTarget(output.target)
            if let cache = output.imageCachePath {
                self.params.imageCachePath = cache
            }
            if let vmin = output.defaultVmin {
                self.params.vmin = vmin
            }
            if let vmax = output.defaultVmax {
                self.params.vmax = vmax
            }
            self.result = output
            self.status = output.message ?? "Archive image loaded."
            self.scheduleLiveRender()
        }
    }

    func queryCatalog() {
        guard hasLoadedImage else {
            errorText = "Load an archive image before querying catalogs."
            status = "Catalog query skipped."
            return
        }
        runBridge(action: "queryCatalog", statusText: "Querying catalog...") { output in
            if let cache = output.catalogCachePath {
                self.params.catalogCachePath = cache
            }
            self.catalogSources = output.catalogSources ?? []
            self.params.queryCatalog = true
            self.result = self.merge(output, into: self.result)
            self.status = output.message ?? "Catalog loaded."
            self.scheduleLiveRender()
        }
    }

    func scheduleLiveRender() {
        guard hasLoadedImage else { return }
        liveRenderTask?.cancel()
        liveRenderTask = Task {
            try? await Task.sleep(nanoseconds: 350_000_000)
            if Task.isCancelled { return }
            await MainActor.run {
                self.renderLive()
            }
        }
    }

    func renderLive() {
        guard hasLoadedImage, !isRunning else { return }
        runBridge(action: "render", statusText: "Rendering chart...") { output in
            self.result = output
            self.catalogSources = output.catalogSources ?? self.catalogSources
            self.selectedCatalogDetail = output.selectedCatalogDetail ?? self.selectedCatalogDetail
            self.status = output.message ?? "Chart rendered."
        }
    }

    func selectCatalogSource(_ source: CatalogSourcePayload) {
        if params.selectedCatalogSourceID == source.id {
            params.selectedCatalogSourceID = ""
            selectedCatalogDetail = ""
        } else {
            params.selectedCatalogSourceID = source.id
            selectedCatalogDetail = source.detail
        }
        scheduleLiveRender()
    }

    func clearCatalog() {
        params.catalogCachePath = ""
        params.selectedCatalogSourceID = ""
        params.queryCatalog = false
        catalogSources = []
        selectedCatalogDetail = ""
        scheduleLiveRender()
    }

    func exportPDF() {
        export(action: "exportPDF", statusText: "Saving PDF...")
    }

    func exportJPG() {
        export(action: "exportJPG", statusText: "Saving JPG...")
    }

    func reconcileBand() {
        setFilterChoice(preferredFilterChoice(for: params.survey), resetImage: false)
        params.imageCachePath = ""
        params.catalogCachePath = ""
        params.selectedCatalogSourceID = ""
    }

    func setFilterChoice(_ choice: String, resetImage: Bool = true) {
        if choice == "Color composite", let band = metadata?.bands?[params.survey]?["Color composite"]?.first {
            params.mode = "Color composite"
            params.band = band
        } else {
            let singles = metadata?.bands?[params.survey]?["Single band"] ?? filterChoices.filter { $0 != "Color composite" }
            params.mode = "Single band"
            params.band = singles.contains(choice) ? choice : (singles.first ?? choice)
        }
        if resetImage {
            params.imageCachePath = ""
            params.catalogCachePath = ""
            params.selectedCatalogSourceID = ""
        }
    }

    private func preferredFilterChoice(for survey: String) -> String {
        let preferred = [
            "Pan-STARRS": "r",
            "Legacy Survey": "r",
            "DSS2": "red",
            "2MASS": "J",
        ][survey] ?? ""
        let choices = filterChoices
        if choices.contains(preferred) {
            return preferred
        }
        return choices.first ?? params.band
    }

    private func export(action: String, statusText: String) {
        guard hasLoadedImage else {
            errorText = "Load an archive image before saving."
            status = "Save skipped."
            return
        }
        runBridge(action: action, statusText: statusText) { output in
            self.status = output.message ?? "Saved chart."
        }
    }

    private func runBridge(action: String, statusText: String, apply: @escaping (PipelineResult) -> Void) {
        guard !isRunning else { return }
        isRunning = true
        errorText = nil
        progress = 0.0
        status = statusText
        startFakeProgress()

        var request = params
        request.action = action
        Task {
            do {
                let output = try await bridge.run(request)
                finishProgress()
                apply(output)
            } catch {
                stopProgress()
                progress = 0.0
                errorText = readable(error)
                status = "\(statusText.replacingOccurrences(of: "...", with: "")) failed."
            }
            isRunning = false
        }
    }

    private func applyTarget(_ target: TargetPayload?) {
        guard let target else { return }
        params.targetName = target.name
        params.raText = target.raText
        params.decText = target.decText
    }

    private func merge(_ output: PipelineResult, into existing: PipelineResult?) -> PipelineResult {
        PipelineResult(
            ok: output.ok,
            error: output.error,
            action: output.action,
            target: output.target ?? existing?.target,
            imagePath: existing?.imagePath,
            survey: existing?.survey,
            band: existing?.band,
            mode: existing?.mode,
            sourceURL: existing?.sourceURL,
            pixelScaleArcsec: existing?.pixelScaleArcsec,
            catalogCount: output.catalogCount,
            slitPaDeg: existing?.slitPaDeg,
            message: output.message,
            imageCachePath: output.imageCachePath ?? existing?.imageCachePath,
            defaultVmin: output.defaultVmin ?? existing?.defaultVmin,
            defaultVmax: output.defaultVmax ?? existing?.defaultVmax,
            imageWidth: output.imageWidth ?? existing?.imageWidth,
            imageHeight: output.imageHeight ?? existing?.imageHeight,
            catalogCachePath: output.catalogCachePath,
            catalogSources: output.catalogSources,
            selectedCatalogDetail: output.selectedCatalogDetail,
            surveys: existing?.surveys,
            bands: existing?.bands,
            observatories: existing?.observatories
        )
    }

    private func readable(_ error: Error) -> String {
        (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
    }

    private func startFakeProgress() {
        progressTask?.cancel()
        progressTask = Task {
            while !Task.isCancelled && progress < 0.9 {
                try? await Task.sleep(nanoseconds: 220_000_000)
                if Task.isCancelled { break }
                await MainActor.run {
                    self.progress = min(0.9, self.progress + 0.055)
                }
            }
        }
    }

    private func finishProgress() {
        progressTask?.cancel()
        progress = 1.0
    }

    private func stopProgress() {
        progressTask?.cancel()
    }
}
