import { defineConfig, loadEnv, type ProxyOptions } from 'vite'
import react from '@vitejs/plugin-react'

const withProxies = (apiTarget: string): Record<string, ProxyOptions> => {
  const routes = ['/api', '/auth', '/tasks']
  return routes.reduce((acc, route) => {
    acc[route] = {
      target: apiTarget,
      changeOrigin: true,
      secure: false,
    }
    return acc
  }, {} as Record<string, ProxyOptions>)
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiTarget =
    env.VITE_API_PROXY_TARGET || env.VITE_API_BASE_URL || 'http://localhost:5000'

  return {
    plugins: [react()],
    server: {
      host: '0.0.0.0',
      port: Number(env.VITE_DEV_SERVER_PORT || 5173),
      proxy: withProxies(apiTarget),
    },
    preview: {
      port: Number(env.VITE_PREVIEW_PORT || 4173),
    },
  }
})
