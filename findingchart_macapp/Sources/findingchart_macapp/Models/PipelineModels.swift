import Foundation

struct PipelineParams: Codable, Equatable {
    var action: String = "render"
    var queryName: String = "2023ixf"
    var resolveTNS: Bool = true
    var targetName: String = "SN 2023ixf"
    var raText: String = ""
    var decText: String = ""

    var survey: String = "Pan-STARRS"
    var mode: String = "Single band"
    var band: String = "r"
    var sizeArcmin: Double = 3.0
    var pixelScaleArcsec: Double = 0.262

    var psfBrightness: Double = 5.0
    var psfFwhmArcsec: Double = 1.0
    var showInjectedSource: Bool = true
    var showCrosshair: Bool = true
    var showSlit: Bool = false
    var showCompass: Bool = true

    var slitWidthArcsec: Double = 2.0
    var slitLengthArcsec: Double = 20.0
    var slitPaDeg: Double = 0.0
    var useParallacticPA: Bool = false
    var observationTimeISO: String = ISO8601DateFormatter().string(from: Date())
    var observatoryName: String = "La Palma"

    var queryCatalog: Bool = false
    var catalogName: String = "Gaia DR3"
    var catalogMaxMagnitude: Double? = nil
    var selectedCatalogSourceID: String = ""
    var imageCachePath: String = ""
    var catalogCachePath: String = ""

    var autoContrast: Bool = true
    var vmin: Double? = nil
    var vmax: Double? = nil
    var contrastStretch: String = "arcsinh"
}

struct PipelineResult: Codable {
    var ok: Bool
    var error: String?
    var action: String?
    var target: TargetPayload?
    var imagePath: String?
    var survey: String?
    var band: String?
    var mode: String?
    var sourceURL: String?
    var pixelScaleArcsec: Double?
    var catalogCount: Int?
    var slitPaDeg: Double?
    var message: String?
    var imageCachePath: String?
    var imageWidth: Int?
    var imageHeight: Int?
    var catalogCachePath: String?
    var catalogSources: [CatalogSourcePayload]?
    var selectedCatalogDetail: String?
    var surveys: [String]?
    var bands: [String: [String: [String]]]?
    var observatories: [String]?
}

struct TargetPayload: Codable {
    var name: String
    var raDeg: Double
    var decDeg: Double
    var raText: String
    var decText: String
    var transientType: String
    var redshift: String
    var hostName: String
}

struct CatalogSourcePayload: Codable, Identifiable, Hashable {
    var id: String
    var label: String
    var catalog: String
    var raDeg: Double
    var decDeg: Double
    var magnitude: Double?
    var magnitudeBand: String
    var sourceID: String
    var detail: String
    var markerX: Double?
    var markerY: Double?
}

enum Fmt {
    static func fixed(_ value: Double, _ digits: Int) -> String {
        String(format: "%.\(digits)f", value)
    }
}
