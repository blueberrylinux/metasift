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

import { AppLayout } from '../components/AppLayout';
import { PageHeader } from '../components/PageHeader';
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

  const actions = (
    <div className="flex gap-2">
      <button
        onClick={() => q.refetch()}
        disabled={q.isFetching}
        className={
          'text-[11px] px-2.5 py-1 rounded-md border transition ' +
          (q.isFetching
            ? 'text-slate-500 border-slate-800 bg-slate-900/40 cursor-wait'
            : 'text-slate-300 border-slate-800 bg-slate-900/40 hover:text-white hover:bg-slate-800/60')
        }
      >
        {q.isFetching ? 'Refreshing…' : 'Regenerate'}
      </button>
      <button
        onClick={download}
        disabled={!q.data}
        className={
          'text-[11px] px-2.5 py-1 rounded-md border transition ' +
          (q.data
            ? 'text-emerald-300 border-emerald-500/20 bg-emerald-500/5 hover:bg-emerald-500/10'
            : 'text-emerald-300/50 border-emerald-500/10 bg-emerald-500/5 cursor-not-allowed')
        }
      >
        📄 Download .md
      </button>
    </div>
  );

  return (
    <AppLayout activeKey="report">
      <PageHeader
        title="Executive report"
        subtitle="Stakeholder-ready markdown summary — composite score, coverage, ownership, blast radius, quality, governance, and data-quality findings. Sections skip themselves when the relevant scan hasn't run."
        chips={
          q.data
            ? [{ label: `Generated ${new Date(q.data.generated_at).toLocaleString()}`, tone: 'slate' }]
            : []
        }
        rightButtons={actions}
      />

      <div className="flex-1 px-6 py-6 max-w-4xl">
        {q.isLoading ? (
          <Placeholder>Generating report…</Placeholder>
        ) : q.error instanceof ApiError && q.error.code === 'no_metadata_loaded' ? (
          <Placeholder>
            No metadata loaded yet. Hit <strong>Refresh metadata</strong> from the sidebar's
            Quick actions, or run{' '}
            <Link to="/chat" className="underline text-emerald-300">
              Stew
            </Link>
            ' auto-refresh.
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
      </div>
    </AppLayout>
  );
}

function Placeholder({ children, error }: { children: React.ReactNode; error?: boolean }) {
  return (
    <div
      className={
        'rounded-xl border px-6 py-8 text-sm ' +
        (error
          ? 'border-red-500/30 bg-red-500/5 text-red-300 font-mono'
          : 'border-slate-800 bg-slate-900/40 text-slate-400')
      }
    >
      {children}
    </div>
  );
}
