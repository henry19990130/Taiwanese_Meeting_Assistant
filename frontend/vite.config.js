import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [vue()],
    root: resolve(__dirname),
    build: {
      outDir: 'dist',
      sourcemap: false,
      minify: 'esbuild',
      emptyOutDir: true,
      rollupOptions: {
        input: { main: resolve(__dirname, 'index.html') },
      },
    },
    define: {
      // 預設為空字串＝同源相對路徑（網頁版由後端提供頁面時可直接用）
      // iOS/PlayCover 建置時以 VITE_API_BASE_URL 指定後端位址
      __API_BASE_URL__: JSON.stringify(env.VITE_API_BASE_URL || ''),
      // Cloudflare Worker 固定入口（雲端模式自動發現 Colab 網址）
      __DISCOVERY_URL__: JSON.stringify(env.VITE_DISCOVERY_URL || ''),
    },
    resolve: {
      extensions: ['.js', '.ts', '.vue', '.json'],
      alias: {
        // 本地 ASR 插件（Breeze-ASR-26 / WhisperKit）
        '@meetsum-local-asr': resolve(__dirname, '../meetsum-local-asr/src/index.ts'),
        // 本地摘要插件（MLX / Bonsai 27B 1-bit）
        '@meetsum-local-llm': resolve(__dirname, '../meetsum-local-llm/src/index.ts'),
      },
    },
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: 'http://localhost:8000',
          changeOrigin: true,
        },
      },
    },
    esbuild: {
      target: 'ES2020',
    },
  }
})