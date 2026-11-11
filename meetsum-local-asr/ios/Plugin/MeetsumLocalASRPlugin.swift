//
//  MeetsumLocalASRPlugin.swift
//  MeetsumLocalASR
//
//  整合 WhisperKit 進行本地語音辨識與講者辨識
//

import Foundation
import Capacitor
import WhisperKit
import SpeakerKit
import AVFoundation
import ArgmaxCore

@objc(MeetsumLocalASRPlugin)
public class MeetsumLocalASRPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "MeetsumLocalASR"
    public let jsName = "MeetsumLocalASR"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "isModelAvailable", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "getAvailableModels", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "downloadModel", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "cancelDownload", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "deleteModel", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "transcribe", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "getTranscriptionStatus", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "cancelTranscription", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "clearCache", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "getDeviceCapabilities", returnType: CAPPluginReturnPromise),
    ]

    // WhisperKit 實例
    private var whisperKit: WhisperKit?
    private let whisperKitQueue = DispatchQueue(label: "com.meetsum.whisperkit", qos: .userInitiated)

    // SpeakerKit 實例 (用於講者辨識)
    private var speakerKit: SpeakerKit?
    private let speakerKitQueue = DispatchQueue(label: "com.meetsum.speakerkit", qos: .userInitiated)

    // 轉錄任務管理
    private var transcriptionJobs: [String: TranscriptionJob] = [:]
    private let jobsQueue = DispatchQueue(label: "com.meetsum.transcription.jobs", attributes: .concurrent)

    // 模型下載管理
    private var activeDownloads: [String: ModelDownloadTask] = [:]
    private let downloadsQueue = DispatchQueue(label: "com.meetsum.downloads", attributes: .concurrent)

    // 事件通知
    private let eventCenter = NotificationCenter.default

    // MARK: - 生命週期

    public override func load() {
        super.load()
        setupNotifications()
        print("[MeetsumLocalASR] 插件已載入")
    }

    private func setupNotifications() {
        // 監聽記憶體警告
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(handleMemoryWarning),
            name: UIApplication.didReceiveMemoryWarningNotification,
            object: nil
        )
    }

    @objc private func handleMemoryWarning() {
        print("[MeetsumLocalASR] 收到記憶體警告，卸載模型")
        unloadWhisperKit()
    }

    // MARK: - WhisperKit 管理

    func loadWhisperKit(modelSize: String, quantization: String) async throws -> WhisperKit {
        if let existing = whisperKit {
            return existing
        }

        let modelFolder = getModelFolder(modelSize: modelSize, quantization: quantization)
        let modelPath = modelFolder.path

        guard FileManager.default.fileExists(atPath: modelPath) else {
            throw NSError(
                domain: "MeetsumLocalASR",
                code: 1001,
                userInfo: [NSLocalizedDescriptionKey: "模型不存在: \(modelPath)"]
            )
        }

        print("[MeetsumLocalASR] 載入 WhisperKit 模型: \(modelSize) (\(quantization))")

        let config = WhisperKitConfig(
            modelFolder: modelFolder.path,
            verbose: true,
            logLevel: .info,
            prewarm: true,
            load: true,
            download: false
        )

        let kit = try await WhisperKit(config)
        self.whisperKit = kit
        return kit
    }

    private func unloadWhisperKit() {
        whisperKit = nil
        print("[MeetsumLocalASR] WhisperKit 已卸載")
    }

    // MARK: - SpeakerKit 管理

    func loadSpeakerKit() async throws -> SpeakerKit {
        if let existing = speakerKit {
            return existing
        }

        print("[MeetsumLocalASR] 載入 SpeakerKit")

        let config = PyannoteConfig()
        let kit = try await SpeakerKit(config)
        self.speakerKit = kit
        return kit
    }

    private func unloadSpeakerKit() {
        speakerKit = nil
        print("[MeetsumLocalASR] SpeakerKit 已卸載")
    }

    // MARK: - ASR Engine Protocol (支援多引擎熱插拔：WhisperKit、BreezeASR 等)

    /// 本地 ASR 引擎協定，定義所有 ASR 引擎需實作的介面
    protocol LocalASREngine: Sendable {
        /// 引擎唯一標識
        var engineId: String { get }
        /// 引擎顯示名稱
        var displayName: String { get }
        /// 支援的語言代碼
        var supportedLanguages: [String] { get }
        /// 是否支援講者辨識
        var supportsDiarization: Bool { get }
        /// 載入模型
        func load(modelSize: String, quantization: String) async throws
        /// 卸載模型
        func unload()
        /// 執行轉錄
        func transcribe(audioPath: String, language: String, enableDiarization: Bool) async throws -> EngineTranscriptionResult
        /// 取得引擎狀態
        var isLoaded: Bool { get }
    }

    /// 引擎轉錄結果統一格式
    struct EngineTranscriptionResult: Sendable {
        let segments: [EngineTranscriptionSegment]
        let language: String
        let duration: TimeInterval
    }

    /// 引擎轉錄片段統一格式
    struct EngineTranscriptionSegment: Sendable {
        let id: Int
        let start: Float
        let end: Float
        let text: String
        let speaker: String?
        let avgLogprob: Float?
        let noSpeechProb: Float?
        let compressionRatio: Float?
    }

    /// WhisperKit 引擎實作
    final class WhisperKitEngine: LocalASREngine {
        let engineId = "whisperkit"
        let displayName = "WhisperKit"
        let supportedLanguages = ["zh", "en", "ja", "ko", "auto"]
        let supportsDiarization = true

        private var whisperKit: WhisperKit?
        private let plugin: MeetsumLocalASRPlugin

        init(plugin: MeetsumLocalASRPlugin) {
            self.plugin = plugin
        }

        var isLoaded: Bool { whisperKit != nil }

        func load(modelSize: String, quantization: String) async throws {
            whisperKit = try await plugin.loadWhisperKit(modelSize: modelSize, quantization: quantization)
        }

        func unload() {
            whisperKit = nil
        }

        func transcribe(audioPath: String, language: String, enableDiarization: Bool) async throws -> EngineTranscriptionResult {
            guard let kit = whisperKit else {
                throw NSError(domain: "MeetsumLocalASR", code: 1003, userInfo: [NSLocalizedDescriptionKey: "WhisperKit 未載入"])
            }

            let results = try await kit.transcribe(audioPath: audioPath)
            guard let result = results.first else {
                throw NSError(domain: "MeetsumLocalASR", code: 1002, userInfo: [NSLocalizedDescriptionKey: "轉錄結果為空"])
            }

            var diarizationSegments: [SpeakerSegment] = []
            if enableDiarization {
                do {
                    let speakerKit = try await plugin.loadSpeakerKit()
                    let audioArray = try AudioProcessor.loadAudioAsFloatArray(fromPath: audioPath)
                    let options = PyannoteDiarizationOptions(
                        numberOfSpeakers: nil,
                        clusterDistanceThreshold: 0.6,
                        useExclusiveReconciliation: false
                    )
                    let diarizationResult = try await speakerKit.diarize(audioArray: audioArray, options: options)
                    diarizationSegments = diarizationResult.segments
                } catch {
                    print("[MeetsumLocalASR] 講者辨識失敗: \(error)")
                }
            }

            let segments = result.segments.enumerated().map { index, segment in
                var speaker = "SPEAKER_00"
                if !diarizationSegments.isEmpty {
                    speaker = matchSpeaker(segmentStart: segment.start, segmentEnd: segment.end, diarizationSegments: diarizationSegments)
                }

                return EngineTranscriptionSegment(
                    id: index,
                    start: segment.start,
                    end: segment.end,
                    text: segment.text,
                    speaker: speaker,
                    avgLogprob: segment.avgLogprob,
                    noSpeechProb: segment.noSpeechProb,
                    compressionRatio: segment.compressionRatio
                )
            }

            return EngineTranscriptionResult(
                segments: segments,
                language: result.language,
                duration: TimeInterval(segments.last?.end ?? 0)
            )
        }

        private func matchSpeaker(segmentStart: Float, segmentEnd: Float, diarizationSegments: [SpeakerSegment]) -> String {
            var bestOverlap: Float = 0
            var bestSpeaker = "SPEAKER_00"
            for dSegment in diarizationSegments {
                let dStart = dSegment.startTime
                let dEnd = dSegment.endTime
                let overlapStart = max(segmentStart, dStart)
                let overlapEnd = min(segmentEnd, dEnd)
                let overlap = max(0, overlapEnd - overlapStart)
                if overlap > bestOverlap {
                    bestOverlap = overlap
                    if let speakerId = dSegment.speaker.speakerId {
                        bestSpeaker = "SPEAKER_\(String(format: "%02d", speakerId))"
                    }
                }
            }
            return bestSpeaker
        }
    }

    /// BreezeASR 引擎實作
    ///
    /// Breeze-ASR-26 是 MediaTek 以 Whisper large-v3 為基礎、用約 1 萬小時台語語音微調的模型。
    /// 官方與社群釋出的是 whisper.cpp 格式（GGML + CoreML encoder）；WhisperKit 需要
    /// WhisperKit 的 CoreML 目錄結構，因此這裡讀取「已轉換好的 CoreML 模型資料夾」。
    ///
    /// 轉換方式見 tools/convert_breeze_whisperkit.sh（whisperkittools）。
    /// 模型 repo 可用環境變數 MEETSUM_BREEZE_REPO 覆寫；預設是專案自架的轉換版本。
    final class BreezeASREngine: LocalASREngine {
        let engineId = "breezeasr"
        let displayName = "Breeze-ASR-26 (MediaTek, ANE encoder)"
        let supportedLanguages = ["zh", "nan", "hak", "en"]
        let supportsDiarization = false

        private var whisperKit: WhisperKit?
        private let plugin: MeetsumLocalASRPlugin

        init(plugin: MeetsumLocalASRPlugin) {
            self.plugin = plugin
        }

        var isLoaded: Bool { whisperKit != nil }

        func load(modelSize: String, quantization: String) async throws {
            let folder = plugin.getModelFolder(modelSize: modelSize, quantization: quantization)
            guard FileManager.default.fileExists(atPath: folder.path) else {
                throw NSError(
                    domain: "MeetsumLocalASR",
                    code: 2001,
                    userInfo: [NSLocalizedDescriptionKey:
                        "找不到 Breeze CoreML 模型。請先下載模型，或執行 tools/convert_breeze_whisperkit.sh 轉換後放到 \(folder.path)"]
                )
            }
            // WhisperKit 會優先使用 CoreML encoder（ANE），decoder 走 GPU/CPU。
            let config = WhisperKitConfig(
                modelFolder: folder.path,
                verbose: true,
                logLevel: .info,
                prewarm: true,
                load: true,
                download: false
            )
            self.whisperKit = try await WhisperKit(config)
        }

        func unload() { whisperKit = nil }

        func transcribe(audioPath: String, language: String, enableDiarization: Bool) async throws -> EngineTranscriptionResult {
            guard let kit = whisperKit else {
                throw NSError(domain: "MeetsumLocalASR", code: 2003,
                              userInfo: [NSLocalizedDescriptionKey: "Breeze 模型尚未載入"])
            }
            // Breeze 以 Whisper 多語模型為基礎；台語／客語同樣使用 zh 語言 token，
            // 由模型本身依聲學特徵辨識，不需要額外語言代碼。
            let whisperLang: String
            switch language {
            case "nan", "hak", "zh": whisperLang = "zh"
            case "en": whisperLang = "en"
            default: whisperLang = "zh"
            }
            let options = DecodingOptions(
                task: .transcribe,
                language: whisperLang,
                temperature: 0,
                usePrefillPrompt: true,
                withoutTimestamps: false,
                chunkingStrategy: .vad
            )
            let results = try await kit.transcribe(audioPath: audioPath, decodeOptions: options)
            guard let result = results.first else {
                throw NSError(domain: "MeetsumLocalASR", code: 2002,
                              userInfo: [NSLocalizedDescriptionKey: "轉錄結果為空"])
            }
            let segments = result.segments.enumerated().map { index, segment in
                EngineTranscriptionSegment(
                    id: index,
                    start: segment.start,
                    end: segment.end,
                    text: segment.text,
                    speaker: "SPEAKER_00",
                    avgLogprob: segment.avgLogprob,
                    noSpeechProb: segment.noSpeechProb,
                    compressionRatio: segment.compressionRatio
                )
            }
            return EngineTranscriptionResult(
                segments: segments,
                language: language,
                duration: TimeInterval(segments.last?.end ?? 0)
            )
        }
    }

    func getModelFolder(modelSize: String, quantization: String) -> URL {
        let documentsPath = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
        let modelsDir = documentsPath.appendingPathComponent("WhisperKitModels", isDirectory: true)
        return modelsDir.appendingPathComponent("\(modelSize)_\(quantization)", isDirectory: true)
    }

    // MARK: - 模型管理

    @objc func isModelAvailable(_ call: CAPPluginCall) {
        guard let modelSize = call.getString("modelSize") else {
            call.reject("缺少 modelSize 參數")
            return
        }
        let quantization = call.getString("quantization") ?? "q4_k"
        let folder = getModelFolder(modelSize: modelSize, quantization: quantization)
        let exists = FileManager.default.fileExists(atPath: folder.path)

        call.resolve(["available": exists, "path": exists ? folder.path : NSNull()])
    }

    @objc func getAvailableModels(_ call: CAPPluginCall) {
        let models: [[String: Any]] = [
            ["name": "tiny", "size_mb": 75, "path": "", "downloaded": false, "quantization": "q4_k", "engine": "whisperkit"],
            ["name": "base", "size_mb": 142, "path": "", "downloaded": false, "quantization": "q4_k", "engine": "whisperkit"],
            ["name": "small", "size_mb": 466, "path": "", "downloaded": false, "quantization": "q4_k", "engine": "whisperkit"],
            ["name": "large-v3-v20240930_626MB", "size_mb": 600, "path": "", "downloaded": false, "quantization": "q4_k", "engine": "whisperkit"],
            ["name": "large-v3-v20240930_turbo", "size_mb": 1600, "path": "", "downloaded": false, "quantization": "q4_k", "engine": "whisperkit"],
            // Breeze-ASR-26：台語／華語／客語／英語；encoder 轉成 CoreML 跑 ANE
            ["name": "breeze-asr-26-coreml", "size_mb": 4300, "path": "", "downloaded": false, "quantization": "4bit", "engine": "breezeasr"],
        ].map { model in
            var m = model
            let folder = self.getModelFolder(modelSize: model["name"] as! String, quantization: model["quantization"] as! String)
            let exists = FileManager.default.fileExists(atPath: folder.appendingPathComponent("config.json").path)
            m["downloaded"] = exists
            m["path"] = exists ? folder.path : ""
            return m
        }

        call.resolve(["models": models])
    }

    @objc func downloadModel(_ call: CAPPluginCall) {
        guard let modelSize = call.getString("modelSize") else {
            call.reject("缺少 modelSize 參數")
            return
        }
        let quantization = call.getString("quantization") ?? "q4_k"
        let key = "\(modelSize)_\(quantization)"

        // 檢查是否已在下載
        downloadsQueue.sync {
            if self.activeDownloads[key] != nil {
                call.reject("模型已在下載中")
                return
            }
        }

        // 建立下載任務
        let task = ModelDownloadTask(
            modelSize: modelSize,
            quantization: quantization,
            plugin: self
        )
        downloadsQueue.async(flags: .barrier) {
            self.activeDownloads[key] = task
        }

        Task {
            do {
                try await task.start()
                downloadsQueue.async(flags: .barrier) {
                    self.activeDownloads.removeValue(forKey: key)
                }
                call.resolve(["success": true, "path": self.getModelFolder(modelSize: modelSize, quantization: quantization).path])
            } catch {
                downloadsQueue.async(flags: .barrier) {
                    self.activeDownloads.removeValue(forKey: key)
                }
                call.resolve(["success": false, "error": error.localizedDescription])
            }
        }
    }

    @objc func cancelDownload(_ call: CAPPluginCall) {
        guard let modelSize = call.getString("modelSize") else {
            call.reject("缺少 modelSize 參數")
            return
        }
        let quantization = call.getString("quantization") ?? "q4_k"
        let key = "\(modelSize)_\(quantization)"

        downloadsQueue.sync {
            if let task = self.activeDownloads[key] {
                task.cancel()
                self.activeDownloads.removeValue(forKey: key)
            }
        }
        call.resolve()
    }

    @objc func deleteModel(_ call: CAPPluginCall) {
        guard let modelSize = call.getString("modelSize") else {
            call.reject("缺少 modelSize 參數")
            return
        }
        let quantization = call.getString("quantization") ?? "q4_k"
        let folder = getModelFolder(modelSize: modelSize, quantization: quantization)

        do {
            if FileManager.default.fileExists(atPath: folder.path) {
                try FileManager.default.removeItem(at: folder)
            }
            // 如果模型在記憶體中，卸載它
            if let wk = whisperKit, let modelFolder = wk.modelFolder, modelFolder.path == folder.path {
                unloadWhisperKit()
            }
            call.resolve(["success": true])
        } catch {
            call.resolve(["success": false, "error": error.localizedDescription])
        }
    }

    // MARK: - 轉錄功能

    @objc func transcribe(_ call: CAPPluginCall) {
        guard let audioPath = call.getString("audioPath") else {
            call.reject("缺少 audioPath 參數")
            return
        }

        let language = call.getString("language") ?? "zh"
        let enableDiarization = call.getBool("enableDiarization") ?? true
        let modelSize = call.getString("modelSize") ?? "large-v3-v20240930_626MB"
        let quantization = call.getString("quantization") ?? "q4_k"
        let engineType = call.getString("engine") ?? "whisperkit"  // whisperkit | breezeasr
        let useVad = call.getBool("useVad") ?? true
        let vadThreshold = call.getDouble("vadThreshold") ?? 0.5

        let jobId = "job_\(Date().timeIntervalSince1970)_\(UUID().uuidString.prefix(8))"

        let job = TranscriptionJob(
            id: jobId,
            audioPath: audioPath,
            language: language,
            enableDiarization: enableDiarization,
            modelSize: modelSize,
            quantization: quantization,
            engineType: engineType,
            useVad: useVad,
            vadThreshold: vadThreshold,
            plugin: self
        )

        jobsQueue.async(flags: .barrier) {
            self.transcriptionJobs[jobId] = job
        }

        // 異步執行轉錄
        job.start()

        call.resolve(["jobId": jobId])
    }

    @objc func getTranscriptionStatus(_ call: CAPPluginCall) {
        guard let jobId = call.getString("jobId") else {
            call.reject("缺少 jobId 參數")
            return
        }

        jobsQueue.sync {
            if let job = self.transcriptionJobs[jobId] {
                var result: [String: Any] = [
                    "status": job.status.rawValue,
                    "progress": job.progress
                ]
                if let transcriptionResult = job.result {
                    result["result"] = transcriptionResult
                }
                if let error = job.error {
                    result["error"] = error
                }
                call.resolve(result)
            } else {
                call.resolve(["status": "failed", "error": "找不到轉錄任務"])
            }
        }
    }

    @objc func cancelTranscription(_ call: CAPPluginCall) {
        guard let jobId = call.getString("jobId") else {
            call.reject("缺少 jobId 參數")
            return
        }

        jobsQueue.sync {
            if let job = self.transcriptionJobs[jobId] {
                job.cancel()
            }
        }
        call.resolve()
    }

    @objc func clearCache(_ call: CAPPluginCall) {
        // 清理暫存檔案
        let tempDir = FileManager.default.temporaryDirectory
        let whisperKitCache = tempDir.appendingPathComponent("WhisperKit", isDirectory: true)

        do {
            if FileManager.default.fileExists(atPath: whisperKitCache.path) {
                try FileManager.default.removeItem(at: whisperKitCache)
            }
            call.resolve()
        } catch {
            call.reject("清理快取失敗: \(error.localizedDescription)")
        }
    }

    @objc func getDeviceCapabilities(_ call: CAPPluginCall) {
        let processInfo = ProcessInfo.processInfo
        let totalMemory = processInfo.physicalMemory
        let totalMemoryMB = Int(totalMemory / (1024 * 1024))

        // 檢查 Metal 支援
        let supportsMetal = MTLCreateSystemDefaultDevice() != nil

        // 檢查 Neural Engine (Apple Silicon)
        var supportsNeuralEngine = false
        #if targetEnvironment(simulator)
        supportsNeuralEngine = false
        #else
        supportsNeuralEngine = ProcessInfo.processInfo.isiOSAppOnMac || (totalMemory >= 6 * 1024 * 1024 * 1024) // 簡易判斷
        #endif

        // 推薦模型大小
        let recommendedModel: String
        if totalMemoryMB >= 6144 { // 6GB+
            recommendedModel = "large-v3-turbo"
        } else if totalMemoryMB >= 4096 { // 4GB+
            recommendedModel = "medium"
        } else {
            recommendedModel = "small"
        }

        call.resolve([
            "supportsMetal": supportsMetal,
            "supportsNeuralEngine": supportsNeuralEngine,
            "totalMemoryMB": totalMemoryMB,
            "availableMemoryMB": totalMemoryMB / 2, // 粗略估計
            "recommendedModelSize": recommendedModel
        ])
    }

    // MARK: - 事件發送

    func emitTranscriptionProgress(_ progress: DownloadProgress) {
        notifyListeners("transcriptionProgress", data: progress.toDictionary())
    }

    func emitTranscriptionComplete(_ result: TranscriptionResult) {
        notifyListeners("transcriptionComplete", data: result.toDictionary())
    }

    func emitTranscriptionError(jobId: String, message: String) {
        notifyListeners("transcriptionError", data: ["jobId": jobId, "message": message])
    }
}

