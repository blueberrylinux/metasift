/**
 * Data sources screen — renders everything registered under
 * OpenMetadata's /services/* endpoints, grouped by kind.
 *
 * Data comes from GET /analysis/data-sources (backed by
 * `analysis.service_coverage()`), the same surface the `list_services`
 * agent tool hits. Table counts are meaningful only for database
 * services — dashboard/messaging/pipeline services don't produce tables
 * and always show 0.
 */

import { useQuery } from '@tanstack/react-query';

import { AppLayout } from '../components/AppLayout';
import { EmptyState } from '../components/EmptyState';
import { PageHeader } from '../components/PageHeader';
import { Skeleton } from '../components/Skeleton';
import { ApiError, type DataSourceRow, getDataSources } from '../lib/api';

const KIND_ORDER = ['database', 'dashboard', 'messaging', 'pipeline', 'other'] as const;
type Kind = (typeof KIND_ORDER)[number];

const KIND_LABELS: Record<Kind, { label: string; blurb: string }> = {
  database: {
    label: 'Databases',
    blurb: 'SQL stores ingested into the catalog — the source of every table you browse.',
  },
  dashboard: {
    label: 'Dashboards',
    blurb: 'BI tools whose reports and charts are catalogued alongside the tables that feed them.',
  },
  messaging: {
    label: 'Messaging',
    blurb: 'Streaming systems (Kafka et al.) exposed as topics in the catalog.',
  },
  pipeline: {
    label: 'Pipelines',
    blurb: 'Orchestrators (Airflow, dbt) whose DAGs/models show up as cataloged entities.',
  },
  other: {
    label: 'Other',
    blurb: 'Services whose kind the UI doesn\'t have a bucket for yet — check server logs.',
  },
};

export function DataSources() {
  const q = useQuery({
    queryKey: ['data-sources'],
    queryFn: getDataSources,
    retry: false,
    staleTime: 60_000,
  });

  const rows = q.data?.rows ?? [];
  const grouped = groupByKind(rows);
  const totalTables = rows.reduce((acc, r) => acc + r.tables, 0);

  const chips =
    q.data && rows.length > 0
      ? [
          { label: `${rows.length} service${rows.length === 1 ? '' : 's'}`, tone: 'emerald' as const },
          { label: `${totalTables} tables ingested`, tone: 'slate' as const },
        ]
      : [];

  const actions = (
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
      {q.isFetching ? 'Refreshing…' : 'Reload'}
    </button>
  );

  return (
    <AppLayout activeKey="sources">
      <PageHeader
        title="Data sources"
        subtitle="Every service connected to OpenMetadata, grouped by kind. Table counts come from OpenMetadata's table inventory — only database services contribute."
        chips={chips}
        rightButtons={actions}
      />

      <div className="flex-1 px-4 md:px-6 py-6 max-w-5xl">
        {q.isLoading ? (
          <SourcesSkeleton />
        ) : q.error instanceof ApiError && q.error.code === 'no_metadata_loaded' ? (
          <EmptyState
            icon="↻"
            title="No metadata loaded yet"
            body="Data sources populate on refresh — MetaSift pulls them from OpenMetadata's /services/* endpoints."
            hint="Hit Refresh metadata in the sidebar to pull services from OpenMetadata."
          />
        ) : q.error ? (
          <EmptyState
            variant="error"
            icon="⚠"
            title="Couldn't load data sources"
            body={(q.error as Error).message}
          />
        ) : rows.length === 0 ? (
          <EmptyState
            icon="·"
            title="No services registered"
            body="OpenMetadata has no database / dashboard / messaging / pipeline services configured. Run the seed script or add a connector in OpenMetadata to see them here."
          />
        ) : (
          <div className="space-y-6">
            {KIND_ORDER.filter((k) => grouped[k]?.length).map((kind) => (
              <KindSection key={kind} kind={kind} rows={grouped[kind]!} />
            ))}
          </div>
        )}
      </div>
    </AppLayout>
  );
}

function KindSection({ kind, rows }: { kind: Kind; rows: DataSourceRow[] }) {
  const meta = KIND_LABELS[kind];
  return (
    <section>
      <div className="flex items-baseline justify-between mb-2">
        <h2 className="text-[13px] font-semibold text-white tracking-tight">
          {meta.label} <span className="text-slate-500 font-mono text-[11px] ml-1">{rows.length}</span>
        </h2>
      </div>
      <p className="text-[11px] text-slate-500 mb-3 max-w-2xl">{meta.blurb}</p>
      <div className="rounded-lg border border-slate-800 overflow-hidden">
        <table className="w-full text-[12px]">
          <thead className="bg-slate-900/60 text-slate-400">
            <tr>
              <th className="text-left font-medium px-3 py-2">Service</th>
              <th className="text-left font-medium px-3 py-2">Connector</th>
              <th className="text-right font-medium px-3 py-2">Tables</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.service} className="border-t border-slate-800/80 hover:bg-slate-900/30">
                <td className="px-3 py-2 text-slate-200 font-medium">{r.service}</td>
                <td className="px-3 py-2 text-slate-400 font-mono text-[11px]">
                  {r.type ?? '—'}
                </td>
                <td className="px-3 py-2 text-right font-mono text-slate-300">{r.tables}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function groupByKind(rows: DataSourceRow[]): Partial<Record<Kind, DataSourceRow[]>> {
  const out: Partial<Record<Kind, DataSourceRow[]>> = {};
  for (const r of rows) {
    const known = KIND_ORDER.includes(r.kind as Kind);
    if (!known) {
      // Surface the unrecognized kind so a new OM service category (or a
      // typo on the backend) doesn't silently disappear into the Databases
      // bucket. Warns once per unique kind to avoid console spam.
      console.warn(
        `[DataSources] unknown service kind "${r.kind}" for ${r.service} — grouping under "Other".`,
      );
    }
    const k: Kind = known ? (r.kind as Kind) : 'other';
    (out[k] ||= []).push(r);
  }
  return out;
}

function SourcesSkeleton() {
  return (
    <div className="space-y-6">
      {Array.from({ length: 2 }).map((_, s) => (
        <div key={s}>
          <Skeleton className="h-[14px] w-24 mb-2" />
          <Skeleton className="h-[11px] w-64 mb-3" />
          <div className="rounded-lg border border-slate-800 overflow-hidden">
            {Array.from({ length: 2 }).map((_, i) => (
              <div key={i} className="border-t border-slate-800/80 px-3 py-2 flex items-center gap-4">
                <Skeleton className="h-[12px] w-32" />
                <Skeleton className="h-[12px] w-20" />
                <div className="flex-1" />
                <Skeleton className="h-[12px] w-8" />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
