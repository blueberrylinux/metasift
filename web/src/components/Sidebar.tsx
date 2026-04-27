/**
 * Sidebar rebuilt from metasift+/MetaSift App.html::Sidebar (L311-L410).
 * Structure:
 *   1. Composite health hero — ScoreRing + 2x2 MetricMini grid + weighting bar
 *   2. Workspace nav — renders flat (7 rows) or grouped (Stew / Observability ▸
 *      / Catalog ▸ / LLM setup) depending on SIDEBAR_NAV_LAYOUT below
 *   3. Quick actions — 5 scan trigger rows with inline progress
 *   4. Footer — OM + LLM connection status pulses
 *
 * Everything lifts hooks from the same query surfaces the screens use
 * (`['composite']`, `['review']`, `['health']`) so values stay in sync
 * without a bespoke sidebar query.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { toast } from 'sonner';

import {
  ApiError,
  type BulkDocBody,
  type CompositeScore,
  type HealthResponse,
  type ScanFrame,
  type ScanKind,
  getComposite,
  getHealth,
  listReview,
  streamScan,
} from '../lib/api';
import { useActiveScan, useSandbox } from '../lib/sandbox';
import { useByoKeyTrap } from './ByoKeyModal';
import { MetricMini, type Tone } from './MetricMini';
import { NavIcon, type NavIconKind } from './NavIcon';
import { ScoreRing } from './ScoreRing';
import { Skeleton, SkeletonRing } from './Skeleton';

export type NavKey = 'chat' | 'review' | 'sources' | 'viz' | 'dq' | 'report' | 'llm';

// Layout switcher — three live paths so we can A/B-compare without losing
// the previous shapes. Flip to 'flat' or 'grouped' to revert. Remove the
// flag + the unused paths once the design is locked.
//   'flat'         — original 7-row workspace nav + 5-row Quick actions.
//   'grouped'      — Observability/Catalog dropdown tree + Quick actions.
//   'restructured' — TopBar gains route shortcuts; sidebar nests scans
//                    under Observability + Scans groups; Quick actions
//                    section is gone (everything's in nav).
const SIDEBAR_NAV_LAYOUT: 'flat' | 'grouped' | 'restructured' = 'restructured';

type GroupKey = 'observability' | 'catalog' | 'scans';

interface NavLeaf {
  kind: 'leaf';
  key: NavKey;
  label: string;
  desc: string;
  to: string;
  icon: NavIconKind;
}
interface NavScanItem {
  kind: 'scan';
  scanKind: ScanKind;
  label: string;
  sub: string;
  icon: string;
}
type NavChild = NavLeaf | NavScanItem;
interface NavGroup {
  kind: 'group';
  key: GroupKey;
  label: string;
  icon: NavIconKind;
  children: NavChild[];
}
type NavNode = NavLeaf | NavGroup;

// Legacy flat layout — kept for A/B via SIDEBAR_NAV_LAYOUT.
const NAV_ITEMS: NavLeaf[] = [
  { kind: 'leaf', key: 'chat', label: 'Stew', desc: 'Metadata wizard', to: '/chat', icon: 'chat' },
  { kind: 'leaf', key: 'review', label: 'Review queue', desc: 'Accept · edit · reject', to: '/review', icon: 'queue' },
  { kind: 'leaf', key: 'sources', label: 'Data sources', desc: 'Connected services', to: '/data-sources', icon: 'sources' },
  { kind: 'leaf', key: 'viz', label: 'Visualizations', desc: '11 tabs', to: '/viz', icon: 'viz' },
  { kind: 'leaf', key: 'dq', label: 'Data quality', desc: 'Failures · gaps · risk', to: '/dq', icon: 'dq' },
  { kind: 'leaf', key: 'report', label: 'Executive report', desc: 'Markdown export', to: '/report', icon: 'doc' },
  { kind: 'leaf', key: 'llm', label: 'LLM setup', desc: 'Provider · model · keys', to: '/settings', icon: 'llm' },
];

// Grouped layout — Observability bundles the analytical read surfaces,
// Catalog bundles the write-adjacent screens. Leaf NavKey values are
// identical to NAV_ITEMS so no screen needs to change activeKey.
const NAV_TREE: NavNode[] = [
  { kind: 'leaf', key: 'chat', label: 'Stew', desc: 'Metadata wizard', to: '/chat', icon: 'chat' },
  {
    kind: 'group',
    key: 'observability',
    label: 'Observability',
    icon: 'observability',
    children: [
      { kind: 'leaf', key: 'viz', label: 'Visualizations', desc: '11 tabs', to: '/viz', icon: 'viz' },
      { kind: 'leaf', key: 'dq', label: 'Data quality', desc: 'Failures · gaps · risk', to: '/dq', icon: 'dq' },
      { kind: 'leaf', key: 'report', label: 'Executive report', desc: 'Markdown export', to: '/report', icon: 'doc' },
    ],
  },
  {
    kind: 'group',
    key: 'catalog',
    label: 'Catalog',
    icon: 'catalog',
    children: [
      { kind: 'leaf', key: 'sources', label: 'Data sources', desc: 'Connected services', to: '/data-sources', icon: 'sources' },
      { kind: 'leaf', key: 'review', label: 'Review queue', desc: 'Accept · edit · reject', to: '/review', icon: 'queue' },
    ],
  },
  { kind: 'leaf', key: 'llm', label: 'LLM setup', desc: 'Provider · model · keys', to: '/settings', icon: 'llm' },
];

// Restructured layout — Stew on top, Observability bundles DQ + the two LLM
// scans, Scans bundles the catalog-wide deep/PII passes, Visualizations and
// Review queue stay top-level. LLM setup, Executive report, Data sources,
// and Refresh metadata move to the TopBar (see TopBar.tsx).
const NAV_TREE_RESTRUCTURED: NavNode[] = [
  { kind: 'leaf', key: 'chat', label: 'Stew', desc: 'Metadata wizard', to: '/chat', icon: 'chat' },
  {
    kind: 'group',
    key: 'observability',
    label: 'Observability',
    icon: 'observability',
    children: [
      { kind: 'leaf', key: 'dq', label: 'Data quality', desc: 'Failures · gaps · risk', to: '/dq', icon: 'dq' },
      { kind: 'scan', scanKind: 'dq_recommend', icon: '💡', label: 'Recommend DQ tests', sub: 'One LLM call per table' },
      { kind: 'scan', scanKind: 'dq_explain', icon: '🧪', label: 'Explain DQ failures', sub: 'One LLM call per failure' },
    ],
  },
  {
    kind: 'group',
    key: 'scans',
    label: 'Scans',
    icon: 'scans',
    children: [
      { kind: 'scan', scanKind: 'deep_scan', icon: '⌕', label: 'Deep scan', sub: 'Stale · conflicts · quality' },
      { kind: 'scan', scanKind: 'pii_scan', icon: '⚑', label: 'PII scan', sub: 'Heuristic · zero-LLM' },
    ],
  },
  { kind: 'leaf', key: 'viz', label: 'Visualizations', desc: '11 tabs', to: '/viz', icon: 'viz' },
  { kind: 'leaf', key: 'review', label: 'Review queue', desc: 'Accept · edit · reject', to: '/review', icon: 'queue' },
];

const QUICK_ACTIONS: {
  kind: ScanKind;
  icon: string;
  label: string;
  sub: string;
}[] = [
  { kind: 'refresh', icon: '↻', label: 'Refresh metadata', sub: 'Pull from OpenMetadata' },
  { kind: 'deep_scan', icon: '⌕', label: 'Deep scan', sub: 'Stale · conflicts · quality' },
  { kind: 'pii_scan', icon: '⚑', label: 'PII scan', sub: 'Heuristic · zero-LLM' },
  { kind: 'dq_explain', icon: '🧪', label: 'Explain DQ failures', sub: 'One LLM call per failure' },
  { kind: 'dq_recommend', icon: '💡', label: 'Recommend DQ tests', sub: 'One LLM call per table' },
];

export function Sidebar({ activeKey }: { activeKey: NavKey }) {
  const composite = useQuery({
    queryKey: ['composite'],
    queryFn: getComposite,
    retry: false,
  });
  const pending = useQuery({
    queryKey: ['review'],
    queryFn: () => listReview(),
    retry: false,
  });
  const health = useQuery({
    queryKey: ['health'],
    queryFn: getHealth,
    refetchInterval: 30_000,
    retry: false,
  });

  return (
    <aside className="w-[280px] shrink-0 border-r border-slate-800/80 bg-slate-950/60 flex flex-col h-[calc(100vh-3.5rem)] sticky top-14">
      {composite.isLoading ? (
        <HealthHeroSkeleton />
      ) : composite.error || !composite.data ? (
        <HealthHeroError error={composite.error} />
      ) : (
        <HealthHero composite={composite.data} />
      )}
      <nav className="flex-1 px-3 py-4 overflow-y-auto scrollbar-thin">
        <SectionLabel>Workspace</SectionLabel>
        <div className="space-y-1">
          <WorkspaceNav activeKey={activeKey} pendingCount={pending.data?.rows.length} />
        </div>

        {SIDEBAR_NAV_LAYOUT !== 'restructured' && (
          <div className="mt-6">
            <SectionLabel>Quick actions</SectionLabel>
            <div className="space-y-1">
              {QUICK_ACTIONS.map((a) => (
                <QuickAction key={a.kind} {...a} />
              ))}
            </div>
          </div>
        )}
      </nav>

      <StatusFooter health={health.data} />
    </aside>
  );
}

// ── Health hero ────────────────────────────────────────────────────────────

function HealthHero({ composite }: { composite?: CompositeScore }) {
  const score = composite?.composite ?? 0;
  const scanned = composite?.scanned ?? false;

  const coverage: [string, Tone] = [pct(composite?.coverage), 'emerald'];
  const accuracy: [string, Tone] = scanned
    ? [pct(composite?.accuracy), 'amber']
    : ['—', 'red'];
  const consistency: [string, Tone] = [pct(composite?.consistency), 'amber'];
  const quality: [string, Tone] = scanned
    ? [pct(composite?.quality), 'amber']
    : ['—', 'red'];

  return (
    <div className="px-5 pt-5 pb-5 border-b border-slate-800/80">
      <div className="flex items-center justify-between mb-4">
        <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">
          Catalog health
        </div>
        <span className="chip">live</span>
      </div>
      <div className="flex flex-col items-center">
        <ScoreRing value={score} size={124} />
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-3 mt-5">
        <MetricMini
          label="Coverage"
          value={coverage[0]}
          tone={coverage[1]}
          delta={scanned ? 'documented' : 'needs refresh'}
        />
        <MetricMini
          label="Accuracy"
          value={accuracy[0]}
          tone={accuracy[1]}
          delta={scanned ? 'non-stale' : 'needs scan'}
        />
        <MetricMini
          label="Consistency"
          value={consistency[0]}
          tone={consistency[1]}
          delta="tag conflicts"
        />
        <MetricMini
          label="Quality"
          value={quality[0]}
          tone={quality[1]}
          delta={scanned ? 'desc score' : 'needs scan'}
        />
      </div>
      {/* Weighting bar — visualises composite's four weights (30/30/20/20). */}
      <div className="mt-5">
        <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5">
          Weighting
        </div>
        <div className="flex h-1.5 rounded-full overflow-hidden bg-slate-800">
          <div style={{ width: '30%' }} className="bg-emerald-500" />
          <div style={{ width: '30%' }} className="bg-emerald-500/40" />
          <div style={{ width: '20%' }} className="bg-cyan-500/80" />
          <div style={{ width: '20%' }} className="bg-cyan-500/30" />
        </div>
        <div className="flex text-[9px] font-mono text-slate-500 mt-1 justify-between">
          <span>cov 30</span>
          <span>acc 30</span>
          <span>con 20</span>
          <span>qua 20</span>
        </div>
      </div>
    </div>
  );
}

