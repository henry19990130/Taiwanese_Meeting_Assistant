import { Plugin } from '@capacitor/core';

export interface LLMModelInfo {
  id: string;
  name: string;
  /** 模型檔案大小（MB） */
  sizeMB: number;
  downloaded: boolean;
  /** 已下載模型的資料夾路徑 */
  path?: string;
  /** 需要的記憶體（MB） */
  requiredMemoryMB?: number;
  /** 是否建議在這台裝置使用 */
  recommended?: boolean;
}

export interface SummarizeOptions {
  /** 逐字稿純文字（可含 [S0001] 之類的段落標記） */
  transcript: string;
  /** 摘要語言：zh / en */
  language?: string;
  /** 會議名稱 */
  meetingName?: string;
  /** 專有名詞，避免模型改寫 */
  glossary?: string[];
  /** 最多生成 token 數 */
  maxTokens?: number;
}

export interface SummarizeJSON {
  headline?: string;
  decisions?: Array<{ summary: string; evidence?: any[] }>;
  action_items?: Array<{
    assignees?: string[];
    task: string;
    due_date?: string | null;
    due_text?: string | null;
  }>;
  discussions?: Array<{ topic?: string; summary?: string; key_points?: string[]; evidence?: any[] }>;
  reports?: Array<{ topic?: string; summary?: string; evidence?: any[] }>;
  next_meeting?: { status?: string; date?: string | null; date_text?: string | null; time?: string | null };
  review_notes?: Array<{ reason: string; field?: string }>;
}

export interface SummarizeResult {
  /** 模型原始輸出（Markdown/JSON 混合） */
  text: string;
  /** 解析成功的結構化資料；解析失敗時為 null */
  json: SummarizeJSON | null;
  /** 實際使用的模型 id */
  model: string;
  /** 生成耗時（毫秒） */
  durationMs: number;
}

export interface ModelProgress {
  modelId: string;
  progress: number; // 0-100
  status: 'downloading' | 'verifying' | 'extracting' | 'completed' | 'failed';
  bytesDownloaded?: number;
  totalBytes?: number;
  error?: string;
}

export interface LocalLLMPlugin extends Plugin {
  /** 目前模型狀態與裝置建議 */
  modelStatus(): Promise<{
    models: LLMModelInfo[];
    totalMemoryMB: number;
    recommendedModelId: string;
    loadedModelId: string | null;
  }>;

  /** 下載模型（背景可續傳；進度用 modelProgress 事件） */
  downloadModel(options: { modelId: string }): Promise<{ success: boolean; path?: string; error?: string }>;

  /** 取消下載 */
  cancelDownload(options: { modelId: string }): Promise<void>;

  /** 刪除已下載模型 */
  deleteModel(options: { modelId: string }): Promise<{ success: boolean }>;

  /** 載入模型（下載完成後第一次使用會自動載入） */
  loadModel(options: { modelId: string }): Promise<{ success: boolean }>;

  /** 卸載模型，釋放記憶體 */
  unload(): Promise<void>;

  /** 產生會議摘要；llmToken 事件會串流輸出 */
  summarize(options: SummarizeOptions): Promise<SummarizeResult>;

  /** 取消目前的生成 */
  cancelSummary(): Promise<void>;

  addListener(eventName: 'modelProgress', listener: (progress: ModelProgress) => void): Promise<{ remove: () => void }>;
  addListener(eventName: 'llmToken', listener: (data: { token: string; index: number }) => void): Promise<{ remove: () => void }>;
  addListener(eventName: 'llmDone', listener: (data: { text: string; durationMs: number }) => void): Promise<{ remove: () => void }>;
  removeAllListeners(): Promise<void>;
}

declare module '@capacitor/core' {
  interface PluginRegistry {
    MeetsumLocalLLM: LocalLLMPlugin;
  }
}
