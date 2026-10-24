import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const configuredApiBaseUrl = env.VITE_API_BASE_URL || ''
  const isLoopbackApi = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?(?:\/|$)/i.test(
    configuredApiBaseUrl,
  )
  const publicApiBaseUrl = command === 'build' && isLoopbackApi
    ? ''
    : configuredApiBaseUrl

  if (command === 'build' && isLoopbackApi) {
    console.warn(
      'Ignoring a localhost VITE_API_BASE_URL for the production build; using same-origin /api instead.',
    )
  }

  return {
    plugins: [react()],
    define: {
      'import.meta.env.VITE_API_BASE_URL': JSON.stringify(publicApiBaseUrl),
    },
    server: {
      host: '127.0.0.1',
      port: 5173,
      proxy: {
        '/api': {
          target: env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:5000',
          changeOrigin: true,
        },
      },
    },
  }
})
