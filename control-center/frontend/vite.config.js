import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const bridgeTarget = process.env.OAS_BRIDGE_URL || 'http://127.0.0.1:22367'

export default defineConfig(({ mode }) => ({
  base: mode === 'desktop' ? './' : '/',
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    proxy: {
      '/api': { target: bridgeTarget, changeOrigin: true, ws: true },
    },
  },
  preview: {
    host: '127.0.0.1',
    proxy: {
      '/api': { target: bridgeTarget, changeOrigin: true, ws: true },
    },
  },
}))
