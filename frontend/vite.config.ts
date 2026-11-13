import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'
import { createMockApi } from './mocks/payment-api.ts'

const useRealBackend = process.env.VITE_USE_REAL_BACKEND === 'true' || process.env.PAUSEGUARD_MODE === 'backend'
const backendTarget = process.env.PAUSEGUARD_BACKEND_URL || 'http://127.0.0.1:8000'

export default defineConfig({
  server: {
    // In real-backend mode, bind strictly to loopback (127.0.0.1) to avoid exposing
    // demo authentication endpoints over LAN. Standalone mock mode keeps 0.0.0.0.
    host: useRealBackend ? '127.0.0.1' : '0.0.0.0',
    port: 5173,
    strictPort: true,
    proxy: useRealBackend
      ? {
          '/api/v2': {
            target: backendTarget,
            changeOrigin: true,
            ws: true,
            xfwd: true,
            bypass(req) {
              // Block non-loopback requests targeting demo auth endpoints
              const remoteAddr = req.socket?.remoteAddress
              if (remoteAddr) {
                const isLoopback =
                  remoteAddr === '127.0.0.1' ||
                  remoteAddr === '::1' ||
                  remoteAddr === '::ffff:127.0.0.1'
                if (!isLoopback && req.url?.startsWith('/api/v2/demo/')) {
                  return false
                }
              }
            },
          },
        }
      : undefined,
  },
  preview: {
    host: useRealBackend ? '127.0.0.1' : '0.0.0.0',
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
