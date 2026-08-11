import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Vite 配置。dev server 代理 /analyze* 到 FastAPI（默认 http://localhost:8000），
// 生产构建为纯静态资源（由 FastAPI 同源托管或独立 nginx）。
//
// 真后端可经 VITE_API_BASE 指向其他地址；缺省走同源 + dev 代理。
const apiTarget = process.env.VITE_API_BASE ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      // 仅在 dev 下代理真后端；/analyze 与 /analyze/stream 都覆盖。
      '/analyze': {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    // Element Plus + Leaflet 体积可观，给个宽裕警告阈值。
    chunkSizeWarningLimit: 900,
  },
})
