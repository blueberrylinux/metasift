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
    // Plotly.js is ~3 MB gzipped — chunk it out so the /viz route lazy-loads
    // it instead of dragging it into the main bundle that every screen pays for.
    rollupOptions: {
      output: {
        manualChunks: {
          plotly: ['plotly.js-dist-min', 'react-plotly.js/factory'],
        },
      },
    },
    chunkSizeWarningLimit: 4000,
  },
});
