import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { Toaster } from 'sonner';

import { App } from './App';
import { ByoKeyTrapProvider } from './components/ByoKeyModal';
import './styles/index.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Composite / coverage are aggregate reads — stale for 60s is fine.
      // Refresh mutation invalidates on success so explicit user actions
      // bypass this anyway.
      staleTime: 60_000,
      refetchOnWindowFocus: false,
    },
  },
});

const container = document.getElementById('root');
if (!container) throw new Error('#root element missing from index.html');

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ByoKeyTrapProvider>
          <App />
        </ByoKeyTrapProvider>
        <Toaster
          position="bottom-right"
          theme="dark"
          richColors
          closeButton
          toastOptions={{
            classNames: {
              toast:
                'border border-slate-800 bg-slate-950/95 text-slate-200 backdrop-blur-sm',
              title: 'text-[13px] font-medium',
              description: 'text-[11px] text-slate-400',
            },
          }}
        />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
