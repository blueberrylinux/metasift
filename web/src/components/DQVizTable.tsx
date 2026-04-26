/**
 * Native HTML tables for the DQ failures and DQ gaps viz tabs.
 *
 * The Plotly Table component has a fundamental limitation: cell height is
 * uniform across all rows. For these two views the cells hold variable-
 * length LLM-written explanations / rationales — short ones leave dead
 * space, long ones overflow the cell and paint over the next row, which
 * is what produced the apparent "row 6 is empty" + cross-row text bleed
 * in the previous Plotly-rendered version.
 *
 * Each row's content drives its own height here; long rationales just
 * make that row taller. Container's overflow handles scrolling cleanly,
 * and the two tables share the same CSS so failures and gaps read with
 * identical rhythm.
 */

import { useQuery } from '@tanstack/react-query';

import {
  ApiError,
  type DQFailure,
  type DQRecommendation,
  type Severity,
  getDQFailures,
  getDQRecommendations,
} from '../lib/api';
import { CopyableFQN, shortFQN } from './CopyableFQN';
import { EmptyState } from './EmptyState';
import { Skeleton } from './Skeleton';

const FIX_TYPE_CHIPS: Record<string, string> = {
  schema_change: 'Schema change',
  etl_investigation: 'ETL investigation',
  data_correction: 'Data correction',
  upstream_fix: 'Upstream fix',
  other: 'Other',
};

// Common shell + cell typography. Re-used by both tables so they read
// identically — top-aligned, monospace identifier cells, body-font for
// LLM text, alternating row background for scan-ability.
//
// Three cell flavors:
// - CELL_ID: monospace 12px, no-wrap, slate-300. Used for short identifiers
//   (FQN, column name, definition, chip labels) so they stay one-line tight.
// - CELL_CODE: monospace 12px, *break-all* + overflow-hidden, slate-400.
//   Used for code-shaped values like regex parameters that have no word
//   boundaries — wraps mid-token instead of painting over adjacent cells.
// - CELL_PROSE: 13px sans, leading-relaxed (1.625), slate-200. Used for
//   multi-sentence LLM output (failure messages, summaries, rationales)
//   so the text breathes instead of feeling jammed.
//
// All three share generous py-4 / px-4 padding so adjacent rows don't run
// into each other visually.
const CELL_PROSE =
  'align-top px-4 py-4 text-[13px] leading-relaxed text-slate-200';
// `overflow-hidden text-ellipsis` is defense-in-depth: with table-fixed +
// explicit colgroup widths, content longer than its column gets clipped
// with an ellipsis instead of painting horizontally over the next cell.
// In practice the colgroup widths below are sized to fit the longest known
// content; the ellipsis only kicks in for unforeseen / future-too-long
// strings (e.g. very long bot-generated column names) so they degrade
// gracefully without obscuring adjacent columns.
const CELL_ID =
  'align-top px-4 py-4 text-[12px] font-mono text-slate-300 whitespace-nowrap overflow-hidden text-ellipsis';
const CELL_CODE =
  'align-top px-4 py-4 text-[11px] font-mono text-slate-400 break-all leading-relaxed';
const HEADER_BASE =
  'sticky top-0 z-10 bg-slate-900/95 backdrop-blur-sm text-left px-4 py-3 ' +
  'text-[12px] font-semibold text-slate-100 uppercase tracking-wider border-b border-slate-700';

// ── DQ failures ────────────────────────────────────────────────────────────

