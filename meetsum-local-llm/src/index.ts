import { registerPlugin } from '@capacitor/core';
import type { LocalLLMPlugin } from './definitions';
import { MeetsumLocalLLMWeb } from './web';

/**
 * MeetsumLocalLLM：裝置內 MLX 摘要（Bonsai 27B 1-bit）
 *
 * ```ts
 * import { MeetsumLocalLLM } from '@meetsum-local-llm';
 * const res = await MeetsumLocalLLM.summarize({ transcript, language: 'zh' });
 * console.log(res.json);
 * ```
 */
const MeetsumLocalLLM = registerPlugin<LocalLLMPlugin>('MeetsumLocalLLM', {
  web: () => new MeetsumLocalLLMWeb(),
});

export { MeetsumLocalLLM };
export type {
  LLMModelInfo,
  SummarizeOptions,
  SummarizeResult,
  SummarizeJSON,
  ModelProgress,
  LocalLLMPlugin,
} from './definitions';