// Error state for the health hero — used when getComposite() fails (network
// down, DuckDB not hydrated, etc.). Without this, the skeleton-or-data branch
// would render a fake `0%` composite score, which reads as "real data" rather
// than "we couldn't fetch it" and quietly misrepresents catalog health.
function HealthHeroError({ error }: { error: unknown }) {
  const isNoMeta = error instanceof ApiError && error.code === 'no_metadata_loaded';
  const heading = isNoMeta ? 'Awaiting metadata' : 'Health unavailable';
  const body = isNoMeta
    ? 'Click Refresh metadata in the topbar to pull from OpenMetadata.'
    : error instanceof Error
      ? error.message
      : 'Composite score unavailable.';
  return (
    <div className="px-5 pt-5 pb-5 border-b border-slate-800/80">
      <div className="flex items-center justify-between mb-4">
        <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">
          Catalog health
        </div>
        <span className="chip amber">{isNoMeta ? 'idle' : 'error'}</span>
      </div>
      <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
        <div className="text-[12px] text-slate-200 font-medium">{heading}</div>
        <div className="text-[11px] text-slate-500 mt-1">{body}</div>
      </div>
    </div>
  );
}

function HealthHeroSkeleton() {
  return (
    <div className="px-5 pt-5 pb-5 border-b border-slate-800/80">
      <div className="flex items-center justify-between mb-4">
        <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">
          Catalog health
        </div>
        <Skeleton className="h-[18px] w-10" />
      </div>
      <div className="flex flex-col items-center">
        <SkeletonRing size={124} />
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-3 mt-5">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="rounded-lg border border-slate-800 bg-slate-900/40 p-3">
            <Skeleton className="h-[10px] w-14 mb-2" />
            <Skeleton className="h-[18px] w-12 mb-1.5" />
            <Skeleton className="h-[9px] w-16" />
          </div>
        ))}
      </div>
      <div className="mt-5">
        <Skeleton className="h-[10px] w-16 mb-1.5" />
        <Skeleton className="h-1.5 w-full rounded-full" />
      </div>
    </div>
  );
}

