/**
 * Executive report screen — Phase 3 slice 5.
 *
 * Fetches the generated markdown from /api/v1/report and renders it with
 * react-markdown + remark-gfm (for tables). A Download button ships the
 * same markdown as a `.md` file.
 *
 * `Markdown` component is lazy-loaded so the react-markdown chunk doesn't
 * enter the main bundle for users who never visit /report.
 */

import { useQuery } from '@tanstack/react-query';
import { lazy, Suspense } from 'react';
import { Link } from 'react-router-dom';

import { Sidebar } from '../components/Sidebar';
import { ApiError, getReport } from '../lib/api';

const Markdown = lazy(() => import('../components/ReportMarkdown'));

export function Report() {
  const q = useQuery({
    queryKey: ['report'],
    queryFn: getReport,
    // Report pulls from every DuckDB surface — refetch on each visit rather
    // than trust the 60 s default. Cheap to regenerate (all in-memory SQL).
    staleTime: 0,
  });

  const download = () => {
    if (!q.data) return;
    // Compact timestamp stem: ISO YYYY-MM-DDTHH:MM:SS → YYYYMMDDHHMM (12 chars).
    const ts = q.data.generated_at.slice(0, 16).replace(/[-:T]/g, '');
    const filename = `metasift-report-${ts}.md`;
    const blob = new Blob([q.data.markdown], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="min-h-screen bg-ink-bg text-ink-text relative flex">
      <Sidebar activeKey="report" />
      <main className="flex-1 px-10 pt-10 pb-20 max-w-4xl">
        <header className="flex items-start justify-between mb-6 gap-4">
          <div>
            <div className="text-xs uppercase tracking-widest text-accent-bright font-semibold">
              MetaSift · Phase 3
            </div>
            <h1 className="text-2xl font-bold tracking-tight">Executive report</h1>
            <p className="text-ink-soft text-sm mt-1 max-w-2xl">
              Stakeholder-ready markdown summary — composite score, coverage, ownership, blast
              radius, quality, governance, and data-quality findings. Sections skip themselves
              when the relevant scan hasn't run.
            </p>
            {q.data && (
              <p className="text-xs font-mono text-ink-dim mt-2">
                Generated {new Date(q.data.generated_at).toLocaleString()}
              </p>
            )}
          </div>
          <div className="flex gap-2 shrink-0">
            <button
              onClick={() => q.refetch()}
              disabled={q.isFetching}
              className={
                'px-3 py-1.5 rounded-md text-xs font-mono border transition-colors ' +
                (q.isFetching
                  ? 'bg-ink-panel/40 text-ink-dim border-ink-border cursor-wait'
                  : 'bg-ink-panel/40 text-ink-soft border-ink-border hover:text-ink-text')
              }
            >
              {q.isFetching ? 'Refreshing…' : 'Regenerate'}
            </button>
            <button
              onClick={download}
              disabled={!q.data}
              className={
                'px-3 py-1.5 rounded-md text-xs font-mono border transition-colors ' +
                (q.data
                  ? 'bg-accent/30 hover:bg-accent/40 text-accent-bright border-accent/40'
                  : 'bg-accent/10 text-accent-soft/60 border-accent/20 cursor-not-allowed')
              }
            >
              📄 Download .md
            </button>
          </div>
        </header>

        {q.isLoading ? (
          <Placeholder>Generating report…</Placeholder>
        ) : q.error instanceof ApiError && q.error.code === 'no_metadata_loaded' ? (
          <Placeholder>
            No metadata loaded yet. Hit <strong>Refresh metadata</strong> on the{' '}
            <Link to="/" className="underline text-accent-soft">
              dashboard
            </Link>{' '}
            first.
          </Placeholder>
        ) : q.error ? (
          <Placeholder error>
            Couldn't generate the report: {(q.error as Error).message}
          </Placeholder>
        ) : q.data ? (
          <Suspense fallback={<Placeholder>Rendering markdown…</Placeholder>}>
            <Markdown source={q.data.markdown} />
          </Suspense>
        ) : null}
      </main>
    </div>
  );
}

function Placeholder({ children, error }: { children: React.ReactNode; error?: boolean }) {
  return (
    <div
      className={
        'rounded-xl border px-6 py-8 text-sm ' +
        (error
          ? 'border-error/30 bg-error/5 text-error-soft font-mono'
          : 'border-ink-border bg-ink-panel/40 text-ink-soft')
      }
    >
      {children}
    </div>
  );
}
