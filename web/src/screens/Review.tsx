/**
 * Review queue screen. Lifted from metasift+/MetaSift App.html::ReviewQueue
 * (L724) + DiffPanel (L819). Split list + diff layout replacing the
 * previous card stack:
 *
 *   [filter chips] ─────────────────────────────────────────────────────
 *   │ 420px list │  diff / rationale / actions / audit trail           │
 *
 * Each list row carries a KindIcon + severity pill + FQN + author + a
 * confidence bar. The right panel shows the full diff with accept/edit/
 * reject actions. Inline edit turns the "after" column into a textarea
 * that feeds into the accept-edited endpoint.
 */

import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';

import { AppLayout } from '../components/AppLayout';
import { PageHeader } from '../components/PageHeader';
import {
  acceptEditedReview,
  acceptReview,
  ApiError,
  listReview,
  rejectReview,
  type ReviewItem,
  type ReviewKind,
} from '../lib/api';

type FilterKey = 'all' | ReviewKind;
type ActStatus = 'accepted' | 'accepted_edited' | 'rejected';

const PII_TAG_OPTIONS = ['PII.Sensitive', 'PII.NonSensitive', 'PII.None'] as const;

export function Review() {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<FilterKey>('all');
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [actStatus, setActStatus] = useState<Record<string, ActStatus>>({});

  const q = useQuery({
    queryKey: ['review'],
    queryFn: () => listReview(),
  });

  const visible = useMemo(
    () =>
      filter === 'all'
        ? q.data?.rows ?? []
        : (q.data?.rows ?? []).filter((r) => r.kind === filter),
    [filter, q.data],
  );

  // Re-select if the selection fell off the visible list (after a filter
  // change or an accept/reject removed it).
  const selected = useMemo(() => {
    const found = visible.find((r) => r.key === selectedKey);
    if (found) return found;
    return visible[0] ?? null;
  }, [visible, selectedKey]);

  const counts = useMemo(() => countByKind(q.data?.rows ?? []), [q.data]);

  const invalidate = () => qc.invalidateQueries({ queryKey: ['review'] });

  const markActed = (key: string, status: ActStatus) =>
    setActStatus((m) => ({ ...m, [key]: status }));

  const bulkPending = visible.length;

  return (
    <AppLayout activeKey="review">
      <PageHeader
        title="Review queue"
        subtitle="Human-gated write-back — accept / edit / reject pending suggestions. REST PATCH fires only on approval."
        chips={[
          { label: `${bulkPending} pending`, tone: bulkPending > 0 ? 'amber' : 'slate' },
          { label: `${counts.description} descriptions`, tone: 'slate' },
          { label: `${counts.pii_tag} PII tags`, tone: 'slate' },
        ]}
      />

      {q.isLoading ? (
        <Empty>Loading queue…</Empty>
      ) : q.error instanceof ApiError && q.error.code === 'no_metadata_loaded' ? (
        <Empty>
          No metadata loaded yet. Hit <strong>Refresh metadata</strong> in the sidebar first.
        </Empty>
      ) : q.error ? (
        <Empty error>Couldn't load queue: {(q.error as Error).message}</Empty>
      ) : (q.data?.rows.length ?? 0) === 0 ? (
        <Empty>
          No pending suggestions. Run <strong>Deep scan</strong> or <strong>PII scan</strong>{' '}
          from the sidebar to populate the queue.
        </Empty>
      ) : (
        <>
          {/* Filter row */}
          <div className="border-b border-slate-800/80 px-6 py-2 flex items-center gap-1 flex-wrap">
            <FilterChip
              label="All"
              n={counts.all}
              active={filter === 'all'}
              onClick={() => setFilter('all')}
            />
            <FilterChip
              label="Descriptions"
              n={counts.description}
              active={filter === 'description'}
              onClick={() => setFilter('description')}
            />
            <FilterChip
              label="PII tags"
              n={counts.pii_tag}
              active={filter === 'pii_tag'}
              onClick={() => setFilter('pii_tag')}
            />
            <div className="flex-1" />
            <div className="text-[10px] text-slate-500 font-mono">sorted: confidence ↓</div>
          </div>

          {/* Split: list + diff */}
          <div className="flex-1 flex overflow-hidden min-h-0">
            <div className="w-[420px] shrink-0 border-r border-slate-800/80 overflow-y-auto scrollbar-thin">
              {visible.map((item) => (
                <ReviewListRow
                  key={item.key}
                  item={item}
                  selected={selected?.key === item.key}
                  status={actStatus[item.key]}
                  onSelect={() => setSelectedKey(item.key)}
                />
              ))}
              {visible.length === 0 && (
                <div className="p-6 text-[12px] text-slate-500">Nothing matches this filter.</div>
              )}
            </div>
            <div className="flex-1 overflow-y-auto scrollbar-thin bg-slate-950/40 min-w-0">
              {selected ? (
                <DiffPanel
                  item={selected}
                  status={actStatus[selected.key]}
                  onAccept={async () => {
                    // Let errors propagate — DiffPanel.guard captures them and
                    // renders inline. Wrapping here and swallowing would hide
                    // 502 PATCH_FAILED from the user.
                    await acceptReview(selected.key);
                    markActed(selected.key, 'accepted');
                    invalidate();
                  }}
                  onAcceptEdited={async (value: string) => {
                    await acceptEditedReview(selected.key, value);
                    markActed(selected.key, 'accepted_edited');
                    invalidate();
                  }}
                  onReject={async () => {
                    await rejectReview(selected.key);
                    markActed(selected.key, 'rejected');
                    invalidate();
                  }}
                />
              ) : (
                <div className="p-8 text-[13px] text-slate-500">
                  Select a suggestion on the left to review.
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </AppLayout>
  );
}

// ── Filter chip ────────────────────────────────────────────────────────────

function FilterChip({
  label,
  n,
  active,
  onClick,
}: {
  label: string;
  n: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={
        'text-[11px] px-2.5 py-1.5 rounded-md transition font-medium border ' +
        (active
          ? 'bg-emerald-500/10 text-emerald-200 border-emerald-500/25'
          : 'text-slate-400 hover:text-white hover:bg-slate-900 border-transparent')
      }
    >
      {label} <span className="font-mono text-slate-600 ml-1">{n}</span>
    </button>
  );
}

// ── List row ───────────────────────────────────────────────────────────────

function ReviewListRow({
  item,
  selected,
  status,
  onSelect,
}: {
  item: ReviewItem;
  selected: boolean;
  status?: ActStatus;
  onSelect: () => void;
}) {
  const sev = severityOf(item);
  return (
    <button
      type="button"
      onClick={onSelect}
      className={
        'rq-row w-full text-left px-5 py-3 border-b border-slate-800/60 transition ' +
        (selected
          ? 'bg-emerald-500/5 border-l-2 border-l-emerald-400'
          : 'border-l-2 border-l-transparent')
      }
    >
      <div className="flex items-start gap-2">
        <div className="shrink-0 w-7 h-7 rounded-md bg-slate-900 border border-slate-800 flex items-center justify-center">
          <KindIcon item={item} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <SeverityPill sev={sev} />
            <span className="text-[10px] text-slate-500 font-mono truncate">
              {kindLabel(item)}
            </span>
          </div>
          <div className="text-[12px] font-mono text-slate-200 truncate">
            {shortFQN(item.fqn)}
            {item.column && <span className="text-slate-500"> · {item.column}</span>}
          </div>
          <div className="text-[11px] text-slate-500 truncate">{authorOf(item)}</div>
          <div className="flex items-center gap-3 mt-1.5">
            <div className="flex items-center gap-1.5 text-[10px]">
              <div className="w-14 h-1 bg-slate-800 rounded-full overflow-hidden">
                <div
                  className="h-full bg-emerald-400"
                  style={{ width: `${item.confidence * 100}%` }}
                />
              </div>
              <span className="font-mono text-slate-400">
                {(item.confidence * 100).toFixed(0)}%
              </span>
            </div>
            {status && (
              <span
                className={
                  'text-[10px] font-mono px-1.5 py-0.5 rounded ' +
                  (status === 'rejected'
                    ? 'bg-red-500/15 text-red-300'
                    : 'bg-emerald-500/15 text-emerald-300')
                }
              >
                {status.replace('_', ' ')}
              </span>
            )}
          </div>
        </div>
      </div>
    </button>
  );
}

// ── Diff panel ─────────────────────────────────────────────────────────────

function DiffPanel({
  item,
  status,
  onAccept,
  onAcceptEdited,
  onReject,
}: {
  item: ReviewItem;
  status?: ActStatus;
  onAccept: () => void | Promise<void>;
  onAcceptEdited: (value: string) => void | Promise<void>;
  onReject: () => void | Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(item.new);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const sev = severityOf(item);

  // Reset local edit state when the selected card changes. Keyed on item.key
  // rather than item.new so an in-progress edit doesn't get clobbered by a
  // background refetch that happens to return a different suggested value.
  useEffect(() => {
    setDraft(item.new);
    setEditing(false);
    setErr(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.key]);

  const guard = async (fn: () => Promise<void> | void) => {
    setBusy(true);
    setErr(null);
    try {
      await fn();
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `${e.code}: ${e.message}`
          : e instanceof Error
            ? e.message
            : String(e),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="p-6 max-w-3xl">
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <KindIcon item={item} />
            <span className="text-[11px] font-mono text-emerald-300 uppercase tracking-wider">
              {kindLabel(item)}
            </span>
            <SeverityPill sev={sev} />
          </div>
          <div className="font-mono text-[15px] text-white break-all">{item.fqn}</div>
          <div className="text-[12px] text-slate-500 mt-1">
            Field:{' '}
            <span className="font-mono text-slate-300">
              {item.kind === 'pii_tag' ? `column ${item.column}` : 'description'}
            </span>{' '}
            · by {authorOf(item)}
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className="text-[10px] uppercase tracking-wider text-slate-500">Confidence</div>
          <div className="text-2xl font-mono text-emerald-300 font-bold">
            {(item.confidence * 100).toFixed(0)}%
          </div>
        </div>
      </div>

      {/* Diff */}
      <div className="rounded-xl border border-slate-800 bg-slate-950/60 overflow-hidden">
        <div className="px-4 py-2 border-b border-slate-800 bg-slate-900/40 flex items-center justify-between">
          <div className="text-[11px] font-mono text-slate-400">
            patch · {item.kind === 'pii_tag' ? 'column tag' : 'description'}
          </div>
          <div className="text-[10px] font-mono text-slate-600 truncate">
            REST PATCH /api/v1/tables/name/{shortFQN(item.fqn)}
          </div>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 md:divide-x md:divide-y-0 divide-y divide-slate-800">
          <div className="p-4">
            <div className="text-[10px] uppercase tracking-wider text-red-300/70 font-semibold mb-2">
              — before
            </div>
            <div className="text-[12px] text-slate-400 leading-relaxed font-mono whitespace-pre-wrap break-words">
              {item.old?.trim() ? item.old : <em className="not-italic text-slate-600">(empty)</em>}
            </div>
          </div>
          <div className="p-4 bg-emerald-500/[0.03]">
            <div className="text-[10px] uppercase tracking-wider text-emerald-300/70 font-semibold mb-2">
              + after
            </div>
            {editing ? (
              item.kind === 'description' ? (
                <textarea
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  rows={5}
                  className="w-full min-h-[80px] bg-slate-900 border border-emerald-500/30 rounded p-2 font-mono text-[12px] text-emerald-100 outline-none focus:border-emerald-500/60"
                />
              ) : (
                <select
                  value={PII_TAG_OPTIONS.includes(draft as (typeof PII_TAG_OPTIONS)[number]) ? draft : item.new}
                  onChange={(e) => setDraft(e.target.value)}
                  className="w-full bg-slate-900 border border-emerald-500/30 rounded p-2 font-mono text-[12px] text-emerald-100 outline-none focus:border-emerald-500/60"
                >
                  {PII_TAG_OPTIONS.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              )
            ) : (
              <div className="text-[12px] text-emerald-100 leading-relaxed font-mono whitespace-pre-wrap break-words">
                {item.new}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Rationale */}
      {item.reason && (
        <div className="mt-5 rounded-lg border border-slate-800 bg-slate-900/30 p-4">
          <div className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold mb-2">
            Rationale
          </div>
          <div className="text-[13px] text-slate-300 leading-relaxed">{item.reason}</div>
        </div>
      )}

      {/* Actions */}
      <div className="mt-6 flex items-center gap-2 flex-wrap">
        {status ? (
          <div className="flex-1 text-[12px] text-slate-400">
            Status:{' '}
            <span
              className={status === 'rejected' ? 'text-red-300' : 'text-emerald-300'}
            >
              {status.replace('_', ' ')}
            </span>{' '}
            ·{' '}
            {status === 'rejected'
              ? 'dismissed (no write)'
              : 'write dispatched to OpenMetadata REST API.'}
          </div>
        ) : editing ? (
          <>
            <button
              type="button"
              onClick={() =>
                guard(async () => {
                  await onAcceptEdited(draft);
                  setEditing(false);
                })
              }
              disabled={busy || !draft.trim()}
              className="px-4 py-2 rounded-md bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-semibold text-[13px] transition disabled:opacity-50"
            >
              {busy ? 'Saving…' : '💾 Save & apply'}
            </button>
            <button
              type="button"
              onClick={() => {
                setEditing(false);
                setDraft(item.new);
              }}
              disabled={busy}
              className="px-4 py-2 rounded-md bg-slate-800 hover:bg-slate-700 text-white text-[13px] transition border border-slate-700 disabled:opacity-50"
            >
              Cancel
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              onClick={() => guard(onAccept)}
              disabled={busy}
              className="px-4 py-2 rounded-md bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-semibold text-[13px] transition disabled:opacity-50"
            >
              {busy ? 'Working…' : '✓ Accept & PATCH'}
            </button>
            <button
              type="button"
              onClick={() => setEditing(true)}
              disabled={busy}
              className="px-4 py-2 rounded-md bg-slate-800 hover:bg-slate-700 text-white text-[13px] transition border border-slate-700 disabled:opacity-50"
            >
              ✎ Edit
            </button>
            <button
              type="button"
              onClick={() => guard(onReject)}
              disabled={busy}
              className="px-4 py-2 rounded-md bg-slate-900 hover:bg-red-500/10 text-slate-300 hover:text-red-300 text-[13px] transition border border-slate-800 disabled:opacity-50"
            >
              ✕ Reject
            </button>
          </>
        )}
      </div>
      {err && (
        <div className="mt-3 text-[11px] font-mono text-red-300">
          ⚠ {err}
        </div>
      )}
    </div>
  );
}

// ── Chips + helpers ────────────────────────────────────────────────────────

type Severity = 'critical' | 'high' | 'med' | 'low';

const SEVERITY_CLS: Record<Severity, string> = {
  critical: 'bg-red-500/15 text-red-300 border-red-500/25',
  high: 'bg-amber-500/15 text-amber-300 border-amber-500/25',
  med: 'bg-cyan-500/15 text-cyan-300 border-cyan-500/25',
  low: 'bg-slate-500/15 text-slate-300 border-slate-500/25',
};

function SeverityPill({ sev }: { sev: Severity }) {
  return (
    <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${SEVERITY_CLS[sev]}`}>
      {sev}
    </span>
  );
}

function severityOf(item: ReviewItem): Severity {
  if (item.kind === 'pii_tag' && item.new === 'PII.Sensitive') return 'critical';
  if (item.confidence >= 0.9) return 'high';
  if (item.confidence >= 0.7) return 'med';
  return 'low';
}

function KindIcon({ item }: { item: ReviewItem }) {
  const icon =
    item.kind === 'pii_tag'
      ? '⚑'
      : item.key.startsWith('doc::')
        ? '◆'
        : '✎';
  return <span className="text-emerald-300">{icon}</span>;
}

function kindLabel(item: ReviewItem): string {
  if (item.kind === 'pii_tag') return 'pii-tag';
  if (item.key.startsWith('doc::')) return 'auto-doc';
  return 'stale-desc';
}

function authorOf(item: ReviewItem): string {
  if (item.kind === 'pii_tag') return 'Cleaning engine · PII scan';
  if (item.key.startsWith('doc::')) return 'Stewardship · auto-doc';
  return 'Cleaning engine · stale rewrite';
}

function shortFQN(fqn: string): string {
  const parts = fqn.split('.');
  if (parts.length <= 2) return fqn;
  return parts.slice(-3).join('.');
}

function countByKind(rows: ReviewItem[]): { all: number; description: number; pii_tag: number } {
  // Count explicitly — an else-branch would silently attribute any new kind
  // the backend introduces (e.g. `naming`) to pii_tag, inflating that chip.
  let desc = 0;
  let pii = 0;
  for (const r of rows) {
    if (r.kind === 'description') desc++;
    else if (r.kind === 'pii_tag') pii++;
  }
  return { all: rows.length, description: desc, pii_tag: pii };
}

function Empty({ children, error }: { children: React.ReactNode; error?: boolean }) {
  return (
    <div className="flex-1 p-8">
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
    </div>
  );
}