function pct(v: number | undefined): string {
  if (v == null || Number.isNaN(v)) return '—';
  return `${v.toFixed(1)}%`;
}

// ── Nav row ────────────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-2 text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-2">
      {children}
    </div>
  );
}

// Workspace nav — branches on SIDEBAR_NAV_LAYOUT. Flat path mirrors the
// original 7-row list; grouped/restructured paths nest screens (and, in
// 'restructured', scan triggers) under collapsible parent rows.
function WorkspaceNav({
  activeKey,
  pendingCount,
}: {
  activeKey: NavKey;
  pendingCount: number | undefined;
}) {
  const { pathname } = useLocation();
  const reviewBadge = pendingCount && pendingCount > 0 ? pendingCount : undefined;

  if (SIDEBAR_NAV_LAYOUT === 'flat') {
    return (
      <>
        {NAV_ITEMS.map((item) => (
          <NavLeafRow
            key={item.key}
            item={item}
            active={item.key === activeKey}
            badge={item.key === 'review' ? reviewBadge : undefined}
          />
        ))}
      </>
    );
  }

  const tree = SIDEBAR_NAV_LAYOUT === 'restructured' ? NAV_TREE_RESTRUCTURED : NAV_TREE;

  return (
    <>
      {tree.map((node) =>
        node.kind === 'leaf' ? (
          <NavLeafRow
            key={node.key}
            item={node}
            active={node.key === activeKey}
            badge={node.key === 'review' ? reviewBadge : undefined}
          />
        ) : (
          <NavGroupRow
            key={node.key}
            group={node}
            activeKey={activeKey}
            pathname={pathname}
            reviewBadge={reviewBadge}
          />
        ),
      )}
    </>
  );
}

