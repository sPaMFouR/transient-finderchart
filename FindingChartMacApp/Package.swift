// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "FindingChartMacApp",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "FindingChartMacApp", targets: ["FindingChartMacApp"])
    ],
    targets: [
        .executableTarget(
            name: "FindingChartMacApp",
            path: "Sources/FindingChartMacApp"
        )
    ]
)
