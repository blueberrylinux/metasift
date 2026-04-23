/**
 * Data quality screen — Phase 3 slice 4.
 *
 * Three tabs over the DQ trio:
 *   * Failures       cards with LLM-written summary / likely_cause /
 *                    next_step + a fix_type chip (when the 🧪 Explain scan
 *                    has run).
 *   * Recommendations severity-filtered list of DQ tests that should exist
 *                    (populated by the 💡 Recommend scan).
 *   * Risk           catalog-wide ranking by risk_score with an inline
 *                    impact drilldown for each row.
 *
 * Every empty-state carries the specific CTA — "run this scan from the
 * sidebar" — tied to the right response flag (explanations_loaded /
 * scan_run) so the user never has to guess which button to click.
 */

import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { Sidebar } from '../components/Sidebar';
import {
  ApiError,
  getDQFailures,
  getDQImpact,
  getDQRecommendations,
  getDQRisk,
  type DQFailure,
  type DQImpactResponse,
  type DQRecommendation,
  type DQRiskRow,
  type DQSummaryResponse,
  type FixType,
  type Severity,
} from '../lib/api';

type TabKey = 'failures' | 'recommendations' | 'risk';

export function DQ() {
  const [tab, setTab] = useState<TabKey>('failures');

  return (
    <div className="min-h-screen bg-ink-bg text-ink-text relative flex">
      <Sidebar activeKey="dq" />
      <main className="flex-1 px-10 pt-10 pb-20 max-w-5xl">
        <header className="flex items-center justify-between mb-6">
          <div>
            <div className="text-xs uppercase tracking-widest text-accent-bright font-semibold">
              MetaSift · Phase 3
            </div>
            <h1 className="text-2xl font-bold tracking-tight">Data quality</h1>
            <p className="text-ink-soft text-sm mt-1 max-w-2xl">
              Failing tests explained in plain English, missing-test recommendations ranked by
              severity, and catalog-wide risk ranking by downstream blast radius.
            </p>
          </div>
          <Link to="/viz" className="text-xs uppercase tracking-widest text-ink-dim hover:text-accent-soft">
            Viz →
          </Link>
        </header>

        <TabStrip tab={tab} onChange={setTab} />

        <div className="mt-6">
          {tab === 'failures' && <FailuresPanel />}
          {tab === 'recommendations' && <RecommendationsPanel />}
          {tab === 'risk' && <RiskPanel />}
        </div>
      </main>
    </div>
  );
}

// ── Tab strip ──────────────────────────────────────────────────────────────

function TabStrip({ tab, onChange }: { tab: TabKey; onChange: (t: TabKey) => void }) {
  const tabs: { key: TabKey; label: string; icon: string }[] = [
    { key: 'failures', label: 'Failures', icon: '🧪' },
    { key: 'recommendations', label: 'Recommendations', icon: '💡' },
    { key: 'risk', label: 'Risk', icon: '🎯' },
  ];
  return (
    <div className="flex gap-1 border-b border-ink-border pb-3" role="tablist">
      {tabs.map((t) => {
        const active = t.key === tab;
        return (
          <button
            key={t.key}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(t.key)}
            className={
              'px-3 py-1.5 rounded-md text-xs font-mono border transition-colors ' +
              (active
                ? 'bg-accent/30 text-accent-bright border-accent/40'
                : 'bg-ink-panel/40 text-ink-soft border-ink-border hover:text-ink-text')
            }
          >
            {t.icon} {t.label}
          </button>
        );
      })}
    </div>
  );
}

// ── Summary strip (shared above Failures tab) ─────────────────────────────

function SummaryStrip({ s }: { s: DQSummaryResponse }) {
  const tiles = [
    { label: 'Total', value: s.total, tint: 'text-ink-text' },
    { label: 'Failed', value: s.failed, tint: 'text-error-soft' },
    { label: 'Passed', value: s.passed, tint: 'text-accent-bright' },
    { label: 'Tables with failures', value: s.failing_tables, tint: 'text-ink-text' },
  ];
  return (
    <div className="grid grid-cols-4 gap-3 mb-5">
      {tiles.map((t) => (
        <div
          key={t.label}
          className="rounded-lg border border-ink-border bg-ink-panel/40 px-4 py-3"
        >
          <div className="text-mini font-mono uppercase tracking-wider text-ink-dim">
            {t.label}
          </div>
          <div className={`text-2xl font-semibold ${t.tint}`}>{t.value}</div>
        </div>
      ))}
    </div>
  );
}

