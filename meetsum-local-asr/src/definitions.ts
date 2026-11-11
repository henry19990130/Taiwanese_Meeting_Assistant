import { Plugin } from '@capacitor/core';

export interface TranscriptionOptions {
  /**
   * 音檔路徑 (file:// URI 或 Documents 相對路徑)
   */
  audioPath: string;

  /**
   * 語言代碼: "zh", "nan", "hak", "en", "auto"
   */
  language: string;

  /**
   * 是否啟用講者辨識
   * @default true
   */
  enableDiarization?: boolean;

  /**
   * 模型大小
   * @default "large-v3-turbo"
   */
  modelSize?: "tiny" | "base" | "small" | "medium" | "large-v3" | "large-v3-turbo";

  /**
   * 量化等級
   * @default "q4_k"
   */
  quantization?: "q4_k" | "q5_k" | "q8_0" | "fp16" | "4bit";

  /**
   * ASR 引擎：whisperkit（一般 Whisper）或 breezeasr（Breeze-ASR-26 CoreML）
   * @default "whisperkit"
   */
  engine?: "whisperkit" | "breezeasr";

  /**
   * 是否使用 VAD (語音活動偵測) 過濾靜音
   * @default true
   */
  useVad?: boolean;

  /**
   * VAD 閾值
   * @default 0.5
   */
  vadThreshold?: number;
}

export interface TranscriptionSegment {
  segment_id: string;
  start_ms: number;
  end_ms: number;
  text: string;
  speaker?: string;
  avg_logprob?: number;
  no_speech_prob?: number;
  compression_ratio?: number;
}

export interface TranscriptionResult {
  segments: TranscriptionSegment[];
  language?: string;
  duration_ms?: number;
  model_used?: string;
}

export interface ModelInfo {
  name: string;
  size_mb: number;
  path: string;
  downloaded: boolean;
  quantization: string;
}

export interface DownloadProgress {
  modelName: string;
  progress: number; // 0-100
  status: 'downloading' | 'verifying' | 'completed' | 'failed';
  bytesDownloaded?: number;
  totalBytes?: number;
  error?: string;
}

export interface LocalASRPlugin extends Plugin {
  /**
   * 檢查模型是否已下載
   */
  isModelAvailable(options: { modelSize: string; quantization?: string }): Promise<{ available: boolean; path?: string }>;

  /**
   * 取得可用模型列表
   */
  getAvailableModels(): Promise<{ models: ModelInfo[] }>;

  /**
   * 下載模型
   */
  downloadModel(options: { modelSize: string; quantization?: string }): Promise<{ success: boolean; path?: string; error?: string }>;

  /**
   * 取消下載
   */
  cancelDownload(options: { modelSize: string }): Promise<void>;

  /**
   * 刪除模型
   */
  deleteModel(options: { modelSize: string; quantization?: string }): Promise<{ success: boolean }>;

  /**
   * 開始轉錄 (非同步，回傳 job ID)
   */
  transcribe(options: TranscriptionOptions): Promise<{ jobId: string }>;

  /**
   * 取得轉錄進度/結果
   */
  getTranscriptionStatus(options: { jobId: string }): Promise<{
    status: 'pending' | 'processing' | 'completed' | 'failed';
    progress?: number;
    result?: TranscriptionResult;
    error?: string;
  }>;

  /**
   * 取消轉錄
   */
  cancelTranscription(options: { jobId: string }): Promise<void>;

  /**
   * 清理暫存檔案
   */
  clearCache(): Promise<void>;

  /**
   * 取得裝置能力資訊
   */
  getDeviceCapabilities(): Promise<{
    supportsMetal: boolean;
    supportsNeuralEngine: boolean;
    totalMemoryMB: number;
    availableMemoryMB: number;
    recommendedModelSize: string;
  }>;

  /**
   * 事件監聽
   */
  addListener(eventName: 'transcriptionProgress', listener: (progress: DownloadProgress) => void): Promise<{ remove: () => void }>;
  addListener(eventName: 'transcriptionComplete', listener: (result: TranscriptionResult) => void): Promise<{ remove: () => void }>;
  addListener(eventName: 'transcriptionError', listener: (error: { jobId: string; message: string }) => void): Promise<{ remove: () => void }>;
  removeAllListeners(): Promise<void>;
}

// 型別擴充：註冊插件
declare module '@capacitor/core' {
  interface PluginRegistry {
    MeetsumLocalASR: LocalASRPlugin;
  }
}