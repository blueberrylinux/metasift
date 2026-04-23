/**
 * Phase 1 dashboard — the first real vertical slice.
 *
 * Renders the composite-score donut + the four sub-metric tiles, wired to
 * TanStack Query against `/api/v1/analysis/composite`. The Refresh button
 * fires `POST /api/v1/analysis/refresh` and invalidates the composite query
 * on completion so the donut re-renders with the new numbers.
 *
 * Empty state: if DuckDB is un-hydrated, the composite endpoint returns
 * `no_metadata_loaded` — we catch that code specifically and render the
 * "click Refresh to hydrate" CTA instead of a generic error.
 *
 * Partial state: after a bare refresh, accuracy + quality come back as 0
 * with `scanned: false`. We render those two tiles as em-dashes to avoid
 * the "0% quality" lie before the deep scan has run (Phase 4).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { MetricCard } from '../components/MetricCard';
import { ScoreRing } from '../components/ScoreRing';
import { Sidebar } from '../components/Sidebar';
import { ApiError, getComposite, postRefresh } from '../lib/api';

export function Dashboard() {
  const qc = useQueryClient();
  const composite = useQuery({
    queryKey: ['composite'],
    queryFn: getComposite,
    retry: (failureCount, error) => {
      // Don't retry the empty-catalog case — it's an expected state, not a flake.
      if (error instanceof ApiError && error.code === 'no_metadata_loaded') return false;
      return failureCount < 2;
    },
  });

  const refresh = useMutation({
    mutationFn: postRefresh,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['composite'] });
      qc.invalidateQueries({ queryKey: ['coverage'] });
    },
  });

  const notHydrated =
    composite.error instanceof ApiError && composite.error.code === 'no_metadata_loaded';

  return (
    <div className="min-h-screen bg-ink-bg text-ink-text bg-hero-glow relative">
      <div className="absolute inset-0 bg-grid-bg bg-grid-48 opacity-40 pointer-events-none" />
      <div className="relative flex">
        <Sidebar activeKey="dashboard" />
        <main className="flex-1 px-10 pt-10 pb-20">
          <header className="flex items-center justify-between mb-10">
            <div>
              <div className="text-xs uppercase tracking-widest text-accent-bright font-semibold">
                MetaSift · Phase 1
              </div>
              <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
            </div>
            <RefreshButton
              pending={refresh.isPending}
              runId={refresh.data?.run_id}
              durationMs={refresh.data?.duration_ms}
              error={refresh.error}
              onClick={() => refresh.mutate()}
            />
          </header>

          {notHydrated ? (
            <EmptyState onRefresh={() => refresh.mutate()} pending={refresh.isPending} />
          ) : composite.isLoading ? (
            <LoadingState />
          ) : composite.error ? (
            <ErrorState error={composite.error} />
          ) : composite.data ? (
            <Content data={composite.data} />
          ) : null}
        </main>
      </div>
    </div>
  );
}

function RefreshButton({
  pending,
  runId,
  durationMs,
  error,
  onClick,
}: {
  pending: boolean;
  runId?: number;
  durationMs?: number;
  error: unknown;
  onClick: () => void;
}) {
  return (
    <div className="flex flex-col items-end gap-1">
      <button
        onClick={onClick}
        disabled={pending}
        className={
          'px-4 py-2 rounded-md text-sm font-mono transition-colors ' +
          (pending
            ? 'bg-accent/20 text-accent-soft border border-accent/30 cursor-wait'
            : 'bg-accent/30 hover:bg-accent/40 text-accent-bright border border-accent/40')
        }
      >
        {pending ? 'Refreshing…' : 'Refresh metadata'}
      </button>
      {error instanceof ApiError ? (
        <span className="text-error-soft text-mini font-mono">{error.message}</span>
      ) : runId ? (
        <span className="text-ink-dim text-mini font-mono">
          run #{runId} · {(durationMs ?? 0) / 1000}s
        </span>
      ) : null}
    </div>
  );
}

function Content({
  data,
}: {
  data: {
    composite: number;
    coverage: number;
    accuracy: number;
    consistency: number;
    quality: number;
    scanned: boolean;
  };
}) {
  return (
    <>
      <div className="flex flex-col items-center mb-10 relative">
        <ScoreRing value={data.composite} size={240} />
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          label="Coverage"
          value={data.coverage}
          hint="% of tables with a description"
        />
        <MetricCard
          label="Accuracy"
          value={data.accuracy}
          pending={!data.scanned}
          hint="% of descriptions that match the column"
        />
        <MetricCard
          label="Consistency"
          value={data.consistency}
          hint="% of columns without tag conflicts"
        />
        <MetricCard
          label="Quality"
          value={data.quality}
          pending={!data.scanned}
          hint="Mean description score (normalized 0-100)"
        />
      </div>
      {!data.scanned && (
        <p className="mt-8 text-ink-dim text-sm">
          Deep scan hasn't run yet — accuracy and quality will populate after the
          first scan (Phase 4).
        </p>
      )}
    </>
  );
}

function EmptyState({ onRefresh, pending }: { onRefresh: () => void; pending: boolean }) {
  return (
    <div className="rounded-xl border border-ink-border bg-ink-panel/50 p-10 flex flex-col items-center gap-4">
      <div className="w-12 h-12 rounded-xl bg-accent-glow border border-accent/30 flex items-center justify-center">
        <span className="font-bold text-accent-soft text-2xl">⟳</span>
      </div>
      <div className="text-center">
        <h2 className="text-lg font-bold">Catalog not loaded yet</h2>
        <p className="text-ink-soft text-sm mt-1 max-w-md">
          Click Refresh to pull metadata from OpenMetadata. Takes ~30s–2min on
          first run; DuckDB is in-memory and rebuilds from scratch each time.
        </p>
      </div>
      <button
        onClick={onRefresh}
        disabled={pending}
        className={
          'px-5 py-2.5 rounded-md text-sm font-mono transition-colors ' +
          (pending
            ? 'bg-accent/20 text-accent-soft border border-accent/30 cursor-wait'
            : 'bg-accent/30 hover:bg-accent/40 text-accent-bright border border-accent/40')
        }
      >
        {pending ? 'Refreshing…' : 'Refresh metadata'}
      </button>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="rounded-xl border border-ink-border bg-ink-panel/50 p-10 text-center text-ink-soft">
      Loading composite score…
    </div>
  );
}

function ErrorState({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : String(error);
  const code = error instanceof ApiError ? error.code : 'unknown';
  return (
    <div className="rounded-xl border border-error/30 bg-error/5 p-6 font-mono text-sm">
      <div className="text-error-soft mb-1">Couldn't load composite score</div>
      <div className="text-ink-soft">
        {code}: {message}
      </div>
    </div>
  );
}
