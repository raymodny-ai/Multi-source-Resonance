import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Vite proxy points to the Python FastAPI/Uvicorn backend.
// Backend default port: 8524 (see api_server.py / config/settings.py).
// Override via env vars if the backend is exposed elsewhere.
const API_TARGET = process.env.VITE_API_TARGET || 'http://localhost:8524'
const WS_TARGET = process.env.VITE_WS_TARGET || 'ws://localhost:8524'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
      },
      '/ws': {
        target: WS_TARGET,
        ws: true,
      },
    },
  },
})