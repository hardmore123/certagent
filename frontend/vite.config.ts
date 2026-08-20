import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 8123,
    proxy: {
      '/api': { target: 'http://localhost:8125', changeOrigin: true },
      '/health': { target: 'http://localhost:8125', changeOrigin: true },
    },
  },
})