function NavLeafRow({
  item,
  active,
  badge,
}: {
  item: NavLeaf;
  active: boolean;
  badge?: number;
}) {
  const base =
    'w-full text-left flex items-center gap-3 px-3 py-2.5 rounded-lg transition group border';
  const activeCls = 'bg-emerald-500/10 border-emerald-500/20';
  const idleCls = 'border-transparent hover:bg-slate-900/80';

  return (
    <Link
      to={item.to}
      className={`${base} ${active ? activeCls : idleCls}`}
    >
      <div
        className={`w-7 h-7 rounded-md flex items-center justify-center ${
          active ? 'bg-emerald-500/15' : 'bg-slate-900 group-hover:bg-slate-800'
        }`}
      >
        <NavIcon kind={item.icon} active={active} />
      </div>
      <div className="flex-1">
        <div className={`text-[13px] font-medium ${active ? 'text-white' : 'text-slate-300'}`}>
          {item.label}
        </div>
        <div className="text-[10px] text-slate-500">{item.desc}</div>
      </div>
      {badge ? (
        <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300">
          {badge}
        </span>
      ) : null}
    </Link>
  );
}

// Collapsible parent row. Auto-expands when any child's path matches the
// current URL; click toggles expansion (no routing). Badge bubbles up from
// child → parent when collapsed so pending work stays visible.
function NavGroupRow({
  group,
  activeKey,
  pathname,
  reviewBadge,
}: {
  group: NavGroup;
  activeKey: NavKey;
  pathname: string;
  reviewBadge: number | undefined;
}) {
  const containsActive = useMemo(
    () =>
      group.children.some(
        (c) => c.kind === 'leaf' && (c.to === pathname || c.key === activeKey),
      ),
    [group.children, pathname, activeKey],
  );
  const [expanded, setExpanded] = useState(containsActive);
  // Re-expand when navigation lands on a child of this group.
  useEffect(() => {
    if (containsActive) setExpanded(true);
  }, [containsActive]);

  // When collapsed, show the child badge (currently only Review queue) on
  // the parent so count visibility isn't lost.
  const hasReviewChild = group.children.some(
    (c) => c.kind === 'leaf' && c.key === 'review',
  );
  const parentBadge = !expanded && hasReviewChild ? reviewBadge : undefined;

  // Mixed children get a generic label since "screens" lies when half are
  // scan triggers. Pure-leaf groups keep the screen count.
  const allLeaves = group.children.every((c) => c.kind === 'leaf');
  const subLabel = allLeaves
    ? `${group.children.length} screens`
    : `${group.children.length} items`;

  const base =
    'w-full text-left flex items-center gap-3 px-3 py-2.5 rounded-lg transition group border';
  const idleCls = 'border-transparent hover:bg-slate-900/80';
  const hintCls =
    containsActive && !expanded ? 'border-emerald-500/15 bg-emerald-500/[0.04]' : idleCls;

  return (
    <div>
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        aria-expanded={expanded}
        aria-controls={`nav-group-${group.key}`}
        className={`${base} ${hintCls}`}
      >
        <div className="w-7 h-7 rounded-md flex items-center justify-center bg-slate-900 group-hover:bg-slate-800">
          <NavIcon kind={group.icon} active={containsActive && !expanded} />
        </div>
        <div className="flex-1">
          <div className="text-[13px] font-medium text-slate-300 flex items-center gap-2">
            {group.label}
            {containsActive && !expanded && (
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" aria-hidden />
            )}
          </div>
          <div className="text-[10px] text-slate-500">{subLabel}</div>
        </div>
        {parentBadge ? (
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300">
            {parentBadge}
          </span>
        ) : null}
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={`text-slate-500 transition-transform ${expanded ? 'rotate-90' : ''}`}
          aria-hidden
        >
          <polyline points="9 18 15 12 9 6" />
        </svg>
      </button>
      {expanded && (
        <div id={`nav-group-${group.key}`} className="mt-1 space-y-1 pl-3">
          {group.children.map((child) =>
            child.kind === 'leaf' ? (
              <NavLeafRow
                key={child.key}
                item={child}
                active={child.key === activeKey}
                badge={child.key === 'review' ? reviewBadge : undefined}
              />
            ) : (
              <QuickAction
                key={child.scanKind}
                kind={child.scanKind}
                icon={child.icon}
                label={child.label}
                sub={child.sub}
              />
            ),
          )}
        </div>
      )}
    </div>
  );
}

