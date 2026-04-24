import http from 'node:http';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Dev: Vite on :5173, FastAPI on :8000. The proxy lets fetch('/api/v1/...')
// from the browser go to the backend without CORS gymnastics.
// Prod: FastAPI serves web/dist/ on :8000 as a single-origin deploy — proxy
// is irrelevant there.

// Bounded HTTP agent for the /api proxy. Node's default Agent has
// `maxSockets: Infinity` + `keepAlive: true`, so under React's bursts of
// parallel fetches Vite opens dozens of upstream connections and never
// closes them. uvicorn ended up holding 150+ ESTABLISHED sockets, then
// wedging on internal state. Capping sockets + short keep-alive TTL keeps
// the count flat.
const apiAgent = new http.Agent({
  keepAlive: true,
  keepAliveMsecs: 1_000,
  maxSockets: 16,
  maxFreeSockets: 4,
});

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        agent: apiAgent,
      },
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