// ── Failures panel ────────────────────────────────────────────────────────

function FailuresPanel() {
  const [schema, setSchema] = useState<string>('');
  const q = useQuery({
    queryKey: ['dq', 'failures'],
    queryFn: () => getDQFailures(),
  });

  if (q.isLoading) return <Placeholder>Loading failures…</Placeholder>;
  if (q.error instanceof ApiError && q.error.code === 'no_metadata_loaded') {
    return (
      <Placeholder>
        No metadata loaded yet. Hit <strong>Refresh metadata</strong> on the dashboard first.
      </Placeholder>
    );
  }
  if (q.error) return <Placeholder error>{(q.error as Error).message}</Placeholder>;
  if (!q.data) return null;

  const schemas = uniqueSchemas(q.data.rows);

  return (
    <>
      <SummaryStrip s={q.data.summary} />

      {!q.data.explanations_loaded && (
        <div className="mb-5 rounded-lg border border-accent/30 bg-accent/5 px-4 py-3 text-xs font-mono text-accent-soft">
          Plain-English explanations aren't loaded yet — click <strong>🧪 Explain DQ</strong> in
          the sidebar to enrich every failing test with a summary, likely cause, next step, and
          fix_type chip.
        </div>
      )}

      {schemas.length > 1 && (
        <div className="flex flex-wrap gap-1 mb-4">
          <button
            onClick={() => setSchema('')}
            className={chipCls(schema === '')}
          >
            All ({q.data.rows.length})
          </button>
          {schemas.map((s) => {
            const n = q.data.rows.filter((r) => fqnSchema(r.table_fqn) === s).length;
            return (
              <button key={s} onClick={() => setSchema(s)} className={chipCls(schema === s)}>
                {s} ({n})
              </button>
            );
          })}
        </div>
      )}

      {q.data.rows.length === 0 ? (
        <Placeholder>
          {q.data.summary.total === 0
            ? 'No DQ tests exist on this catalog yet. Seed or ingest some test cases and retry.'
            : 'No failing DQ tests. Everything looks clean.'}
        </Placeholder>
      ) : (
        <div className="flex flex-col gap-3">
          {q.data.rows
            .filter((r) => !schema || fqnSchema(r.table_fqn) === schema)
            .map((f) => (
              <FailureCard key={f.test_id} f={f} />
            ))}
        </div>
      )}
    </>
  );
}

function FailureCard({ f }: { f: DQFailure }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-xl border border-ink-border bg-ink-panel/40 p-5 flex flex-col gap-2">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 text-sm">
            <span className="font-semibold">{f.test_name}</span>
            {f.explanation && <FixTypeChip value={f.explanation.fix_type} />}
          </div>
          <code className="text-xs font-mono text-ink-dim block mt-0.5 break-all">
            {f.table_fqn}
            {f.column_name && ` · column ${f.column_name}`}
            {f.test_definition_name && ` · ${f.test_definition_name}`}
          </code>
        </div>
        {f.explanation && (
          <button
            onClick={() => setOpen((v) => !v)}
            className="text-xs font-mono text-ink-dim hover:text-accent-soft px-2 py-1"
          >
            {open ? 'Collapse' : 'Details'}
          </button>
        )}
      </div>
      {f.result_message && (
        <p className="text-xs text-ink-dim break-words">
          <span className="text-ink-soft">OM message:</span> {f.result_message}
        </p>
      )}
      {f.explanation && open && (
        <div className="mt-1 rounded-md border border-ink-border/60 bg-ink-panel/30 px-3 py-2 space-y-2 text-sm">
          <ExplanationRow label="Summary" value={f.explanation.summary} />
          <ExplanationRow label="Likely cause" value={f.explanation.likely_cause} />
          <ExplanationRow label="Next step" value={f.explanation.next_step} emphasise />
        </div>
      )}
    </div>
  );
}

function ExplanationRow({
  label,
  value,
  emphasise,
}: {
  label: string;
  value: string;
  emphasise?: boolean;
}) {
  return (
    <div>
      <div className="text-mini font-mono uppercase tracking-wider text-ink-dim">{label}</div>
      <div className={emphasise ? 'text-accent-soft' : 'text-ink-text'}>{value}</div>
    </div>
  );
}

// ── Recommendations panel ─────────────────────────────────────────────────

