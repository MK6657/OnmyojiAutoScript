import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 开发模式把 /api 与 WebSocket 转发到 Bridge；
// 桌面构建通过 .env.desktop 固定到 127.0.0.1:22367。
const bridgeTarget = process.env.OAS_BRIDGE_URL || 'http://127.0.0.1:22367'

export default defineConfig(({ mode }) => ({
  base: mode === 'desktop' ? './' : '/',
  plugins: [react()],
  build: { outDir: 'dist', emptyOutDir: true, chunkSizeWarningLimit: 900 },
  server: {
    host: '127.0.0.1',
    proxy: { '/api': { target: bridgeTarget, changeOrigin: true, ws: true } },
  },
  preview: {
    host: '127.0.0.1',
    proxy: { '/api': { target: bridgeTarget, changeOrigin: true, ws: true } },
  },
}))
