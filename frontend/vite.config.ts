import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'
import { createMockApi } from './mocks/payment-api.ts'

const useRealBackend = process.env.VITE_USE_REAL_BACKEND === 'true' || process.env.PAUSEGUARD_MODE === 'backend'
const backendTarget = process.env.PAUSEGUARD_BACKEND_URL || 'http://127.0.0.1:8000'

export default defineConfig({
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    proxy: useRealBackend
      ? {
          '/api/v2': {
            target: backendTarget,
            changeOrigin: true,
            ws: true,
          },
        }
      : undefined,
  },
  preview: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
  },
  plugins: [
    react(),
    tailwindcss(),
    {
      name: 'pauseguard-local-payment-fixture',
      configureServer(server) {
        if (!useRealBackend) {
          server.middlewares.use(createMockApi())
        }
      },
      configurePreviewServer(server) {
        if (!useRealBackend) {
          server.middlewares.use(createMockApi())
        }
      },
    },
  ],
})
