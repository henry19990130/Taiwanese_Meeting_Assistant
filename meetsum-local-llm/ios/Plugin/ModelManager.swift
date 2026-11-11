import Foundation

/// 模型下載與存放。
///
/// Bonsai 的 MLX 版本在 Hugging Face 上是一整個資料夾（config.json + safetensors + tokenizer），
/// 這裡用 Hugging Face API 列出檔案，逐一抓到：
///   Application Support/models/<modelId>/
///
/// 只下載推論需要的檔案，遇到中斷就重抓該檔（單檔內不支援續傳，但不會重抓已完成檔案）。
actor ModelManager {

    struct ModelSpec: Sendable {
        let id: String
        let name: String
        let repo: String
        let sizeMB: Int
        let requiredMemoryMB: Int
        /// 需要的檔案；nil = 全部（排除 README 等）
        let allowExtensions: Set<String>?
    }

    static let shared = ModelManager()

    static let specs: [ModelSpec] = [
        ModelSpec(
            id: "bonsai-27b-1bit",
            name: "Bonsai 27B 1-bit",
            repo: "prism-ml/Bonsai-27B-mlx-1bit",
            sizeMB: 3900,
            requiredMemoryMB: 5200,
            allowExtensions: nil
        ),
        ModelSpec(
            id: "bonsai-8b-1bit",
            name: "Bonsai 8B 1-bit",
            repo: "prism-ml/Bonsai-8B-mlx-1bit",
            sizeMB: 1150,
            requiredMemoryMB: 2400,
            allowExtensions: nil
        )
    ]

    private let fm = FileManager.default
    private var cancelled: Set<String> = []

    // MARK: - 路徑

    func modelsRoot() throws -> URL {
        let base = try fm.url(for: .applicationSupportDirectory, in: .userDomainMask,
                              appropriateFor: nil, create: true)
        let root = base.appendingPathComponent("models", isDirectory: true)
        try fm.createDirectory(at: root, withIntermediateDirectories: true)
        return root
    }

    func folder(for modelId: String) throws -> URL {
        try modelsRoot().appendingPathComponent(modelId, isDirectory: true)
    }

    func isDownloaded(_ modelId: String) -> Bool {
        guard let dir = try? folder(for: modelId) else { return false }
        let config = dir.appendingPathComponent("config.json")
        guard fm.fileExists(atPath: config.path) else { return false }
        // 至少要有权重文件
        let files = (try? fm.contentsOfDirectory(atPath: dir.path)) ?? []
        return files.contains { $0.hasSuffix(".safetensors") || $0.hasSuffix(".npz") }
    }

    func delete(_ modelId: String) throws {
        let dir = try folder(for: modelId)
        if fm.fileExists(atPath: dir.path) { try fm.removeItem(at: dir) }
    }

    // MARK: - 下載

    struct RemoteFile: Decodable {
        let rfilename: String
    }
    struct ModelInfoResponse: Decodable {
        let siblings: [RemoteFile]
    }

    func download(
        modelId: String,
        progress: @escaping @Sendable (Int64, Int64) -> Void
    ) async throws -> URL {
        guard let spec = Self.specs.first(where: { $0.id == modelId }) else {
            throw NSError(domain: "MeetsumLocalLLM", code: 3001,
                          userInfo: [NSLocalizedDescriptionKey: "未知模型 \(modelId)"])
        }
        cancelled.remove(modelId)

        let dir = try folder(for: modelId)
        try fm.createDirectory(at: dir, withIntermediateDirectories: true)

        // 1. 列出 repo 檔案
        let listURL = URL(string: "https://huggingface.co/api/models/\(spec.repo)")!
        var req = URLRequest(url: listURL)
        req.timeoutInterval = 30
        req.setValue("MeetSum/1.2 (iOS; on-device)", forHTTPHeaderField: "User-Agent")
        let (data, _) = try await URLSession.shared.data(for: req)
        let info = try JSONDecoder().decode(ModelInfoResponse.self, from: data)

        let skipNames: Set<String> = [".gitattributes", "README.md", "LICENSE", "LICENSE.txt"]
        let files = info.siblings.map(\.rfilename).filter { name in
            if skipNames.contains(name) { return false }
            if name.hasPrefix(".") { return false }
            return true
        }
        guard !files.isEmpty else {
            throw NSError(domain: "MeetsumLocalLLM", code: 3002,
                          userInfo: [NSLocalizedDescriptionKey: "模型 repo 沒有可下載的檔案"])
        }

        // 2. 先抓小檔取得總大小（Content-Length），再下載
        var sizes: [String: Int64] = [:]
        for name in files {
            if let size = try? await headSize(repo: spec.repo, path: name) { sizes[name] = size }
        }
        let total = sizes.values.reduce(Int64(0), +)
        var done: Int64 = 0
        progress(done, max(total, 1))

        // 3. 逐檔下載
        for name in files {
            if cancelled.contains(modelId) { throw CancellationError() }
            let dest = dir.appendingPathComponent(name)
            if fm.fileExists(atPath: dest.path) {
                done += sizes[name] ?? fileSize(dest)
                progress(done, max(total, done))
                continue
            }
            try await downloadFile(repo: spec.repo, path: name, to: dest)
            done += sizes[name] ?? fileSize(dest)
            progress(done, max(total, done))
        }

        return dir
    }

    func cancel(_ modelId: String) {
        cancelled.insert(modelId)
    }

    private func headSize(repo: String, path: String) async throws -> Int64? {
        var comps = URLComponents(string: "https://huggingface.co/\(repo)/resolve/main/\(path)")!
        comps.queryItems = [URLQueryItem(name: "download", value: "true")]
        var req = URLRequest(url: comps.url!)
        req.httpMethod = "HEAD"
        req.timeoutInterval = 20
        let (_, res) = try await URLSession.shared.data(for: req)
        guard let http = res as? HTTPURLResponse,
              let len = http.value(forHTTPHeaderField: "Content-Length"),
              let value = Int64(len) else { return nil }
        return value
    }

    private func downloadFile(repo: String, path: String, to dest: URL) async throws {
        var comps = URLComponents(string: "https://huggingface.co/\(repo)/resolve/main/\(path)")!
        comps.queryItems = [URLQueryItem(name: "download", value: "true")]
        var req = URLRequest(url: comps.url!)
        req.timeoutInterval = 600
        req.setValue("MeetSum/1.2 (iOS; on-device)", forHTTPHeaderField: "User-Agent")
        let (tmp, res) = try await URLSession.shared.download(for: req)
        guard let http = res as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw NSError(domain: "MeetsumLocalLLM", code: 3003,
                          userInfo: [NSLocalizedDescriptionKey: "下載失敗：\(path)（HTTP \((res as? HTTPURLResponse)?.statusCode ?? -1)）"])
        }
        try fm.createDirectory(at: dest.deletingLastPathComponent(), withIntermediateDirectories: true)
        if fm.fileExists(atPath: dest.path) { try fm.removeItem(at: dest) }
        try fm.moveItem(at: tmp, to: dest)
    }

    private func fileSize(_ url: URL) -> Int64 {
        guard let attrs = try? fm.attributesOfItem(atPath: url.path),
              let size = attrs[.size] as? NSNumber else { return 0 }
        return size.int64Value
    }
}
