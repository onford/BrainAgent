import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const proxyTarget = env.VITE_PROXY_TARGET ?? 'http://localhost:8000'
  return {
    plugins: [vue()],
    test: {
      environment: 'jsdom',
    },
    server: {
      port: Number(env.FRONTEND_PORT ?? 5173),
      proxy: {
        '/api': proxyTarget,
        '/health': proxyTarget,
      },
    },
  }
})