// ── Quick action (scan row with inline progress) ───────────────────────────

interface QuickState {
  running: boolean;
  step: number;
  total: number;
  label: string;
  err: string | null;
}

const INITIAL_STATE: QuickState = {
  running: false,
  step: 0,
  total: 0,
  label: '',
  err: null,
};

function QuickAction({
  kind,
  icon,
  label,
  sub,
  body,
}: {
  kind: ScanKind;
  icon: string;
  label: string;
  sub: string;
  body?: BulkDocBody;
}) {
  const qc = useQueryClient();
  const [state, setState] = useState<QuickState>(INITIAL_STATE);
  // Abort in-flight scans on unmount (route change, app close) so the
  // backend's dedicated scan executor doesn't accumulate orphaned workers.
  const abortRef = useRef<AbortController | null>(null);
  // Sandbox: trap 402 byo_key_required → BYO-key modal. Cross-visitor
  // scan polling: disable button when ANYONE's scan is active and this
  // button hasn't kicked it off itself (state.running covers self-runs).
  const byoKey = useByoKeyTrap();
  const sandbox = useSandbox();
  const { active: activeScan } = useActiveScan();
  // refresh is intentionally NOT sandbox-blocked (Patch 1 of the
  // post-deploy round): it hydrates the read-only DuckDB cache, which
  // the UI cannot render anything without. Per-IP rate limit at Caddy
  // + the per-kind try_start_scan lock bound the abuse vector.
  const otherScanRunning = sandbox && !!activeScan && !state.running;

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const run = useMutation({
    mutationFn: async () => {
      abortRef.current?.abort();
      const ctrl = new AbortController();
      abortRef.current = ctrl;

      setState({ ...INITIAL_STATE, running: true, label: 'Starting…' });
      try {
        await streamScan(
          kind,
          (frame: ScanFrame) => {
            setState((prev) => {
              if (frame.type === 'progress') {
                return {
                  ...prev,
                  step: frame.step,
                  total: frame.total,
                  label: frame.label,
                };
              }
              if (frame.type === 'done') {
                toast.success(`${label} done`, {
                  description: summariseCounts(kind, frame.counts),
                });
                return { ...prev, running: false };
              }
              toast.error(`${label} failed`, { description: frame.message });
              return { ...prev, running: false, err: frame.message };
            });
          },
          body,
          ctrl.signal,
        );
      } catch (e) {
        if (e instanceof DOMException && e.name === 'AbortError') return;
        if (byoKey.trap(e)) {
          setState({ ...INITIAL_STATE });
          return;
        }
        throw e;
      }
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['composite'] });
      qc.invalidateQueries({ queryKey: ['coverage'] });
      qc.invalidateQueries({ queryKey: ['review'] });
      qc.invalidateQueries({ queryKey: ['viz'] });
      qc.invalidateQueries({ queryKey: ['dq'] });
      qc.invalidateQueries({ queryKey: ['scan-status'] });
      qc.invalidateQueries({ queryKey: ['scans', 'active'] });
    },
    onError: (e) => {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`${label} failed`, { description: msg });
      setState({ ...INITIAL_STATE, err: msg });
    },
  });

  const pctDone = state.running && state.total > 0
    ? Math.min(100, (state.step / state.total) * 100)
    : 0;

  // Tooltip surfaces WHY the button is disabled (only "another visitor's
  // scan is running" remains as a non-self disable reason after the
  // refresh-ungating).
  const blockReason = otherScanRunning
    ? `Another visitor is running a ${activeScan?.kind ?? 'scan'} — wait ~30s`
    : null;
  const disabled = state.running || otherScanRunning;
  return (
    <button
      type="button"
      onClick={() => run.mutate()}
      disabled={disabled}
      title={blockReason ?? undefined}
      className="w-full text-left flex items-center gap-3 px-3 py-2 rounded-lg border border-slate-800 bg-slate-900/40 hover:border-emerald-500/30 hover:bg-slate-900 transition disabled:opacity-70 disabled:cursor-not-allowed"
    >
      <div className="w-6 h-6 rounded bg-slate-800 text-emerald-400 flex items-center justify-center text-sm">
        {icon}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-[12px] text-slate-200 truncate">
          {state.running ? 'Running…' : label}
        </div>
        {state.running ? (
          <div className="mt-1">
            <div className="h-[2px] w-full bg-slate-800 rounded overflow-hidden">
              <div
                className="h-full bg-emerald-500/70 transition-all"
                style={{ width: `${pctDone}%` }}
              />
            </div>
            {state.total > 0 && (
              <div className="text-[9px] font-mono text-slate-500 truncate mt-0.5">
                {state.step}/{state.total} · {state.label}
              </div>
            )}
          </div>
        ) : state.err ? (
          <div className="text-[10px] text-red-300 truncate">⚠ {state.err}</div>
        ) : (
          <div className="text-[10px] text-slate-500 truncate">{sub}</div>
        )}
      </div>
    </button>
  );
}

