// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "findingchart_macapp",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "findingchart_macapp", targets: ["findingchart_macapp"])
    ],
    targets: [
        .executableTarget(
            name: "findingchart_macapp",
            path: "Sources/findingchart_macapp"
        )
    ]
)
