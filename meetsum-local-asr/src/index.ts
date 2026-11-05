import { registerPlugin, WebPlugin } from '@capacitor/core';
import type { LocalASRPlugin } from './definitions';
import { MeetsumLocalASRWeb } from './web';

/**
 * MeetsumLocalASR 插件
 *
 * 使用方式：
 * ```typescript
 * import { MeetsumLocalASR } from 'meetsum-local-asr';
 *
 * // 檢查模型
 * const { available } = await MeetsumLocalASR.isModelAvailable({ modelSize: 'large-v3-turbo' });
 *
 * // 下載模型
 * await MeetsumLocalASR.downloadModel({ modelSize: 'large-v3-turbo', quantization: 'q4_k' });
 *
 * // 開始轉錄
 * const { jobId } = await MeetsumLocalASR.transcribe({
 *   audioPath: 'file:///path/to/audio.m4a',
 *   language: 'zh',
 *   enableDiarization: true,
 *   modelSize: 'large-v3-turbo'
 * });
 *
 * // 監聽進度
 * const listener = await MeetsumLocalASR.addListener('transcriptionProgress', (progress) => {
 *   console.log('進度:', progress.progress, '%');
 * });
 *
 * // 輪詢結果
 * const status = await MeetsumLocalASR.getTranscriptionStatus({ jobId });
 * ```
 */
const MeetsumLocalASR = registerPlugin<LocalASRPlugin>('MeetsumLocalASR', {
  web: () => new MeetsumLocalASRWeb()
});

export { MeetsumLocalASR };
export type {
  TranscriptionOptions,
  TranscriptionSegment,
  TranscriptionResult,
  ModelInfo,
  DownloadProgress,
  LocalASRPlugin
} from './definitions';