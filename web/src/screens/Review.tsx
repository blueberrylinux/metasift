/**
 * Review queue screen — ports Streamlit's `_render_review_panel`.
 *
 * The filter row mirrors the Streamlit `All (N) / Descriptions (M) /
 * PII tags (K)` radio — but we always fetch ALL items and filter client-
 * side so the counts render accurately even when a filter is active.
 */

import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import { ReviewCard } from '../components/ReviewCard';
import { Sidebar } from '../components/Sidebar';
import { ApiError, listReview, type ReviewItem, type ReviewKind } from '../lib/api';

type FilterKey = 'all' | ReviewKind;

export function Review() {
  const [filter, setFilter] = useState<FilterKey>('all');
  const q = useQuery({
    queryKey: ['review'],
    queryFn: () => listReview(),
  });

  const counts = useMemo(() => countByKind(q.data?.rows ?? []), [q.data]);
  const visible = useMemo(
    () =>
      filter === 'all' ? (q.data?.rows ?? []) : (q.data?.rows ?? []).filter((r) => r.kind === filter),
    [filter, q.data],
  );

  return (
    <div className="min-h-screen bg-ink-bg text-ink-text relative flex">
      <Sidebar activeKey="review" />
      <main className="flex-1 px-10 pt-10 pb-20 max-w-5xl">
        <header className="flex items-center justify-between mb-6">
          <div>
            <div className="text-xs uppercase tracking-widest text-accent-bright font-semibold">
              MetaSift · Phase 3
            </div>
            <h1 className="text-2xl font-bold tracking-tight">Review queue</h1>
            <p className="text-ink-soft text-sm mt-1 max-w-2xl">
              Pending suggestions from the cleaning and PII engines. Accept applies the change
              via REST PATCH; Edit lets you tweak first; Reject dismisses it.
            </p>
          </div>
          <Link to="/chat" className="text-xs uppercase tracking-widest text-ink-dim hover:text-accent-soft">
            Stew →
          </Link>
        </header>

        {q.isLoading ? (
          <Placeholder>Loading queue…</Placeholder>
        ) : q.error instanceof ApiError && q.error.code === 'no_metadata_loaded' ? (
          <Placeholder>
            No metadata loaded yet. Hit <Link to="/" className="text-accent-soft underline">Refresh metadata</Link> on
            the dashboard first.
          </Placeholder>
        ) : q.error ? (
          <Placeholder>
            Couldn't load queue: {(q.error as Error).message}
          </Placeholder>
        ) : (q.data?.rows.length ?? 0) === 0 ? (
          <Placeholder>
            No pending suggestions. Run the deep scan or PII scan from the sidebar to populate
            the queue — coming in slice 2.
          </Placeholder>
        ) : (
          <>
            <FilterRow filter={filter} onChange={setFilter} counts={counts} />
            <div className="flex flex-col gap-4">
              {visible.map((item) => (
                <ReviewCard key={item.key} item={item} />
              ))}
              {visible.length === 0 && (
                <Placeholder>No items match this filter.</Placeholder>
              )}
            </div>
          </>
        )}
      </main>
    </div>
  );
}

function FilterRow({
  filter,
  onChange,
  counts,
}: {
  filter: FilterKey;
  onChange: (f: FilterKey) => void;
  counts: { all: number; description: number; pii_tag: number };
}) {
  const opts: { key: FilterKey; label: string; n: number }[] = [
    { key: 'all', label: 'All', n: counts.all },
    { key: 'description', label: 'Descriptions', n: counts.description },
    { key: 'pii_tag', label: 'PII tags', n: counts.pii_tag },
  ];
  return (
    <div className="flex gap-1 mb-6">
      {opts.map((o) => {
        const active = filter === o.key;
        return (
          <button
            key={o.key}
            onClick={() => onChange(o.key)}
            className={
              'px-3 py-1.5 rounded-md text-xs font-mono border transition-colors ' +
              (active
                ? 'bg-accent/30 text-accent-bright border-accent/40'
                : 'bg-ink-panel/40 text-ink-soft border-ink-border hover:text-ink-text')
            }
          >
            {o.label} ({o.n})
          </button>
        );
      })}
    </div>
  );
}

function countByKind(items: ReviewItem[]): { all: number; description: number; pii_tag: number } {
  let desc = 0;
  let pii = 0;
  for (const i of items) {
    if (i.kind === 'description') desc++;
    else pii++;
  }
  return { all: items.length, description: desc, pii_tag: pii };
}

function Placeholder({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-ink-border bg-ink-panel/40 px-6 py-8 text-sm text-ink-soft">
      {children}
    </div>
  );
}
