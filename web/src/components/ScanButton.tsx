/**
 * One scan trigger — button + inline progress + result summary.
 *
 * Mirrors a sidebar entry from the Streamlit app. Frame handling:
 *   - progress → updates step/total/label for the progress bar
 *   - done     → renders a success line with the counts summary
 *   - error    → renders an error line with the message
 *
 * After done/error, the button re-enables and the counts stay visible so
 * the user has a persistent "last time I ran this" hint. The sidebar
 * `/scans/status` query is invalidated on completion so the "N min ago"
 * label elsewhere refreshes without a page reload.
 */

import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { ApiError, streamScan, type BulkDocBody, type ScanKind } from '../lib/api';

interface State {
  running: boolean;
  step: number;
  total: number;
  label: string;
  summary: string | null;
  error: string | null;
}

const INITIAL: State = {
  running: false,
  step: 0,
  total: 0,
  label: '',
  summary: null,
  error: null,
};

export function ScanButton({
  kind,
  icon,
  label,
  summarize,
  help,
  body,
  compact,
}: {
  kind: ScanKind;
  icon: string;
  label: string;
  /** Turns the engine's `counts` dict into a one-line success summary. */
  summarize: (counts: Record<string, unknown>) => string;
  help?: string;
  body?: BulkDocBody;
  compact?: boolean;
}) {
  const qc = useQueryClient();
  const [state, setState] = useState<State>(INITIAL);

  const run = async () => {
    setState({ ...INITIAL, running: true, label: 'Starting…' });
    try {
      await streamScan(kind, (frame) => {
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
            return {
              ...prev,
              running: false,
              summary: summarize(frame.counts),
              error: null,
            };
          }
          // frame.type === 'error' — clear any leftover summary from a prior
          // successful run so the two states don't render stacked on retry.
          return { ...prev, running: false, summary: null, error: frame.message };
        });
      }, body);
    } catch (e) {
      const msg = e instanceof ApiError ? `${e.code}: ${e.message}` : String(e);
      setState({ ...INITIAL, error: msg });
    } finally {
      // Refresh review queue since a completed scan usually populates fresh
      // suggestions / failure explanations, and every viz figure since most
      // tabs read from the tables the scans write.
      qc.invalidateQueries({ queryKey: ['review'] });
      qc.invalidateQueries({ queryKey: ['viz'] });
      // Reserved touchpoint: once a ScanStatusBadge subscribes to
      // ['scan-status'] via getScanStatus(), this will drive the "last scan
      // N min ago" hint. Harmless no-op until then.
      qc.invalidateQueries({ queryKey: ['scan-status'] });
    }
  };

  const progressPct =
    state.running && state.total > 0 ? Math.min(100, (state.step / state.total) * 100) : 0;

  return (
    <div className="flex flex-col gap-1">
      <button
        onClick={run}
        disabled={state.running}
        title={help}
        className={
          'w-full text-left rounded-md px-3 py-2 text-sm font-mono transition-colors border ' +
          (state.running
            ? 'bg-accent/20 text-accent-soft border-accent/30 cursor-wait'
            : 'bg-ink-panel/60 hover:bg-ink-panel text-ink-text border-ink-border hover:border-accent/40')
        }
      >
        <span className="mr-1.5">{icon}</span>
        {state.running ? 'Running…' : label}
      </button>
      {state.running && (
        <div className="px-1">
          <div className="h-1 w-full bg-ink-panel rounded overflow-hidden">
            <div
              className="h-full bg-accent/50 transition-all"
              style={{ width: `${progressPct}%` }}
            />
          </div>
          {state.total > 0 && (
            <div className="text-mini font-mono text-ink-dim mt-0.5 truncate" title={state.label}>
              {state.step}/{state.total} · {state.label}
            </div>
          )}
        </div>
      )}
      {!state.running && state.summary && !compact && (
        <div className="text-mini font-mono text-accent-soft px-1">✓ {state.summary}</div>
      )}
      {!state.running && state.error && (
        <div className="text-mini font-mono text-error-soft px-1" title={state.error}>
          ⚠ {state.error}
        </div>
      )}
    </div>
  );
}
