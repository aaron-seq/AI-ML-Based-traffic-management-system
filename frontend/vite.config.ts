import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

/**
 * The dev server proxies `/api`, `/ws` and `/static` to the backend so the app
 * runs same-origin in development. That keeps CORS out of the local loop and
 * means the production build works unchanged behind a reverse proxy.
 */
const backendTarget = process.env.VITE_BACKEND_URL ?? 'http://localhost:8000';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    // Mirrors the `@/*` path mapping in tsconfig.json.
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 3000,
    host: true,
    proxy: {
      '/api': { target: backendTarget, changeOrigin: true },
      '/health': { target: backendTarget, changeOrigin: true },
      '/metrics': { target: backendTarget, changeOrigin: true },
      '/static': { target: backendTarget, changeOrigin: true },
      '/ws': { target: backendTarget, ws: true, changeOrigin: true },
    },
  },
  preview: { port: 3000, host: true },
  build: {
    outDir: 'dist',
    sourcemap: true,
    rollupOptions: {
      output: {
        // Charting is heavy and only needed on the analytics screens; splitting
        // it keeps the initial control-room load small.
        manualChunks: (id: string) => (id.includes('recharts') ? 'charts' : undefined),
      },
    },
  },
});
