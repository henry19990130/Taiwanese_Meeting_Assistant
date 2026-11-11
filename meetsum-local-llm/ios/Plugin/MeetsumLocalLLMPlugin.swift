//
//  MeetsumLocalLLMPlugin.swift
//  MeetsumLocalLLM
//
//  裝置內摘要：MLX Swift + Bonsai 27B 1-bit（約 3.9 GB）
//  模型不打包進 IPA，第一次使用時下載到 Application Support/models/。
//

import Foundation
import Capacitor
import UIKit

@objc(MeetsumLocalLLMPlugin)
public class MeetsumLocalLLMPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "MeetsumLocalLLM"
    public let jsName = "MeetsumLocalLLM"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "modelStatus", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "downloadModel", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "cancelDownload", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "deleteModel", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "loadModel", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "unload", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "summarize", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "cancelSummary", returnType: CAPPluginReturnPromise),
    ]

    private let engine = MLXEngine()
    private var summaryTask: Task<Void, Never>?

    public override func load() {
        super.load()
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(handleMemoryWarning),
            name: UIApplication.didReceiveMemoryWarningNotification,
            object: nil
        )
    }

    @objc private func handleMemoryWarning() {
        Task { await engine.unload() }
    }

    // MARK: - 模型管理

    @objc func modelStatus(_ call: CAPPluginCall) {
        Task {
            let memoryMB = Int(ProcessInfo.processInfo.physicalMemory / (1024 * 1024))
            let recommended = memoryMB >= 7000 ? "bonsai-27b-1bit" : "bonsai-8b-1bit"

            var models: [[String: Any]] = []
            for spec in ModelManager.specs {
                let downloaded = await ModelManager.shared.isDownloaded(spec.id)
                let folder = try? await ModelManager.shared.folder(for: spec.id)
                let path = folder?.path ?? ""
                models.append([
                    "id": spec.id,
                    "name": spec.name,
                    "sizeMB": spec.sizeMB,
                    "downloaded": downloaded,
                    "path": downloaded ? path : "",
                    "requiredMemoryMB": spec.requiredMemoryMB,
                    "recommended": spec.id == recommended,
                ])
            }
            let loaded = await engine.loadedModelId
            call.resolve([
                "models": models,
                "totalMemoryMB": memoryMB,
                "recommendedModelId": recommended,
                "loadedModelId": loaded ?? NSNull(),
            ])
        }
    }

    @objc func downloadModel(_ call: CAPPluginCall) {
        guard let modelId = call.getString("modelId") else {
            call.reject("缺少 modelId 參數")
            return
        }
        Task {
            do {
                let dir = try await ModelManager.shared.download(modelId: modelId) { done, total in
                    let pct = total > 0 ? Int(Double(done) / Double(total) * 100) : 0
                    self.notifyListeners("modelProgress", data: [
                        "modelId": modelId,
                        "progress": min(pct, 99),
                        "status": "downloading",
                        "bytesDownloaded": done,
                        "totalBytes": total,
                    ])
                }
                self.notifyListeners("modelProgress", data: [
                    "modelId": modelId,
                    "progress": 100,
                    "status": "completed",
                ])
                call.resolve(["success": true, "path": dir.path])
            } catch {
                self.notifyListeners("modelProgress", data: [
                    "modelId": modelId,
                    "progress": 0,
                    "status": "failed",
                    "error": error.localizedDescription,
                ])
                call.resolve(["success": false, "error": error.localizedDescription])
            }
        }
    }

    @objc func cancelDownload(_ call: CAPPluginCall) {
        guard let modelId = call.getString("modelId") else { call.reject("缺少 modelId"); return }
        Task {
            await ModelManager.shared.cancel(modelId)
            call.resolve()
        }
    }

    @objc func deleteModel(_ call: CAPPluginCall) {
        guard let modelId = call.getString("modelId") else { call.reject("缺少 modelId"); return }
        Task {
            do {
                await engine.unload()
                try await ModelManager.shared.delete(modelId)
                call.resolve(["success": true])
            } catch {
                call.resolve(["success": false, "error": error.localizedDescription])
            }
        }
    }

    @objc func loadModel(_ call: CAPPluginCall) {
        guard let modelId = call.getString("modelId") else { call.reject("缺少 modelId"); return }
        Task {
            do {
                let dir = try await ModelManager.shared.folder(for: modelId)
                try await engine.load(modelId: modelId, directory: dir)
                call.resolve(["success": true])
            } catch {
                call.resolve(["success": false, "error": error.localizedDescription])
            }
        }
    }

    @objc func unload(_ call: CAPPluginCall) {
        Task {
            await engine.unload()
            call.resolve()
        }
    }

    // MARK: - 摘要

    @objc func summarize(_ call: CAPPluginCall) {
        guard let transcript = call.getString("transcript"), !transcript.isEmpty else {
            call.reject("缺少 transcript")
            return
        }
        let language = call.getString("language") ?? "zh"
        let meetingName = call.getString("meetingName") ?? "會議"
        let glossary = call.getArray("glossary", String.self) ?? []
        let maxTokens = call.getInt("maxTokens") ?? 2048

        // 選模型：優先使用已下載的 27B，其次 8B
        Task {
            let modelId = await self.pickModel()
            guard let modelId else {
                call.reject("尚未下載本機摘要模型，請先到「本機模型」下載")
                return
            }
            let dir: URL
            do { dir = try await ModelManager.shared.folder(for: modelId) }
            catch { call.reject("找不到模型：\(error.localizedDescription)"); return }

            let system = Self.systemPrompt(language: language)
            let user = Self.userPrompt(
                meetingName: meetingName,
                transcript: transcript,
                glossary: glossary
            )
            let started = Date()
            let collector = TokenCollector()

            let task = Task {
                do {
                    let text = try await self.engine.summarize(
                        modelId: modelId,
                        directory: dir,
                        systemPrompt: system,
                        userPrompt: user,
                        maxTokens: maxTokens
                    ) { chunk in
                        let idx = collector.append(chunk)
                        self.notifyListeners("llmToken", data: ["token": chunk, "index": idx])
                    }
                    let ms = Int(Date().timeIntervalSince(started) * 1000)
                    self.notifyListeners("llmDone", data: ["text": text, "durationMs": ms])
                    let json = SummaryJSONParser.parse(text)
                    call.resolve([
                        "text": text,
                        "json": json ?? NSNull(),
                        "model": modelId,
                        "durationMs": ms,
                    ])
                } catch {
                    call.reject("摘要失敗：\(error.localizedDescription)")
                }
            }
            self.summaryTask = task
            await task.value
        }
    }

    @objc func cancelSummary(_ call: CAPPluginCall) {
        summaryTask?.cancel()
        summaryTask = nil
        Task {
            await engine.cancel()
            call.resolve()
        }
    }

    private func pickModel() async -> String? {
        for id in ["bonsai-27b-1bit", "bonsai-8b-1bit"] {
            if await ModelManager.shared.isDownloaded(id) { return id }
        }
        return nil
    }

    // MARK: - 提示詞

    static func systemPrompt(language: String) -> String {
        let langRule = language == "en"
            ? "Write all output in English."
            : "一律使用繁體中文（台灣用語）輸出，不要出現簡體字。"
        return """
        你是專業的會議紀錄助理。請把逐字稿整理成結構化重點，只能根據逐字稿內容，不要臆測。
        \(langRule)

        只輸出一個 JSON 物件，不要加任何說明或 Markdown 圍欄，格式如下：
        {
          "headline": "一句話總結",
          "decisions":   [{"summary": "決議內容", "evidence": [{"segment_id": "S0001", "quote": "原文"}]}],
          "action_items":[{"assignees": ["王小明"], "task": "待辦事項", "due_date": null, "due_text": null}],
          "discussions": [{"topic": "議題", "summary": "討論摘要", "key_points": ["重點"], "evidence": []}],
          "reports":     [{"topic": "報告事項", "summary": "內容", "evidence": []}],
          "next_meeting":{"status": "confirmed|tentative|not_mentioned", "date": null, "date_text": null, "time": null},
          "review_notes":[{"reason": "需要人工確認的地方", "field": "欄位名稱"}]
        }
        沒有內容的欄位請給空陣列。evidence 的 segment_id 必須來自逐字稿的 [Sxxxx] 標記。
        """
    }

    static func userPrompt(meetingName: String, transcript: String, glossary: [String]) -> String {
        var text = "會議名稱：\(meetingName)\n"
        if !glossary.isEmpty {
            text += "專有名詞（請保持原樣，不要改寫）：\(glossary.joined(separator: "、"))\n"
        }
        // 控制 context：太長的逐字稿先截斷（前端可先做 map-reduce）
        let limit = 60_000
        if transcript.count > limit {
            text += "\n逐字稿（已截斷）：\n" + String(transcript.prefix(limit))
        } else {
            text += "\n逐字稿：\n" + transcript
        }
        return text
    }
}

/// 執行緒安全地累積串流輸出（給 llmToken 事件用）
final class TokenCollector: @unchecked Sendable {
    private let lock = NSLock()
    private var count = 0

    func append(_ text: String) -> Int {
        lock.lock()
        defer { lock.unlock() }
        count += 1
        return count
    }
}