export function DQFailuresVizTable() {
  const q = useQuery({
    queryKey: ['dq', 'failures'],
    queryFn: getDQFailures,
    retry: false,
  });

  if (q.isLoading) return <TableSkeleton cols={8} rows={4} />;
  if (q.error instanceof ApiError && q.error.code === 'no_metadata_loaded') {
    return (
      <EmptyState
        icon="↻"
        title="No metadata loaded yet"
        body="Hit Refresh metadata in the sidebar first."
      />
    );
  }
  if (q.error) {
    return (
      <EmptyState
        variant="error"
        icon="⚠"
        title="Couldn't load DQ failures"
        body={(q.error as Error).message}
      />
    );
  }
  if (!q.data || q.data.rows.length === 0) {
    return (
      <EmptyState
        icon="🧪"
        title="No failing DQ tests"
        body="Either no tests are configured in OpenMetadata, or every test is currently passing."
        hint="Run `make seed` to populate sample failing tests for the demo."
      />
    );
  }

  const explained = q.data.rows.filter((r) => r.explanation).length;

  return (
    <div>
      <div className="text-[12px] text-slate-400 mb-3 font-mono">
        Failing DQ checks — {q.data.rows.length} total · {explained} explained
        {explained < q.data.rows.length && (
          <span className="text-slate-500">
            {' '}(click Explain DQ failures in the sidebar to fill in the rest)
          </span>
        )}
      </div>
      <div className="overflow-auto rounded-lg border border-slate-800 bg-slate-950/40 max-h-[calc(100vh-340px)]">
        <table
          className="w-full border-collapse table-fixed"
          style={{ minWidth: 1700 }}
        >
          <colgroup>
            {/* Table column 280: fits "analytics.users.customer_profiles"
                (33 chars × 7px ≈ 231px) with breathing room. */}
            <col style={{ width: 280 }} />
            {/* Column 160: fits "user_sessions_started_at" et al. */}
            <col style={{ width: 160 }} />
            {/* Definition 220: fits "columnValuesToMatchRegex". */}
            <col style={{ width: 220 }} />
            <col style={{ width: 240 }} />
            <col style={{ width: 240 }} />
            <col style={{ width: 240 }} />
            <col style={{ width: 160 }} />
            <col style={{ width: 240 }} />
          </colgroup>
          <thead>
            <tr>
              <th className={HEADER_BASE}>Table</th>
              <th className={HEADER_BASE}>Column</th>
              <th className={HEADER_BASE}>Definition</th>
              <th className={HEADER_BASE}>Failure message</th>
              <th className={HEADER_BASE}>Summary</th>
              <th className={HEADER_BASE}>Likely cause</th>
              <th className={HEADER_BASE}>Fix type</th>
              <th className={HEADER_BASE}>Suggested fix</th>
            </tr>
          </thead>
          <tbody>
            {q.data.rows.map((r, i) => (
              <DQFailureRow key={r.test_id} row={r} alt={i % 2 === 1} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function DQFailureRow({ row, alt }: { row: DQFailure; alt: boolean }) {
  const ex = row.explanation;
  const bg = alt ? 'bg-slate-900/30' : 'bg-slate-950/40';
  return (
    <tr className={`${bg} border-b border-slate-800/60`}>
      <td className={CELL_ID + ' text-slate-200'}>
        <CopyableFQN
          fqn={row.table_fqn}
          variant="short"
          className="font-mono text-[12px] text-slate-200"
        />
      </td>
      <td className={CELL_ID}>{row.column_name || '—'}</td>
      <td className={CELL_ID}>{row.test_definition_name || '—'}</td>
      <td className={CELL_PROSE}>{row.result_message || '—'}</td>
      <td className={CELL_PROSE}>{ex?.summary || <Pending />}</td>
      <td className={CELL_PROSE}>{ex?.likely_cause || <Pending />}</td>
      <td className={CELL_PROSE}>
        {ex?.fix_type ? <FixTypeChip kind={ex.fix_type} /> : <Pending />}
      </td>
      <td className={CELL_PROSE}>{ex?.next_step || <Pending />}</td>
    </tr>
  );
}

function Pending() {
  return (
    <span className="text-[11px] font-mono text-slate-600 italic">
      not yet explained
    </span>
  );
}

function FixTypeChip({ kind }: { kind: string }) {
  const label = FIX_TYPE_CHIPS[kind] ?? kind;
  return (
    <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-200 border border-cyan-500/20 whitespace-nowrap inline-block">
      {label}
    </span>
  );
}

// ── DQ gaps ────────────────────────────────────────────────────────────────

const SEVERITY_TONE: Record<Severity, string> = {
  critical: 'bg-red-500/10 text-red-300 border-red-500/30',
  recommended: 'bg-amber-500/10 text-amber-300 border-amber-500/30',
  'nice-to-have': 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30',
};

export function DQGapsVizTable() {
  const q = useQuery({
    queryKey: ['dq', 'recommendations'],
    queryFn: () => getDQRecommendations(),
    retry: false,
  });

  if (q.isLoading) return <TableSkeleton cols={6} rows={5} />;
  if (q.error instanceof ApiError && q.error.code === 'no_metadata_loaded') {
    return (
      <EmptyState
        icon="↻"
        title="No metadata loaded yet"
        body="Hit Refresh metadata in the sidebar first."
      />
    );
  }
  if (q.error) {
    return (
      <EmptyState
        variant="error"
        icon="⚠"
        title="Couldn't load DQ gaps"
        body={(q.error as Error).message}
      />
    );
  }
  if (!q.data) return null;
  if (!q.data.scan_run) {
    return (
      <EmptyState
        icon="💡"
        title="DQ recommendations not generated yet"
        body="MetaSift analyses each table's columns + tags + existing tests to suggest tests that should exist."
        hint="Click Recommend DQ tests in the sidebar — one LLM call per table."
      />
    );
  }
  if (q.data.rows.length === 0) {
    return (
      <EmptyState
        icon="✓"
        title="No DQ gaps detected"
        body="Every table already has the tests MetaSift would have recommended."
      />
    );
  }

  const counts = q.data.rows.reduce<Record<string, number>>((acc, r) => {
    acc[r.severity] = (acc[r.severity] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div>
      <div className="text-[12px] text-slate-400 mb-3 font-mono">
        DQ recommendation gaps — {q.data.rows.length} total · {counts.critical ?? 0} critical · {counts.recommended ?? 0} recommended · {counts['nice-to-have'] ?? 0} nice-to-have
      </div>
      <div className="overflow-auto rounded-lg border border-slate-800 bg-slate-950/40 max-h-[calc(100vh-340px)]">
        <table
          className="w-full border-collapse table-fixed"
          style={{ minWidth: 1200 }}
        >
          <colgroup>
            {/* Same Table column width as DQ failures so the two tabs read
                identically when switching between them. */}
            <col style={{ width: 280 }} />
            <col style={{ width: 180 }} />
            <col style={{ width: 220 }} />
            <col style={{ width: 200 }} />
            <col style={{ width: 130 }} />
            <col />
          </colgroup>
          <thead>
            <tr>
              <th className={HEADER_BASE}>Table</th>
              <th className={HEADER_BASE}>Column</th>
              <th className={HEADER_BASE}>Test definition</th>
              <th className={HEADER_BASE}>Parameters</th>
              <th className={HEADER_BASE}>Severity</th>
              <th className={HEADER_BASE}>Rationale</th>
            </tr>
          </thead>
          <tbody>
            {q.data.rows.map((r, i) => (
              <DQGapRow key={`${r.table_fqn}:${r.column_name || ''}:${r.test_definition}:${i}`} row={r} alt={i % 2 === 1} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function DQGapRow({ row, alt }: { row: DQRecommendation; alt: boolean }) {
  const bg = alt ? 'bg-slate-900/30' : 'bg-slate-950/40';
  const params = row.parameters && row.parameters.length > 0
    ? row.parameters
        .map((p) => `${p.name ?? ''}=${p.value ?? ''}`)
        .join(', ')
    : '—';
  return (
    <tr className={`${bg} border-b border-slate-800/60`}>
      <td className={CELL_ID + ' text-slate-200'}>
        <CopyableFQN
          fqn={row.table_fqn}
          variant="short"
          className="font-mono text-[12px] text-slate-200"
        />
      </td>
      <td className={CELL_ID}>
        {row.column_name || (
          <span className="italic text-slate-500">(table-level)</span>
        )}
      </td>
      <td className={CELL_ID}>{row.test_definition}</td>
      <td className={CELL_CODE}>{params}</td>
      <td className="align-top px-4 py-4">
        <span
          className={
            'text-[11px] font-mono px-2 py-0.5 rounded border whitespace-nowrap inline-block ' +
            (SEVERITY_TONE[row.severity] ?? 'bg-slate-800 text-slate-300 border-slate-700')
          }
        >
          {row.severity}
        </span>
      </td>
      <td className={CELL_PROSE}>{row.rationale || '—'}</td>
    </tr>
  );
}

// ── Shared ─────────────────────────────────────────────────────────────────

function TableSkeleton({ cols, rows }: { cols: number; rows: number }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/40 overflow-hidden">
      <div className="grid border-b border-slate-700 bg-slate-900/95" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0,1fr))` }}>
        {Array.from({ length: cols }).map((_, i) => (
          <div key={i} className="px-3 py-2.5">
            <Skeleton className="h-[14px] w-20" />
          </div>
        ))}
      </div>
      {Array.from({ length: rows }).map((_, r) => (
        <div
          key={r}
          className={'grid border-b border-slate-800/60 ' + (r % 2 ? 'bg-slate-900/30' : 'bg-slate-950/40')}
          style={{ gridTemplateColumns: `repeat(${cols}, minmax(0,1fr))` }}
        >
          {Array.from({ length: cols }).map((__, c) => (
            <div key={c} className="px-3 py-2.5">
              <Skeleton className="h-[12px] w-full max-w-[120px]" />
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

// `shortFQN` is imported from CopyableFQN so the column copies the
// identical short form already used everywhere else in the app.
export { shortFQN };