// MARK: - 支援類別

enum TranscriptionStatus: String {
    case pending = "pending"
    case processing = "processing"
    case completed = "completed"
    case failed = "failed"
}

final class TranscriptionJob {
    let id: String
    let audioPath: String
    let language: String
    let enableDiarization: Bool
    let modelSize: String
    let quantization: String
    let engineType: String
    let useVad: Bool
    let vadThreshold: Double
    weak var plugin: MeetsumLocalASRPlugin?

    private(set) var status: TranscriptionStatus = .pending
    private(set) var progress: Double = 0
    private(set) var result: TranscriptionResult?
    private(set) var error: String?
    private var cancelled = false

    init(
        id: String,
        audioPath: String,
        language: String,
        enableDiarization: Bool,
        modelSize: String,
        quantization: String,
        engineType: String,
        useVad: Bool,
        vadThreshold: Double,
        plugin: MeetsumLocalASRPlugin?
    ) {
        self.id = id
        self.audioPath = audioPath
        self.language = language
        self.enableDiarization = enableDiarization
        self.modelSize = modelSize
        self.quantization = quantization
        self.engineType = engineType
        self.useVad = useVad
        self.vadThreshold = vadThreshold
        self.plugin = plugin
    }

    func start() {
        status = .processing
        progress = 0
        plugin?.emitTranscriptionProgress(DownloadProgress(
            modelName: "transcription",
            progress: 0,
            status: .downloading
        ))

        Task {
            await runTranscription()
        }
    }

