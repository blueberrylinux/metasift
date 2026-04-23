/**
 * Phase 0 placeholder — just proves the React + Vite + Tailwind + FastAPI
 * wiring works end-to-end. Hitting the app shows a health-check badge that
 * reads from /api/v1/health, confirming the proxy and backend are both alive.
 *
 * Replaced by the real sidebar + router layout in Phase 1.
 */

import { useEffect, useState } from 'react';

import { getHealth, type HealthResponse } from './lib/api';

export function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getHealth()
      .then((h) => {
        if (!cancelled) setHealth(h);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="min-h-screen bg-ink-bg text-ink-text bg-hero-glow">
      <div className="absolute inset-0 bg-grid-bg bg-grid-48 opacity-40 pointer-events-none" />
      <div className="relative max-w-3xl mx-auto px-8 pt-16 pb-20">
        <header className="flex items-center gap-4 mb-8">
          <div className="w-12 h-12 rounded-xl bg-accent-glow border border-accent/30 flex items-center justify-center">
            <span className="font-bold text-accent-soft text-xl">M</span>
          </div>
          <div>
            <div className="text-xs uppercase tracking-widest text-accent-bright font-semibold">
              MetaSift · Phase 0
            </div>
            <h1 className="text-2xl font-bold tracking-tight">Port scaffold alive</h1>
          </div>
        </header>

        <div className="rounded-xl border border-ink-border bg-ink-panel/50 p-6">
          <div className="text-xs uppercase tracking-widest text-accent-bright font-semibold mb-3">
            Health check
          </div>
          {error ? (
            <div className="font-mono text-error-soft">
              Couldn’t reach /api/v1/health — {error}
              <div className="text-ink-dim text-sm mt-2">
                Start the backend: <span className="text-accent-soft">make api</span>
              </div>
            </div>
          ) : !health ? (
            <div className="text-ink-soft">Loading…</div>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              <HealthRow label="API version" value={health.version} ok={true} />
              <HealthRow label="Overall" value={health.ok ? 'up' : 'degraded'} ok={health.ok} />
              <HealthRow label="OpenMetadata" value={health.om ? 'reachable' : 'down'} ok={health.om} />
              <HealthRow label="LLM" value={health.llm ? 'configured' : 'missing key'} ok={health.llm} />
              <HealthRow label="DuckDB" value={health.duck ? 'hydrated' : 'empty'} ok={health.duck} />
              <HealthRow label="SQLite" value={health.sqlite ? 'migrated' : 'error'} ok={health.sqlite} />
            </div>
          )}
        </div>

        <p className="text-xs text-ink-dim mt-6 font-mono">
          Phase 1 replaces this with the real sidebar + composite score dashboard.
        </p>
      </div>
    </div>
  );
}

function HealthRow({ label, value, ok }: { label: string; value: string; ok: boolean }) {
  return (
    <div className="flex items-center justify-between border border-ink-border/50 rounded-md px-3 py-2 bg-ink-bg/40">
      <span className="text-ink-soft text-sm">{label}</span>
      <span className="flex items-center gap-2 font-mono text-xs">
        <span
          className={`w-1.5 h-1.5 rounded-full ${ok ? 'bg-accent' : 'bg-error'} animate-pulse-dot`}
        />
        <span className={ok ? 'text-accent-soft' : 'text-error-soft'}>{value}</span>
      </span>
    </div>
  );
}
