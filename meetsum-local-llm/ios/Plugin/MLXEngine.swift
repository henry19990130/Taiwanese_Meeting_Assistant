import Foundation
import MLXLLM
import MLXLMCommon

/// 以 MLX 在裝置上執行 LLM（Bonsai 1-bit）。
///
/// 注意：
/// - 1-bit / ternary 模型需要 PrismML 的 mlx-swift fork；官方版只能跑 4-bit。
/// - 一次只載入一個模型；ASR 與 LLM 不應同時駐留（記憶體）。
actor MLXEngine {

    private var container: ModelContainer?
    private var loadedId: String?
    private var currentTask: Task<Void, Never>?

    var loadedModelId: String? { loadedId }

    func load(modelId: String, directory: URL) async throws {
        if loadedId == modelId, container != nil { return }
        await unload()

        var config = ModelConfiguration(directory: directory)

        let loaded = try await LLMModelFactory.shared.loadContainer(configuration: config) { _ in
            // 載入進度（權重讀取）目前不需要回報到 UI
        }
        self.container = loaded
        self.loadedId = modelId
    }

    func unload() async {
        currentTask?.cancel()
        currentTask = nil
        container = nil
        loadedId = nil
    }

    func cancel() {
        currentTask?.cancel()
        currentTask = nil
    }

    /// 產生摘要；每收到一段文字就呼叫 onToken。
    func summarize(
        modelId: String,
        directory: URL,
        systemPrompt: String,
        userPrompt: String,
        maxTokens: Int,
        onToken: @escaping @Sendable (String) -> Void
    ) async throws -> String {
        try await load(modelId: modelId, directory: directory)
        guard let container else {
            throw NSError(domain: "MeetsumLocalLLM", code: 3101,
                          userInfo: [NSLocalizedDescriptionKey: "模型尚未載入"])
        }

        var params = GenerateParameters()
        params.maxTokens = maxTokens
        params.temperature = 0.2
        params.topP = 0.9

        let session = ChatSession(
            container,
            instructions: systemPrompt,
            generateParameters: params
        )

        var output = ""
        let stream = session.streamResponse(to: userPrompt)
        for try await chunk in stream {
            if Task.isCancelled { break }
            output += chunk
            onToken(chunk)
        }
        return output
    }
}

/// 把模型輸出中的 JSON 抽出來；失敗回傳 nil（前端會退回顯示純文字）。
enum SummaryJSONParser {
    static func parse(_ text: String) -> [String: Any]? {
        guard let start = text.firstIndex(of: "{"),
              let end = text.lastIndex(of: "}") else { return nil }
        let json = String(text[start...end])
        guard let data = json.data(using: .utf8) else { return nil }
        return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
    }
}