    func cancel() {
        cancelled = true
        status = .failed
        error = "使用者取消"
        plugin?.emitTranscriptionError(jobId: id, message: "使用者取消")
    }

    private func runTranscription() async {
        guard let plugin = plugin else { return }

        do {
            // 解析音檔路徑
            let audioURL = resolveAudioURL(audioPath)

            // 選擇引擎
            let engine: LocalASREngine
            switch engineType {
            case "breezeasr":
                engine = BreezeASREngine(plugin: plugin)
            case "whisperkit":
                fallthrough
            default:
                engine = WhisperKitEngine(plugin: plugin)
            }

            // 載入模型
            updateProgress(0.1, status: .downloading)
            try await engine.load(modelSize: modelSize, quantization: quantization)

            // 執行轉錄
            updateProgress(0.3, status: .processing)
            let engineResult = try await engine.transcribe(
                audioPath: audioURL.path,
                language: language,
                enableDiarization: enableDiarization
            )

            // 講者辨識 (如果引擎不支援內建 diarization，使用 SpeakerKit)
            var diarizationSegments: [SpeakerSegment] = []
            if enableDiarization && !engine.supportsDiarization {
                updateProgress(0.6, status: .processing)
                do {
                    let speakerKit = try await plugin.loadSpeakerKit()
                    let audioArray = try AudioProcessor.loadAudioAsFloatArray(fromPath: audioURL.path)
                    let options = PyannoteDiarizationOptions(
                        numberOfSpeakers: nil,
                        clusterDistanceThreshold: 0.6,
                        useExclusiveReconciliation: false
                    )
                    let diarizationResult = try await speakerKit.diarize(audioArray: audioArray, options: options)
                    diarizationSegments = diarizationResult.segments
                    print("[MeetsumLocalASR] 講者辨識完成: \(diarizationSegments.count) 個片段")
                } catch {
                    print("[MeetsumLocalASR] 講者辨識失敗，使用預設講者: \(error)")
                }
            }

            // 將轉錄結果與講者資訊合併
            let segments: [TranscriptionSegment] = engineResult.segments.enumerated().map { index, segment in
                let segmentId = String(format: "S%04d", index + 1)
                let startMs = Int(segment.start * 1000)
                let endMs = Int(segment.end * 1000)

                // 根據時間重疊匹配講者
                var speaker = segment.speaker ?? "SPEAKER_00"
                if !diarizationSegments.isEmpty && engine.supportsDiarization == false {
                    // 找到時間重疊最多的講者片段
                    let segmentStart = segment.start
                    let segmentEnd = segment.end
                    var bestOverlap: Float = 0
                    var bestSpeaker = "SPEAKER_00"
                    for dSegment in diarizationSegments {
                        let dStart = dSegment.startTime
                        let dEnd = dSegment.endTime
                        let overlapStart = max(segmentStart, dStart)
                        let overlapEnd = min(segmentEnd, dEnd)
                        let overlap = max(0, overlapEnd - overlapStart)
                        if overlap > bestOverlap {
                            bestOverlap = overlap
                            if let speakerId = dSegment.speaker.speakerId {
                                bestSpeaker = "SPEAKER_\(String(format: "%02d", speakerId))"
                            }
                        }
                    }
                    speaker = bestSpeaker
                }

                return TranscriptionSegment(
                    segment_id: segmentId,
                    start_ms: startMs,
                    end_ms: endMs,
                    text: segment.text,
                    speaker: speaker,
                    avgLogprob: segment.avgLogprob,
                    noSpeechProb: segment.noSpeechProb,
                    compressionRatio: segment.compressionRatio
                )
            }

            // 計算總時長
            let totalDurationMs = segments.last?.end_ms ?? 0

            let result = TranscriptionResult(
                segments: segments,
                language: engineResult.language,
                duration_ms: totalDurationMs,
                model_used: "\(modelSize)_\(quantization)_\(engineType)"
            )

            self.result = result
            self.status = .completed
            self.progress = 1.0

            await MainActor.run {
                plugin.emitTranscriptionComplete(result)
                plugin.emitTranscriptionProgress(DownloadProgress(
                    modelName: "transcription",
                    progress: 100,
                    status: .completed
                ))
            }

        } catch {
            self.status = .failed
            self.error = error.localizedDescription
            let errorMessage = error.localizedDescription
            let currentJobId = id
            await MainActor.run {
                plugin.emitTranscriptionError(jobId: currentJobId, message: errorMessage)
                plugin.emitTranscriptionProgress(DownloadProgress(
                    modelName: "transcription",
                    progress: 0,
                    status: .failed,
                    error: errorMessage
                ))
            }
        }
    }