function RecommendationsPanel() {
  const [severity, setSeverity] = useState<Severity | null>(null);
  const q = useQuery({
    queryKey: ['dq', 'recommendations', severity],
    queryFn: () => getDQRecommendations(severity ?? undefined),
  });

  if (q.isLoading) return <Placeholder>Loading recommendations…</Placeholder>;
  if (q.error instanceof ApiError && q.error.code === 'no_metadata_loaded') {
    return <Placeholder>No metadata loaded yet.</Placeholder>;
  }
  if (q.error) return <Placeholder error>{(q.error as Error).message}</Placeholder>;
  if (!q.data) return null;

  if (!q.data.scan_run) {
    return (
      <Placeholder>
        Recommendations haven't been generated yet. Click{' '}
        <strong>💡 Recommend DQ</strong> in the sidebar — one LLM call per table, ~30s on the
        demo catalog.
      </Placeholder>
    );
  }

  const severities: (Severity | null)[] = [null, 'critical', 'recommended', 'nice-to-have'];

  return (
    <>
      <div className="flex flex-wrap gap-1 mb-4">
        {severities.map((s) => {
          const label = s ?? 'all';
          const n = s ? q.data.rows.filter((r) => r.severity === s).length : q.data.rows.length;
          return (
            <button key={label} onClick={() => setSeverity(s)} className={chipCls(severity === s)}>
              {label} ({n})
            </button>
          );
        })}
      </div>

      {q.data.rows.length === 0 ? (
        <Placeholder>
          Nothing recommended for this severity. Try another filter, or run{' '}
          <strong>💡 Recommend DQ</strong> again after updating the catalog.
        </Placeholder>
      ) : (
        <div className="flex flex-col gap-3">
          {q.data.rows.map((r, i) => (
            <RecommendationCard key={`${r.table_fqn}:${r.column_name || ''}:${r.test_definition}:${i}`} r={r} />
          ))}
        </div>
      )}
    </>
  );
}