// ── Status footer ──────────────────────────────────────────────────────────

function StatusFooter({ health }: { health?: HealthResponse }) {
  const om = health?.om ?? false;
  const llm = health?.llm ?? false;
  return (
    <div className="border-t border-slate-800/80 px-5 py-3">
      <div className="flex items-center justify-between text-[11px]">
        <div className="flex items-center gap-2">
          <Dot on={om} />
          <span className="text-slate-400">OpenMetadata</span>
          {health?.version && (
            <span className="text-slate-600 font-mono">{health.version}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Dot on={llm} />
          <span className="text-slate-400">LLM</span>
        </div>
      </div>
    </div>
  );
}

function Dot({ on }: { on: boolean }) {
  return (
    <span
      className={
        'w-1.5 h-1.5 rounded-full pulse-dot ' + (on ? 'bg-emerald-400' : 'bg-slate-600')
      }
    />
  );
}

// Shape a one-line summary for the toast description, tailored per scan so
// the user sees the metric that actually matters for that kind (tables for
// refresh, explanations for dq_explain, etc.) instead of a generic count dump.
// Keys mirror what the engines return — see cleaning.run_pii_scan,
// stewardship.run_dq_recommendations, duck.refresh_all, etc.
function summariseCounts(kind: ScanKind, counts: Record<string, unknown>): string {
  const n = (k: string): number | null => {
    const v = counts[k];
    if (typeof v === 'number') return v;
    if (typeof v === 'string') {
      const parsed = Number(v);
      return Number.isFinite(parsed) ? parsed : null;
    }
    return null;
  };
  switch (kind) {
    case 'refresh': {
      const t = n('om_tables');
      const c = n('om_columns');
      if (t != null && c != null) return `${t} tables · ${c} columns`;
      return 'metadata refreshed';
    }
    case 'deep_scan': {
      const analyzed = n('analyzed');
      const acc = n('accuracy_pct');
      const qual = n('quality_avg_1_5');
      if (analyzed != null && acc != null && qual != null) {
        return `${analyzed} scanned · acc ${acc.toFixed(0)}% · qual ${qual.toFixed(1)}/5`;
      }
      return 'deep scan complete';
    }
    case 'pii_scan': {
      const scanned = n('scanned');
      const sensitive = n('sensitive');
      const gaps = n('gaps');
      if (scanned != null) {
        return `${scanned} columns · ${sensitive ?? 0} sensitive · ${gaps ?? 0} gaps`;
      }
      return 'PII scan complete';
    }
    case 'dq_explain': {
      const expl = n('explained');
      const total = n('total');
      if (expl != null && total != null) return `${expl}/${total} failures explained`;
      if (expl != null) return `${expl} explanations`;
      return 'DQ failures explained';
    }
    case 'dq_recommend': {
      const total = n('total');
      const crit = n('critical');
      if (total != null) {
        return `${total} recommendations${crit ? ` · ${crit} critical` : ''}`;
      }
      return 'DQ recommendations ready';
    }
    case 'bulk_doc': {
      const drafted = n('drafted');
      const total = n('total');
      if (drafted != null && total != null) return `${drafted}/${total} tables documented`;
      return 'auto-doc complete';
    }
    default:
      return '';
  }
}