    private func updateProgress(_ progress: Double, status: DownloadProgress.DownloadStatus) {
        self.progress = progress
        plugin?.emitTranscriptionProgress(DownloadProgress(
            modelName: "transcription",
            progress: Int(progress * 100),
            status: status
        ))
    }

    private func resolveAudioURL(_ path: String) -> URL {
        if path.hasPrefix("file://") {
            return URL(string: path)!
        } else {
            // 相對路徑，假設在 Documents 目錄
            let documentsPath = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
            return documentsPath.appendingPathComponent(path)
        }
    }
}

final class ModelDownloadTask {
    let modelSize: String
    let quantization: String
    weak var plugin: MeetsumLocalASRPlugin?
    private var cancelled = false
    private var downloadTask: Task<URL, Error>?

    init(modelSize: String, quantization: String, plugin: MeetsumLocalASRPlugin) {
        self.modelSize = modelSize
        self.quantization = quantization
        self.plugin = plugin
    }

    func start() async throws {
        let target = getModelFolder()
        // 已有完整模型就直接結束
        if FileManager.default.fileExists(atPath: target.appendingPathComponent("config.json").path) {
            return
        }
        try FileManager.default.createDirectory(
            at: target.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )

        let isBreeze = modelSize.hasPrefix("breeze")
        // Breeze 需要先轉成 WhisperKit CoreML 格式；repo 可從 Info.plist 的
        // BreezeModelRepo 或 UserDefaults("meetsum.breeze_repo") 覆寫。
        var repo = UserDefaults.standard.string(forKey: "meetsum.breeze_repo")
            ?? (Bundle.main.object(forInfoDictionaryKey: "BreezeModelRepo") as? String)
            ?? ""
        repo = repo.trimmingCharacters(in: .whitespacesAndNewlines)
        var variant = (Bundle.main.object(forInfoDictionaryKey: "BreezeModelVariant") as? String) ?? ""
        variant = variant.trimmingCharacters(in: .whitespacesAndNewlines)
        if isBreeze && repo.isEmpty {
            throw NSError(
                domain: "MeetsumLocalASR",
                code: 2100,
                userInfo: [NSLocalizedDescriptionKey:
                    "尚未設定 Breeze 模型來源。請把轉換好的 CoreML 資料夾放到 Documents/WhisperKitModels/breeze-asr-26-coreml_4bit，或在 Info.plist 設定 BreezeModelRepo 後重新下載。"]
            )
        }
        if isBreeze && variant.isEmpty {
            // whisperkit-generate-model 的資料夾名稱帶有大小，例如
            // MediaTek-Research_Breeze-ASR-26_632MB，因此向 HF 查實際名稱。
            guard let resolved = try await Self.resolveBreezeVariant(repo: repo) else {
                throw NSError(
                    domain: "MeetsumLocalASR",
                    code: 2101,
                    userInfo: [NSLocalizedDescriptionKey:
                        "在 \(repo) 找不到 Breeze 模型資料夾，請確認已上傳轉換後的 CoreML 模型。"]
                )
            }
            variant = resolved
        }

        emit(progress: 0, status: .downloading)
        let downloaded = try await WhisperKit.download(
            variant: isBreeze ? variant : modelSize,
            from: isBreeze ? repo : "argmaxinc/whisperkit-coreml"
        ) { progress in
            let pct = Int(progress.fractionCompleted * 100)
            self.emit(progress: pct, status: .downloading)
        }
        if cancelled { throw CancellationError() }

        // WhisperKit 會下載到自己的快取；移到我們管理的資料夾
        if downloaded.standardizedFileURL != target.standardizedFileURL {
            let fm = FileManager.default
            if fm.fileExists(atPath: target.path) { try fm.removeItem(at: target) }
            try fm.copyItem(at: downloaded, to: target)
        }
        emit(progress: 100, status: .completed)
    }

