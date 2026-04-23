import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Dev: Vite on :5173, FastAPI on :8000. The proxy lets fetch('/api/v1/...')
// from the browser go to the backend without CORS gymnastics.
// Prod: FastAPI serves web/dist/ on :8000 as a single-origin deploy — proxy
// is irrelevant there.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
    // Keep the Plotly chunk separate — loaded lazily by the viz route only.
    rollupOptions: {
      output: {
        manualChunks: {
          // populated in Phase 5 when we add react-plotly.js
        },
      },
    },
  },
});
