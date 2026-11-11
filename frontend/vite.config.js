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
        external: ['../../meetsum-local-asr/src/index.ts'],
      },
    },
    define: {
      __API_BASE_URL__: JSON.stringify(env.VITE_API_BASE_URL || 'http://localhost:8000'),
    },
    resolve: {
      extensions: ['.js', '.ts', '.vue', '.json'],
      alias: {
        '@/meetsum-local-asr': resolve(__dirname, '../meetsum-local-asr/src'),
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