    func cancel() {
        cancelled = true
        downloadTask?.cancel()
    }

    /// 向 Hugging Face 查詢 repo 內的模型資料夾名稱。
    ///
    /// `whisperkit-generate-model` 產生的名稱形如
    /// `MediaTek-Research_Breeze-ASR-26_632MB`，大小會隨量化與模型版本變動，
    /// 所以不寫死；多個 variant 時挑 MB 最小的（量化最多，最適合手機）。
    static func resolveBreezeVariant(repo: String) async throws -> String? {
        guard let url = URL(string: "https://huggingface.co/api/models/\(repo)/tree/main") else {
            return nil
        }
        var req = URLRequest(url: url)
        req.timeoutInterval = 30
        req.setValue("MeetSum/1.2 (iOS; on-device)", forHTTPHeaderField: "User-Agent")
        let (data, res) = try await URLSession.shared.data(for: req)
        guard let http = res as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            return nil
        }
        guard let items = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] else {
            return nil
        }
        let folders = items.compactMap { item -> String? in
            guard (item["type"] as? String) == "directory" else { return nil }
            let path = item["path"] as? String ?? ""
            return path.isEmpty ? nil : path
        }.filter { $0.lowercased().contains("breeze") }
        guard !folders.isEmpty else { return nil }

        func sizeMB(_ name: String) -> Int {
            guard let range = name.range(of: #"(\d+)MB$"#, options: .regularExpression) else {
                return Int.max
            }
            return Int(name[range].dropLast(2)) ?? Int.max
        }
        return folders.min { sizeMB($0) < sizeMB($1) }
    }

    private func emit(progress: Int, status: DownloadProgress.DownloadStatus, error: String? = nil) {
        guard let plugin else { return }
        let payload = DownloadProgress(
            modelName: "\(modelSize)_\(quantization)",
            progress: progress,
            status: status,
            error: error
        )
        plugin.notifyListeners("transcriptionProgress", data: payload.toDictionary())
    }

    private func getModelFolder() -> URL {
        let documentsPath = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
        let modelsDir = documentsPath.appendingPathComponent("WhisperKitModels", isDirectory: true)
        return modelsDir.appendingPathComponent("\(modelSize)_\(quantization)", isDirectory: true)
    }
}

