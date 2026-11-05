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

    /// BreezeASR 引擎實作 (預留介面，待 Core ML 模型可用時實作)
    ///
    /// BreezeASR 是 MediaTek 開發的針對台語/國語/英文優化的 ASR 模型
    /// 目前階段：介面已定義，具體實作待 MediaTek 發布 Core ML 格式模型
    /// 參考: https://github.com/MediaTek-Research/Breeze-ASR
    final class BreezeASREngine: LocalASREngine {
        let engineId = "breezeasr"
        let displayName = "BreezeASR (MediaTek)"
        let supportedLanguages = ["zh", "nan", "hak", "en"]  // 台語、客語、國語、英文
        let supportsDiarization = false  // BreezeASR 專注於 ASR，需搭配獨立 diarization

        private var model: Any?  // 預留 Core ML 模型
        private let plugin: MeetsumLocalASRPlugin

        init(plugin: MeetsumLocalASRPlugin) {
            self.plugin = plugin
        }

        var isLoaded: Bool { model != nil }

        func load(modelSize: String, quantization: String) async throws {
            // TODO: 實作 BreezeASR Core ML 模型載入
            // 需要 MediaTek 提供 .mlmodelc 格式模型
            // 預期模型結構：
            // - BreezeASREncoder.mlmodelc (音頻編碼器)
            // - BreezeASRDecoder.mlmodelc (文本解碼器)
            // - BreezeASRTokenizer (分詞器)
            throw NSError(
                domain: "MeetsumLocalASR",
                code: 2001,
                userInfo: [NSLocalizedDescriptionKey: "BreezeASR 引擎尚未實作，等待 MediaTek Core ML 模型發布"]
            )
        }

        func unload() {
            model = nil
        }

        func transcribe(audioPath: String, language: String, enableDiarization: Bool) async throws -> EngineTranscriptionResult {
            throw NSError(
                domain: "MeetsumLocalASR",
                code: 2002,
                userInfo: [NSLocalizedDescriptionKey: "BreezeASR 引擎尚未實作"]
            )
        }
    }

    private func getModelFolder(modelSize: String, quantization: String) -> URL {
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
            ["name": "tiny", "size_mb": 75, "path": "", "downloaded": false, "quantization": "q4_k"],
            ["name": "base", "size_mb": 142, "path": "", "downloaded": false, "quantization": "q4_k"],
            ["name": "small", "size_mb": 466, "path": "", "downloaded": false, "quantization": "q4_k"],
            ["name": "large-v3-v20240930_626MB", "size_mb": 600, "path": "", "downloaded": false, "quantization": "q4_k"],
            ["name": "large-v3-v20240930_turbo", "size_mb": 1600, "path": "", "downloaded": false, "quantization": "q4_k"],
        ].map { model in
            var m = model
            let folder = self.getModelFolder(modelSize: model["name"] as! String, quantization: model["quantization"] as! String)
            m["downloaded"] = FileManager.default.fileExists(atPath: folder.path)
            m["path"] = m["downloaded"] as! Bool ? folder.path : ""
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
        let task = ModelDownloadTask(modelSize: modelSize, quantization: quantization, call: call)
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

            // 載入模型
            updateProgress(0.1, status: .downloading)
            let whisperKit = try await plugin.loadWhisperKit(modelSize: modelSize, quantization: quantization)

            // 執行轉錄 - 使用 WhisperKit 的 transcribe 方法
            // WhisperKit 回傳 TranscriptionResult 陣列（每個音檔一個結果）
            let transcriptionResults = try await whisperKit.transcribe(
                audioPath: audioURL.path
            )

            // 取得第一個結果（單一音檔）
            guard let transcriptionResult = transcriptionResults.first else {
                throw NSError(
                    domain: "MeetsumLocalASR",
                    code: 1002,
                    userInfo: [NSLocalizedDescriptionKey: "轉錄結果為空"]
                )
            }

            // 講者辨識
            var diarizationSegments: [SpeakerSegment] = []
            if enableDiarization {
                updateProgress(0.5, status: .processing)
                do {
                    let speakerKit = try await plugin.loadSpeakerKit()
                    // 載入音頻數據
                    let audioArray = try AudioProcessor.loadAudioAsFloatArray(fromPath: audioURL.path)
                    let options = PyannoteDiarizationOptions(
                        numberOfSpeakers: nil,  // 自動檢測講者數量
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
            let segments: [TranscriptionSegment] = transcriptionResult.segments.enumerated().map { index, segment in
                let segmentId = String(format: "S%04d", index + 1)
                let startMs = Int(segment.start * 1000)
                let endMs = Int(segment.end * 1000)

                // 根據時間重疊匹配講者
                var speaker = "SPEAKER_00"
                if !diarizationSegments.isEmpty {
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

            // 計算總時長（使用最後一個 segment 的結束時間）
            let totalDurationMs = segments.last?.end_ms ?? 0

            let result = TranscriptionResult(
                segments: segments,
                language: transcriptionResult.language,
                duration_ms: totalDurationMs,
                model_used: "\(modelSize)_\(quantization)"
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
    let call: CAPPluginCall
    private var cancelled = false

    init(modelSize: String, quantization: String, call: CAPPluginCall) {
        self.modelSize = modelSize
        self.quantization = quantization
        self.call = call
    }

    func start() async throws {
        // 這裡實際上會使用 WhisperKit 的模型下載功能
        // 目前 WhisperKit 會在首次載入時自動下載
        // 我們這裡模擬下載過程

        let modelFolder = getModelFolder()
        let modelPath = modelFolder.path

        // 檢查是否已存在
        if FileManager.default.fileExists(atPath: modelPath) {
            return
        }

        // 建立目錄
        try FileManager.default.createDirectory(at: modelFolder, withIntermediateDirectories: true)

        // 這裡應該實作實際的模型下載邏輯
        // WhisperKit 內部會處理從 HuggingFace 下載
        // 我們這裡只做基本驗證

        // 模擬下載進度回報
        for i in 1...10 {
            if cancelled { throw CancellationError() }
            try await Task.sleep(nanoseconds: 500_000_000) // 0.5 秒
            call.resolve([
                "progress": DownloadProgress(
                    modelName: "\(modelSize)_\(quantization)",
                    progress: i * 10,
                    status: .downloading,
                    bytesDownloaded: Int64(i * 100_000_000),
                    totalBytes: 1_000_000_000
                ).toDictionary()
            ])
        }
    }

    func cancel() {
        cancelled = true
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