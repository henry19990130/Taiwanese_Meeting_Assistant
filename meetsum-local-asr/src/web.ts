import { WebPlugin } from '@capacitor/core';
import type { LocalASRPlugin, TranscriptionOptions, TranscriptionResult, ModelInfo, DownloadProgress } from './definitions';

/**
 * Web 端降級實作
 * 瀏覽器環境無法運行 WhisperKit，提供 API 相容介面
 * 實際轉錄需在 iOS 原生環境執行
 */
export class MeetsumLocalASRWeb extends WebPlugin implements LocalASRPlugin {
  private availableModels: ModelInfo[] = [
    { name: 'tiny', size_mb: 75, path: '', downloaded: false, quantization: 'q4_k' },
    { name: 'base', size_mb: 142, path: '', downloaded: false, quantization: 'q4_k' },
    { name: 'small', size_mb: 466, path: '', downloaded: false, quantization: 'q4_k' },
    { name: 'medium', size_mb: 1500, path: '', downloaded: false, quantization: 'q4_k' },
    { name: 'large-v3', size_mb: 2900, path: '', downloaded: false, quantization: 'q4_k' },
    { name: 'large-v3-turbo', size_mb: 1600, path: '', downloaded: false, quantization: 'q4_k' },
  ];

  private downloadListeners: Map<string, (progress: DownloadProgress) => void> = new Map();
  private transcriptionJobs: Map<string, { status: string; progress: number; result?: TranscriptionResult; error?: string }> = new Map();
  private progressListeners: Map<string, (progress: DownloadProgress) => void> = new Map();

  async isModelAvailable(options: { modelSize: string; quantization?: string }): Promise<{ available: boolean; path?: string }> {
    console.warn('[MeetsumLocalASR] Web 環境無法使用本地模型，請在 iOS 實機上測試');
    const model = this.availableModels.find(m => m.name === options.modelSize);
    return { available: false, path: undefined };
  }

  async getAvailableModels(): Promise<{ models: ModelInfo[] }> {
    return { models: this.availableModels };
  }

  async downloadModel(options: { modelSize: string; quantization?: string }): Promise<{ success: boolean; path?: string; error?: string }> {
    console.warn('[MeetsumLocalASR] Web 環境不支援模型下載，請在 iOS 實機上操作');
    return { success: false, error: 'Web 環境不支援模型下載' };
  }

  async cancelDownload(options: { modelSize: string }): Promise<void> {
    console.warn('[MeetsumLocalASR] Web 環境無下載任務可取消');
  }

  async deleteModel(options: { modelSize: string; quantization?: string }): Promise<{ success: boolean }> {
    console.warn('[MeetsumLocalASR] Web 環境無本地模型可刪除');
    return { success: true };
  }

  async transcribe(options: TranscriptionOptions): Promise<{ jobId: string }> {
    console.warn('[MeetsumLocalASR] Web 環境無法執行本地轉錄，請在 iOS 實機上測試或使用雲端 API');
    const jobId = `job_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;

    // 模擬失敗狀態
    this.transcriptionJobs.set(jobId, {
      status: 'failed',
      progress: 0,
      error: 'Web 環境不支援本地轉錄，請使用 iOS 實機或雲端 API'
    });

    // 觸發錯誤事件
    setTimeout(() => {
      const errorListeners = this.progressListeners.get('transcriptionError');
      if (errorListeners) {
        errorListeners({ jobId, message: 'Web 環境不支援本地轉錄' });
      }
    }, 100);

    return { jobId };
  }

  async getTranscriptionStatus(options: { jobId: string }): Promise<{
    status: 'pending' | 'processing' | 'completed' | 'failed';
    progress?: number;
    result?: TranscriptionResult;
    error?: string;
  }> {
    const job = this.transcriptionJobs.get(options.jobId);
    if (!job) {
      return { status: 'failed', error: '找不到轉錄任務' };
    }
    return job;
  }

  async cancelTranscription(options: { jobId: string }): Promise<void> {
    const job = this.transcriptionJobs.get(options.jobId);
    if (job) {
      job.status = 'failed';
      job.error = '使用者取消';
    }
  }

  async clearCache(): Promise<void> {
    console.log('[MeetsumLocalASR] Web 環境清除快取 (無操作)');
  }

  async getDeviceCapabilities(): Promise<{
    supportsMetal: boolean;
    supportsNeuralEngine: boolean;
    totalMemoryMB: number;
    availableMemoryMB: number;
    recommendedModelSize: string;
  }> {
    // Web 環境回傳模擬資訊
    const mem = (navigator as any).deviceMemory || 4; // GB
    return {
      supportsMetal: false,
      supportsNeuralEngine: false,
      totalMemoryMB: mem * 1024,
      availableMemoryMB: mem * 1024 * 0.5,
      recommendedModelSize: mem >= 8 ? 'large-v3-turbo' : 'small'
    };
  }

  async addListener(
    eventName: 'transcriptionProgress' | 'transcriptionComplete' | 'transcriptionError',
    listener: (data: any) => void
  ): Promise<{ remove: () => void }> {
    if (!this.progressListeners.has(eventName)) {
      this.progressListeners.set(eventName, listener);
    }
    return {
      remove: () => this.progressListeners.delete(eventName)
    };
  }

  async removeAllListeners(): Promise<void> {
    this.progressListeners.clear();
    this.downloadListeners.clear();
  }
}