/**
 * Sticky top header. Lifted from metasift+/MetaSift App.html::TopBar
 * (L215-L249). Logo refresh button dropped (no logo picker surface in the
 * port); Welcome Guide button is a placeholder for slice 2 to wire into
 * the WelcomeModal.
 *
 * Route shortcuts (Data sources / Executive report / LLM setup) and the
 * Refresh metadata scan trigger are gated behind TOPBAR_NAV_BUTTONS so we
 * can flip back to the minimal header without losing the code.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

import { getHealth, type ScanFrame, streamScan } from '../lib/api';
import { useSandbox } from '../lib/sandbox';
import { useByoKeyTrap } from './ByoKeyModal';
import { LogoM } from './LogoM';

// Flip to 'classic' to drop the route shortcuts + refresh button and
// restore the old Welcome guide / Docs only header.
const TOPBAR_NAV_BUTTONS: 'classic' | 'expanded' = 'expanded';

export function TopBar({ onOpenWelcome }: { onOpenWelcome?: () => void }) {
  // Pull live health for the version badge — replaces the hardcoded
  // `openmetadata.local · admin` strip which was wrong as soon as the user
  // pointed at a different OM host. Once JWT-from-UI lands the host can come
  // from `/om/config` so we can show it here too.
  const health = useQuery({
    queryKey: ['health'],
    queryFn: getHealth,
    refetchInterval: 30_000,
    retry: false,
  });
  const omReachable = health.data?.om;
  const omVersion = health.data?.version;

  return (
    <div className="h-14 border-b border-slate-800/80 backdrop-blur-md bg-slate-950/70 flex items-center justify-between px-5 sticky top-0 z-30">
      <div className="flex items-center gap-3">
        <LogoM size={44} />
        <div>
          <div className="text-[13px] font-bold text-white tracking-tight leading-none">
            MetaSift
          </div>
          <div className="text-[10px] text-slate-500 mt-0.5 leading-none">
            AI metadata analyst &amp; steward
          </div>
        </div>
        <div className="ml-5 h-5 w-px bg-slate-800" />
        <div className="flex items-center gap-2 text-[11px] text-slate-400">
          <span
            className={
              'w-1.5 h-1.5 rounded-full ' +
              (omReachable ? 'bg-emerald-400' : 'bg-slate-600')
            }
            aria-label={omReachable ? 'OpenMetadata reachable' : 'OpenMetadata unreachable'}
          />
          <span className="font-mono">OpenMetadata</span>
          {omVersion && (
            <span className="font-mono text-slate-500">{omVersion}</span>
          )}
        </div>
      </div>
      <div className="flex items-center gap-2">
        {TOPBAR_NAV_BUTTONS === 'expanded' && (
          <>
            <RefreshMetadataButton />
            <NavLink to="/settings">LLM setup</NavLink>
            <NavLink to="/report">Executive report</NavLink>
            <NavLink to="/data-sources">Data sources</NavLink>
            <div className="h-5 w-px bg-slate-800 mx-1" />
          </>
        )}
        <button
          onClick={onOpenWelcome}
          className="text-[11px] px-2.5 py-1 rounded-md text-cyan-300 border border-cyan-500/20 bg-cyan-500/5 hover:bg-cyan-500/10 transition"
        >
          ⓘ Welcome guide
        </button>
        <a
          href="https://github.com/blueberrylinux/metasift"
          target="_blank"
          rel="noreferrer"
          className="text-[11px] px-2.5 py-1 rounded-md text-slate-300 hover:text-white hover:bg-slate-800/60 transition"
        >
          Docs
        </a>
      </div>
    </div>
  );
}

// Sized larger than Welcome guide / Docs (12px / py-1.5) for visual weight,
// no leading icon — middle-ground between the chip-style and a full nav row.
function NavLink({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <Link
      to={to}
      className="text-[12px] px-3 py-1.5 rounded-md text-slate-300 border border-slate-800 bg-slate-900/40 hover:text-white hover:bg-slate-800/60 hover:border-slate-700 transition"
    >
      {children}
    </Link>
  );
}

// Topbar variant of the sidebar's QuickAction. Shows inline progress
// percent + step/total while a refresh is in flight; toasts on done/error.
// Uses a fresh AbortController per click so a re-click cancels the previous
// run cleanly.
function RefreshMetadataButton() {
  const qc = useQueryClient();
  const abortRef = useRef<AbortController | null>(null);
  const [running, setRunning] = useState(false);
  const [step, setStep] = useState(0);
  const [total, setTotal] = useState(0);
  const [label, setLabel] = useState('');
  // Refresh is a sandbox-gated write endpoint — disable the button entirely
  // when sandbox=true so the user doesn't waste a click on a guaranteed
  // 403 sandbox_read_only. Tooltip explains.
  const sandbox = useSandbox();
  // Trap any 402 byo_key_required (would only fire if a future, non-write
  // refresh path is added; harmless in current code).
  const byoKey = useByoKeyTrap();

  // Abort if the topbar unmounts (eg. tab close).
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

      setRunning(true);
      setStep(0);
      setTotal(0);
      setLabel('Starting…');

      try {
        await streamScan(
          'refresh',
          (frame: ScanFrame) => {
            if (frame.type === 'progress') {
              setStep(frame.step);
              setTotal(frame.total);
              setLabel(frame.label);
            } else if (frame.type === 'done') {
              const t = numberish(frame.counts['om_tables']);
              const c = numberish(frame.counts['om_columns']);
              toast.success('Refresh metadata done', {
                description:
                  t != null && c != null
                    ? `${t} tables · ${c} columns`
                    : 'metadata refreshed',
              });
              setRunning(false);
            } else {
              toast.error('Refresh metadata failed', { description: frame.message });
              setRunning(false);
            }
          },
          undefined,
          ctrl.signal,
        );
      } catch (e) {
        if (e instanceof DOMException && e.name === 'AbortError') return;
        if (byoKey.trap(e)) {
          setRunning(false);
          return;
        }
        throw e;
      }
    },
    onSettled: () => {
      // Defensive reset — the AbortError early-return in mutationFn skips
      // setRunning(false), and onSettled fires after both success and error,
      // so this guarantees the button never gets trapped in 'running'.
      setRunning(false);
      qc.invalidateQueries({ queryKey: ['composite'] });
      qc.invalidateQueries({ queryKey: ['coverage'] });
      qc.invalidateQueries({ queryKey: ['review'] });
      qc.invalidateQueries({ queryKey: ['viz'] });
      qc.invalidateQueries({ queryKey: ['dq'] });
      qc.invalidateQueries({ queryKey: ['data-sources'] });
    },
    onError: (e) => {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error('Refresh metadata failed', { description: msg });
      setRunning(false);
    },
  });

  const pct = running && total > 0 ? Math.min(100, (step / total) * 100) : 0;

  return (
    <button
      type="button"
      onClick={() => run.mutate()}
      disabled={running || sandbox}
      title={
        sandbox
          ? 'Read-only sandbox — refresh runs nightly via systemd timer'
          : running
            ? `${step}/${total} · ${label}`
            : 'Pull latest metadata from OpenMetadata'
      }
      className="text-[12px] px-3 py-1.5 rounded-md text-slate-200 border border-emerald-500/20 bg-emerald-500/5 hover:text-white hover:bg-emerald-500/10 hover:border-emerald-500/30 transition disabled:cursor-not-allowed disabled:opacity-50 flex items-center gap-2 min-w-[170px]"
    >
      <span className={running ? 'animate-spin' : ''}>↻</span>
      {running ? (
        <span className="flex-1 flex flex-col items-stretch gap-0.5">
          <span className="flex items-center justify-between gap-2 text-[10px] font-mono text-slate-300">
            <span className="truncate">{label || 'Refreshing…'}</span>
            <span className="text-slate-500">
              {total > 0 ? `${pct.toFixed(0)}%` : '…'}
            </span>
          </span>
          <span className="h-[2px] w-full bg-slate-800 rounded overflow-hidden">
            <span
              className="block h-full bg-emerald-500/70 transition-all"
              style={{ width: `${pct}%` }}
            />
          </span>
        </span>
      ) : (
        <span>Refresh metadata</span>
      )}
    </button>
  );
}

function numberish(v: unknown): number | null {
  if (typeof v === 'number') return v;
  if (typeof v === 'string') {
    const parsed = Number(v);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}
