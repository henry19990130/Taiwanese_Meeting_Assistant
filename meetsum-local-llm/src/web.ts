import { WebPlugin } from '@capacitor/core';
import type {
  LocalLLMPlugin,
  LLMModelInfo,
  SummarizeOptions,
  SummarizeResult,
  ModelProgress,
} from './definitions';

/**
 * 瀏覽器環境沒有 MLX，只能回報「不支援」。
 * App 會依錯誤訊息提示使用者改用雲端模式。
 */
export class MeetsumLocalLLMWeb extends WebPlugin implements LocalLLMPlugin {
  private loaded: string | null = null;

  async modelStatus(): Promise<{
    models: LLMModelInfo[];
    totalMemoryMB: number;
    recommendedModelId: string;
    loadedModelId: string | null;
  }> {
    const memGB = (navigator as any).deviceMemory || 4;
    return {
      models: [
        {
          id: 'bonsai-27b-1bit',
          name: 'Bonsai 27B 1-bit',
          sizeMB: 3900,
          downloaded: false,
          requiredMemoryMB: 5200,
          recommended: memGB >= 8,
        },
      ],
      totalMemoryMB: Math.round(memGB * 1024),
      recommendedModelId: 'bonsai-27b-1bit',
      loadedModelId: this.loaded,
    };
  }

  async downloadModel(_options: { modelId: string }): Promise<{ success: boolean; path?: string; error?: string }> {
    return { success: false, error: '瀏覽器不支援本機模型，請使用 iOS App 或雲端模式' };
  }

  async cancelDownload(_options: { modelId: string }): Promise<void> {
    /* no-op */
  }

  async deleteModel(_options: { modelId: string }): Promise<{ success: boolean }> {
    return { success: true };
  }

  async loadModel(_options: { modelId: string }): Promise<{ success: boolean }> {
    return { success: false };
  }

  async unload(): Promise<void> {
    this.loaded = null;
  }

  async summarize(_options: SummarizeOptions): Promise<SummarizeResult> {
    throw new Error('瀏覽器不支援本機摘要，請切換到雲端模式');
  }

  async cancelSummary(): Promise<void> {
    /* no-op */
  }

  async addListener(
    eventName: 'modelProgress' | 'llmToken' | 'llmDone',
    _listener: (data: any) => void,
  ): Promise<{ remove: () => void }> {
    return { remove: () => {} };
  }

  async removeAllListeners(): Promise<void> {
    /* no-op */
  }
}

export type { ModelProgress };
