// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "MeetsumLocalLLM",
    platforms: [
        // MLX Swift 需要 iOS 17 / macOS 14
        .iOS(.v17),
        .macOS(.v14)
    ],
    products: [
        .library(
            name: "MeetsumLocalLLM",
            targets: ["MeetsumLocalLLM"]
        )
    ],
    dependencies: [
        .package(url: "https://github.com/ionic-team/capacitor-swift-pm", from: "8.0.0"),

        // Bonsai 27B 1-bit 需要 PrismML 的 mlx-swift fork（含 1-bit / ternary kernels）。
        // 若只想跑一般 4-bit 模型，可換成官方：
        //   .package(url: "https://github.com/ml-explore/mlx-swift-examples", from: "2.0.0")
        // 並把下面 product 的 package 名稱改成 "mlx-swift-examples"。
        .package(url: "https://github.com/PrismML-Eng/mlx-swift-examples", branch: "main"),
    ],
    targets: [
        .target(
            name: "MeetsumLocalLLM",
            dependencies: [
                .product(name: "Capacitor", package: "capacitor-swift-pm"),
                .product(name: "Cordova", package: "capacitor-swift-pm"),
                .product(name: "MLXLLM", package: "mlx-swift-examples"),
                .product(name: "MLXLMCommon", package: "mlx-swift-examples"),
            ],
            path: "ios/Plugin"
        )
    ],
    swiftLanguageVersions: [.v5]
)