struct TranscriptionSegment {
    let segment_id: String
    let start_ms: Int
    let end_ms: Int
    let text: String
    let speaker: String
    let avgLogprob: Float?
    let noSpeechProb: Float?
    let compressionRatio: Float?

    func toDictionary() -> [String: Any] {
        var dict: [String: Any] = [
            "segment_id": segment_id,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "text": text,
            "speaker": speaker
        ]
        if let avgLogprob = avgLogprob { dict["avg_logprob"] = avgLogprob }
        if let noSpeechProb = noSpeechProb { dict["no_speech_prob"] = noSpeechProb }
        if let compressionRatio = compressionRatio { dict["compression_ratio"] = compressionRatio }
        return dict
    }
}

struct TranscriptionResult {
    let segments: [TranscriptionSegment]
    let language: String?
    let duration_ms: Int?
    let model_used: String?

    func toDictionary() -> [String: Any] {
        var dict: [String: Any] = [
            "segments": segments.map { $0.toDictionary() }
        ]
        if let language = language { dict["language"] = language }
        if let duration = duration_ms { dict["duration_ms"] = duration }
        if let model = model_used { dict["model_used"] = model }
        return dict
    }
}

struct DownloadProgress {
    let modelName: String
    let progress: Int
    let status: DownloadStatus
    let bytesDownloaded: Int64?
    let totalBytes: Int64?
    let error: String?

    enum DownloadStatus: String {
        case downloading = "downloading"
        case processing = "processing"
        case verifying = "verifying"
        case completed = "completed"
        case failed = "failed"
    }

    init(modelName: String, progress: Int, status: DownloadStatus, bytesDownloaded: Int64? = nil, totalBytes: Int64? = nil, error: String? = nil) {
        self.modelName = modelName
        self.progress = progress
        self.status = status
        self.bytesDownloaded = bytesDownloaded
        self.totalBytes = totalBytes
        self.error = error
    }

    func toDictionary() -> [String: Any] {
        var dict: [String: Any] = [
            "modelName": modelName,
            "progress": progress,
            "status": status.rawValue
        ]
        if let bytes = bytesDownloaded { dict["bytesDownloaded"] = bytes }
        if let total = totalBytes { dict["totalBytes"] = total }
        if let error = error { dict["error"] = error }
        return dict
    }
}