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
import { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { AppLayout } from '../components/AppLayout';
import { CopyableFQN, shortFQN } from '../components/CopyableFQN';
import { EmptyState } from '../components/EmptyState';
import { PageHeader } from '../components/PageHeader';
import { Skeleton } from '../components/Skeleton';
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

  const visible = useMemo(() => {
    const rows =
      filter === 'all'
        ? q.data?.rows ?? []
        : (q.data?.rows ?? []).filter((r) => r.kind === filter);
    // Sort matches the "sorted: confidence ↓" label in the filter strip.
    // Tie-break by FQN for stable ordering across refetches.
    return [...rows].sort(
      (a, b) => b.confidence - a.confidence || a.fqn.localeCompare(b.fqn),
    );
  }, [filter, q.data]);

  // Re-select if the selection fell off the visible list (after a filter
  // change or an accept/reject removed it).
  const selected = useMemo(() => {
    const found = visible.find((r) => r.key === selectedKey);
    if (found) return found;
    return visible[0] ?? null;
  }, [visible, selectedKey]);

  const counts = useMemo(() => countByKind(q.data?.rows ?? []), [q.data]);

  // After a mutation lands, refetch the list AND drop actStatus entries for
  // keys that are no longer in the queue. Without the prune, dead keys
  // accumulate in actStatus across the session and grow the in-memory map.
  const invalidate = async () => {
    await qc.invalidateQueries({ queryKey: ['review'] });
    const fresh = qc.getQueryData<{ rows: ReviewItem[] }>(['review']);
    if (!fresh) return;
    const live = new Set(fresh.rows.map((r) => r.key));
    setActStatus((m) => {
      const next: Record<string, ActStatus> = {};
      for (const [k, v] of Object.entries(m)) {
        if (live.has(k)) next[k] = v;
      }
      return next;
    });
  };

  const markActed = (key: string, status: ActStatus) =>
    setActStatus((m) => ({ ...m, [key]: status }));

  const bulkPending = visible.length;

  // j/k navigation over the visible list. Skipped while the user is typing
  // (so inline edits don't get hijacked) and wraps at both ends so the user
  // can keep holding j without hitting a dead zone.
  const moveSelection = useCallback(
    (delta: 1 | -1) => {
      if (visible.length === 0) return;
      const currentIdx = selected ? visible.findIndex((r) => r.key === selected.key) : -1;
      const nextIdx =
        currentIdx === -1
          ? 0
          : (currentIdx + delta + visible.length) % visible.length;
      setSelectedKey(visible[nextIdx].key);
    },
    [visible, selected],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key !== 'j' && e.key !== 'k') return;
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName;
      if (
        tag === 'INPUT' ||
        tag === 'TEXTAREA' ||
        tag === 'SELECT' ||
        target?.isContentEditable
      )
        return;
      e.preventDefault();
      moveSelection(e.key === 'j' ? 1 : -1);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [moveSelection]);

  // Keep the selected row in view when j/k scrolls past the viewport edge.
  // Querying by data-attribute is simpler than threading refs through every
  // row — there's only ever one selected row so the lookup is cheap.
  useEffect(() => {
    if (!selected) return;
    const el = document.querySelector<HTMLElement>(
      `[data-review-key="${CSS.escape(selected.key)}"]`,
    );
    el?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [selected?.key]); // eslint-disable-line react-hooks/exhaustive-deps

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
        <ReviewSkeleton />
      ) : q.error instanceof ApiError && q.error.code === 'no_metadata_loaded' ? (
        <div className="p-8">
          <EmptyState
            icon="↻"
            title="No metadata loaded yet"
            body={
              <>
                The review queue is populated from a refreshed catalog. Hit{' '}
                <strong>Refresh metadata</strong> in the sidebar to pull from OpenMetadata.
              </>
            }
            hint="Once the refresh finishes, run Deep scan or PII scan to generate suggestions."
          />
        </div>
      ) : q.error ? (
        <div className="p-8">
          <EmptyState
            variant="error"
            icon="⚠"
            title="Couldn't load queue"
            body={(q.error as Error).message}
          />
        </div>
      ) : (q.data?.rows.length ?? 0) === 0 ? (
        <div className="p-8">
          <EmptyState
            icon="✓"
            title="No pending suggestions"
            body="The catalog is clean — or no scans have run yet."
            hint={
              <>
                Run <strong className="text-slate-300">Deep scan</strong> (descriptions) or{' '}
                <strong className="text-slate-300">PII scan</strong> (tags) from the sidebar to
                populate the queue.
              </>
            }
          />
        </div>
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
            <div className="flex items-center gap-3 text-[10px] text-slate-500 font-mono">
              <span className="flex items-center gap-1">
                <kbd>j</kbd>
                <kbd>k</kbd>
                <span>navigate</span>
              </span>
              <span>sorted: confidence ↓</span>
            </div>
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
                <div className="p-4">
                  <EmptyState
                    compact
                    icon="⌕"
                    title="No matches"
                    body="Nothing in the queue matches this filter."
                    hint="Try a different filter chip above."
                  />
                </div>
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
                    toast.success('Accepted · PATCH dispatched', {
                      description: shortFQN(selected.fqn),
                    });
                    invalidate();
                  }}
                  onAcceptEdited={async (value: string) => {
                    await acceptEditedReview(selected.key, value);
                    markActed(selected.key, 'accepted_edited');
                    toast.success('Saved & applied', {
                      description: shortFQN(selected.fqn),
                    });
                    invalidate();
                  }}
                  onReject={async () => {
                    await rejectReview(selected.key);
                    markActed(selected.key, 'rejected');
                    toast('Rejected', {
                      description: shortFQN(selected.fqn),
                    });
                    invalidate();
                  }}
                />
              ) : (
                <div className="p-8">
                  <EmptyState
                    compact
                    icon="◀"
                    title="Pick a suggestion"
                    body="Select a row on the left to see the before/after diff and rationale."
                  />
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
  // Using role="button" on a div (not a <button>) because the row contains
  // a nested CopyableFQN button — button-in-button is invalid HTML and
  // Safari drops the inner click.
  return (
    <div
      role="button"
      tabIndex={0}
      data-review-key={item.key}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onSelect();
        }
      }}
      aria-pressed={selected}
      className={
        'rq-row w-full text-left px-5 py-3 border-b border-slate-800/60 transition cursor-pointer focus:outline-none focus:bg-slate-900/60 ' +
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
          <div className="truncate">
            <CopyableFQN
              fqn={item.fqn}
              variant="short"
              columnSuffix={item.column ? `· ${item.column}` : undefined}
              className="font-mono text-[12px] text-slate-200"
            />
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
    </div>
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
          <CopyableFQN
            fqn={item.fqn}
            variant="full"
            className="font-mono text-[15px] text-white"
          />
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

// List-shaped skeleton that mirrors ReviewListRow geometry: 28px kind badge,
// severity pill + kind label row, FQN line, author line, confidence bar.
// Tuning the dimensions to the real row means layout doesn't jump when the
// query resolves.
function ReviewSkeleton() {
  return (
    <div className="flex-1 flex overflow-hidden min-h-0">
      <div className="w-[420px] shrink-0 border-r border-slate-800/80 overflow-hidden">
        {Array.from({ length: 7 }).map((_, i) => (
          <div key={i} className="px-5 py-3 border-b border-slate-800/60 flex items-start gap-2">
            <Skeleton className="h-7 w-7 shrink-0 rounded-md" />
            <div className="flex-1 min-w-0 space-y-1.5">
              <div className="flex items-center gap-2">
                <Skeleton className="h-[14px] w-12 rounded" />
                <Skeleton className="h-[10px] w-16 rounded" />
              </div>
              <Skeleton className="h-[14px] w-3/4 rounded" />
              <Skeleton className="h-[10px] w-1/2 rounded" />
              <Skeleton className="h-[6px] w-24 rounded-full" />
            </div>
          </div>
        ))}
      </div>
      <div className="flex-1 bg-slate-950/40 p-6 space-y-4">
        <Skeleton className="h-[18px] w-48 rounded" />
        <Skeleton className="h-[14px] w-64 rounded" />
        <Skeleton className="h-[220px] w-full rounded-xl" />
        <div className="flex gap-2">
          <Skeleton className="h-[34px] w-32 rounded-md" />
          <Skeleton className="h-[34px] w-20 rounded-md" />
          <Skeleton className="h-[34px] w-20 rounded-md" />
        </div>
      </div>
    </div>
  );
}