function RecommendationCard({ r }: { r: DQRecommendation }) {
  return (
    <div className="rounded-xl border border-ink-border bg-ink-panel/40 p-5 flex flex-col gap-2">
      <div className="flex items-center gap-2 text-sm">
        <SeverityChip value={r.severity} />
        <span className="font-mono text-accent-soft">{r.test_definition}</span>
      </div>
      <code className="text-xs font-mono text-ink-dim break-all">
        {r.table_fqn}
        {r.column_name && ` · column ${r.column_name}`}
      </code>
      {r.rationale && <p className="text-sm text-ink-text">{r.rationale}</p>}
      {r.parameters.length > 0 && (
        <details className="mt-1">
          <summary className="cursor-pointer text-xs font-mono text-ink-dim hover:text-accent-soft">
            Parameters ({r.parameters.length})
          </summary>
          <pre className="mt-1 text-xs font-mono text-ink-soft bg-ink-panel/60 rounded-md p-2 overflow-auto max-h-40">
            {JSON.stringify(r.parameters, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}

// ── Risk panel ────────────────────────────────────────────────────────────

function RiskPanel() {
  const q = useQuery({
    queryKey: ['dq', 'risk'],
    queryFn: () => getDQRisk(20),
  });

  if (q.isLoading) return <Placeholder>Loading risk ranking…</Placeholder>;
  if (q.error instanceof ApiError && q.error.code === 'no_metadata_loaded') {
    return <Placeholder>No metadata loaded yet.</Placeholder>;
  }
  if (q.error) return <Placeholder error>{(q.error as Error).message}</Placeholder>;
  if (!q.data || q.data.rows.length === 0) {
    return (
      <Placeholder>
        No failing DQ tests. Risk ranking is empty when the catalog is clean — or seed the demo
        test cases with <code className="font-mono text-accent-soft">make seed</code>.
      </Placeholder>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {q.data.rows.map((r) => (
        <RiskRow key={r.fqn} r={r} />
      ))}
    </div>
  );
}

function RiskRow({ r }: { r: DQRiskRow }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-ink-border bg-ink-panel/40 overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full text-left px-4 py-3 hover:bg-ink-panel/60 flex items-center justify-between gap-3"
      >
        <div className="flex-1 min-w-0">
          <code className="text-sm font-mono text-ink-text break-all">{r.fqn}</code>
          <div className="flex gap-3 text-mini font-mono text-ink-dim mt-0.5">
            <span>
              failed: <span className="text-error-soft">{r.failed_tests}</span>
            </span>
            <span>direct: {r.direct}</span>
            <span>transitive: {r.transitive}</span>
            <span>
              pii ↓: <span className={r.pii_downstream > 0 ? 'text-accent-bright' : ''}>{r.pii_downstream}</span>
            </span>
          </div>
        </div>
        <div className="shrink-0 flex items-center gap-3">
          <div className="text-lg font-semibold text-accent-bright font-mono">{r.risk_score}</div>
          <span className="text-xs text-ink-dim">{open ? '▾' : '▸'}</span>
        </div>
      </button>
      {open && <ImpactDrilldown fqn={r.fqn} />}
    </div>
  );
}

function ImpactDrilldown({ fqn }: { fqn: string }) {
  const q = useQuery({
    queryKey: ['dq', 'impact', fqn],
    queryFn: () => getDQImpact(fqn),
  });

  if (q.isLoading) {
    return <div className="px-4 py-3 text-xs font-mono text-ink-dim">Loading impact…</div>;
  }
  if (q.error) {
    return (
      <div className="px-4 py-3 text-xs font-mono text-error-soft">
        Couldn't load impact: {(q.error as Error).message}
      </div>
    );
  }
  if (!q.data) return null;
  return <ImpactBody d={q.data} />;
}

function ImpactBody({ d }: { d: DQImpactResponse }) {
  return (
    <div className="border-t border-ink-border px-4 py-3 text-xs space-y-2 bg-ink-panel/20">
      {d.failing_test_names.length > 0 && (
        <div>
          <div className="font-mono text-ink-dim uppercase tracking-wider text-mini mb-0.5">
            Failing tests
          </div>
          <ul className="list-disc list-inside text-ink-text">
            {d.failing_test_names.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </div>
      )}
      {d.downstream_fqns.length > 0 && (
        <div>
          <div className="font-mono text-ink-dim uppercase tracking-wider text-mini mb-0.5">
            Downstream impact ({d.downstream_fqns.length} tables)
          </div>
          <ul className="list-disc list-inside font-mono text-ink-text break-all">
            {d.downstream_fqns.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </div>
      )}
      {d.failing_test_names.length === 0 && d.downstream_fqns.length === 0 && (
        <div className="text-ink-dim italic">No active risk for this table.</div>
      )}
    </div>
  );
}

// ── Chips ──────────────────────────────────────────────────────────────────

const FIX_TYPE_LABELS: Record<FixType, { icon: string; label: string }> = {
  schema_change: { icon: '🔷', label: 'Schema change' },
  etl_investigation: { icon: '🔍', label: 'ETL investigation' },
  data_correction: { icon: '⚠️', label: 'Data correction' },
  upstream_fix: { icon: '🔄', label: 'Upstream fix' },
  other: { icon: '🛠', label: 'Other' },
};

function FixTypeChip({ value }: { value: FixType }) {
  const f = FIX_TYPE_LABELS[value] ?? FIX_TYPE_LABELS.other;
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-accent/30 bg-accent/10 px-2 py-0.5 text-mini font-mono text-accent-soft">
      <span aria-hidden>{f.icon}</span>
      {f.label}
    </span>
  );
}

const SEVERITY_STYLES: Record<Severity, { icon: string; cls: string }> = {
  critical: {
    icon: '🚨',
    cls: 'border-error/40 bg-error/10 text-error-soft',
  },
  recommended: {
    icon: '💡',
    cls: 'border-accent/30 bg-accent/10 text-accent-soft',
  },
  'nice-to-have': {
    icon: '✨',
    cls: 'border-ink-border bg-ink-panel/60 text-ink-soft',
  },
};

function SeverityChip({ value }: { value: Severity }) {
  const s = SEVERITY_STYLES[value];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-mini font-mono ${s.cls}`}
    >
      <span aria-hidden>{s.icon}</span>
      {value}
    </span>
  );
}

// ── Utilities ──────────────────────────────────────────────────────────────

function fqnSchema(fqn: string): string {
  const parts = fqn.split('.');
  return parts.length >= 3 ? parts[2] : '';
}

function uniqueSchemas(rows: DQFailure[]): string[] {
  const s = new Set<string>();
  for (const r of rows) {
    const sch = fqnSchema(r.table_fqn);
    if (sch) s.add(sch);
  }
  return [...s].sort();
}

function chipCls(active: boolean): string {
  return (
    'px-2.5 py-1 rounded-md text-mini font-mono border transition-colors ' +
    (active
      ? 'bg-accent/30 text-accent-bright border-accent/40'
      : 'bg-ink-panel/40 text-ink-soft border-ink-border hover:text-ink-text')
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
