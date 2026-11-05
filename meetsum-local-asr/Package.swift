// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "MeetsumLocalASR",
    platforms: [
        .iOS(.v16)
    ],
    products: [
        .library(
            name: "MeetsumLocalASR",
            targets: ["MeetsumLocalASR"]
        ),
    ],
    dependencies: [
        .package(url: "https://github.com/argmaxinc/argmax-oss-swift", from: "0.1.0"),
        .package(url: "https://github.com/ionic-team/capacitor-swift-pm", from: "8.0.0"),
    ],
    targets: [
        .target(
            name: "MeetsumLocalASR",
            dependencies: [
                .product(name: "WhisperKit", package: "argmax-oss-swift"),
                .product(name: "SpeakerKit", package: "argmax-oss-swift"),
                .product(name: "Capacitor", package: "capacitor-swift-pm"),
                .product(name: "Cordova", package: "capacitor-swift-pm"),
            ],
            path: "ios/Plugin",
            resources: [
                .process("Resources")
            ],
            publicHeadersPath: "include"
        ),
    ],
    swiftLanguageVersions: [.v5]
)