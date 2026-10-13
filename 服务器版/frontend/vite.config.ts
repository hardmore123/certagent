import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ command }) => ({
  plugins: [react()],
  // 生产构建使用相对路径：通过外层 Nginx 访问 /certagent/ 时解析为
  // /certagent/assets 与 /certagent/api；直接访问 8123 时解析为 /assets 与 /api。
  // 开发环境保留根路径，继续使用 Vite 的 /api 代理。
  base: command === 'build' ? './' : '/',
  server: {
    port: 8123,
    proxy: {
      '/api': { target: 'http://localhost:8125', changeOrigin: true },
      '/health': { target: 'http://localhost:8125', changeOrigin: true },
    },
  },
}))
