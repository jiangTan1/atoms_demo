import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// 前端构建配置：产物输出到 web/dist（随仓库提交，由 FastAPI 静态托管）。
// 开发态把 /api、/preview、/share 代理到本机后端（127.0.0.1:80），
// 与生产保持同源，登录态 Cookie 正常携带（见 design.md 决策 1）。
export default defineConfig({
  base: '/',
  plugins: [react()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:80',
      '/preview': 'http://127.0.0.1:80',
      '/share': 'http://127.0.0.1:80',
    },
  },
});