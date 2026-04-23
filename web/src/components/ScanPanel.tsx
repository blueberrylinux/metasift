/**
 * Stacked scan triggers for the Sidebar. Four entries — the same
 * Streamlit had in its sidebar, minus bulk-doc (agent-triggered) and
 * refresh (which lives on the Dashboard and uses the sync endpoint).
 *
 * Each button is self-contained: its own progress bar + result line.
 * Completion invalidates ['review'] + ['scan-status'] so the queue
 * screen and the "last scan N min ago" hint refresh automatically.
 */

import { ScanButton } from './ScanButton';

type CountsLike = Record<string, unknown>;

const n = (c: CountsLike, k: string): number => {
  const v = c[k];
  return typeof v === 'number' ? v : 0;
};

export function ScanPanel() {
  return (
    <div className="flex flex-col gap-2 pt-2">
      <div className="text-mini font-mono uppercase tracking-wider text-ink-dim px-1">Scans</div>

      <ScanButton
        kind="deep_scan"
        icon="🔬"
        label="Deep scan"
        help="Stale-description + quality-scoring pass (LLM calls — ~30s)"
        summarize={(c) =>
          `${n(c, 'analyzed')} tables · accuracy ${n(c, 'accuracy_pct')}% · quality ${n(c, 'quality_avg_1_5')}/5`
        }
        compact
      />

      <ScanButton
        kind="pii_scan"
        icon="🔐"
        label="PII scan"
        help="Heuristic PII classification (fast — no LLM)"
        summarize={(c) =>
          `${n(c, 'scanned')} columns · ${n(c, 'sensitive')} sensitive · ${n(c, 'gaps')} gap(s)`
        }
        compact
      />

      <ScanButton
        kind="dq_recommend"
        icon="💡"
        label="Recommend DQ"
        help="Per-table DQ test recommendations (LLM per table)"
        summarize={(c) => `${n(c, 'total')} recs · 🚨 ${n(c, 'critical')} 💡 ${n(c, 'recommended')} ✨ ${n(c, 'nice')}`}
        compact
      />

      <ScanButton
        kind="dq_explain"
        icon="🧪"
        label="Explain DQ"
        help="LLM-written explanations for failing DQ tests"
        summarize={(c) => `${n(c, 'explained')}/${n(c, 'total')} failures explained`}
        compact
      />
    </div>
  );
}
