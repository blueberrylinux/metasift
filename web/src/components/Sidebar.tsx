/**
 * Sidebar rebuilt from metasift+/MetaSift App.html::Sidebar (L311-L410).
 * Structure:
 *   1. Composite health hero — ScoreRing + 2x2 MetricMini grid + weighting bar
 *   2. Workspace nav — 6 NavIcons (chat / queue / viz / dq / doc / llm)
 *   3. Quick actions — 5 scan trigger rows with inline progress
 *   4. Footer — OM + LLM connection status pulses
 *
 * Everything lifts hooks from the same query surfaces the screens use
 * (`['composite']`, `['review']`, `['health']`) so values stay in sync
 * without a bespoke sidebar query.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

import {
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
import { MetricMini, type Tone } from './MetricMini';
import { NavIcon, type NavIconKind } from './NavIcon';
import { ScoreRing } from './ScoreRing';
import { Skeleton, SkeletonRing } from './Skeleton';

export type NavKey = 'chat' | 'review' | 'sources' | 'viz' | 'dq' | 'report' | 'llm';

interface NavItem {
  key: NavKey;
  label: string;
  desc: string;
  to: string;
  icon: NavIconKind;
}

const NAV_ITEMS: NavItem[] = [
  { key: 'chat', label: 'Stew', desc: 'Metadata wizard', to: '/chat', icon: 'chat' },
  { key: 'review', label: 'Review queue', desc: 'Accept · edit · reject', to: '/review', icon: 'queue' },
  { key: 'sources', label: 'Data sources', desc: 'Connected services', to: '/data-sources', icon: 'sources' },
  { key: 'viz', label: 'Visualizations', desc: '11 tabs', to: '/viz', icon: 'viz' },
  { key: 'dq', label: 'Data quality', desc: 'Failures · gaps · risk', to: '/dq', icon: 'dq' },
  { key: 'report', label: 'Executive report', desc: 'Markdown export', to: '/report', icon: 'doc' },
  { key: 'llm', label: 'LLM setup', desc: 'Provider · model · keys', to: '/settings', icon: 'llm' },
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
      ) : (
        <HealthHero composite={composite.data} />
      )}
      <nav className="flex-1 px-3 py-4 overflow-y-auto scrollbar-thin">
        <SectionLabel>Workspace</SectionLabel>
        <div className="space-y-1">
          {NAV_ITEMS.map((item) => {
            const active = item.key === activeKey;
            const badge =
              item.key === 'review' ? pending.data?.rows.length ?? undefined : undefined;
            return (
              <NavRow
                key={item.key}
                item={item}
                active={active}
                badge={badge && badge > 0 ? badge : undefined}
              />
            );
          })}
        </div>

        <div className="mt-6">
          <SectionLabel>Quick actions</SectionLabel>
          <div className="space-y-1">
            {QUICK_ACTIONS.map((a) => (
              <QuickAction key={a.kind} {...a} />
            ))}
          </div>
        </div>
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

function NavRow({ item, active, badge }: { item: NavItem; active: boolean; badge?: number }) {
  const base =
    'w-full text-left flex items-center gap-3 px-3 py-2.5 rounded-lg transition group border';
  const activeCls = 'bg-emerald-500/10 border-emerald-500/20';
  const idleCls = 'border-transparent hover:bg-slate-900/80';

  return (
    <Link to={item.to} className={`${base} ${active ? activeCls : idleCls}`}>
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

  return (
    <button
      type="button"
      onClick={() => run.mutate()}
      disabled={state.running}
      className="w-full text-left flex items-center gap-3 px-3 py-2 rounded-lg border border-slate-800 bg-slate-900/40 hover:border-emerald-500/30 hover:bg-slate-900 transition disabled:opacity-70 disabled:cursor-wait"
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

