import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 构建产物输出到 Flask 的 app/web 目录，由 Flask 直接托管；
// 开发模式下 5173 端口把 /api 代理到 Flask 5000。
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: '../app/web',
    emptyOutDir: true,
  },
})
