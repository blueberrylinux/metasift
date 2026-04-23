/**
 * Small metric tile for the dashboard grid. Renders a label + percentage or
 * em-dash placeholder. `pending` signals "deep scan hasn't run yet, this
 * number is meaningless" — we show an em-dash and a muted hint instead of
 * a misleading 0%.
 */

interface Props {
  label: string;
  value: number | null;
  /** When true, display "—" and a hint that the deep scan hasn't run. */
  pending?: boolean;
  hint?: string;
}

function toneFor(value: number | null): string {
  if (value === null) return 'text-ink-soft';
  if (value >= 75) return 'text-accent-soft';
  if (value >= 50) return 'text-warn-soft';
  return 'text-error-soft';
}

export function MetricCard({ label, value, pending = false, hint }: Props) {
  const displayValue = pending || value === null ? '—' : `${value.toFixed(1)}%`;
  const tone = pending ? 'text-ink-soft' : toneFor(value);

  return (
    <div className="rounded-xl border border-ink-border bg-ink-panel/50 p-5 flex flex-col gap-2">
      <span className="text-ink-dim text-tiny uppercase tracking-widest">{label}</span>
      <span className={`font-mono font-bold text-3xl tracking-tight ${tone}`}>
        {displayValue}
      </span>
      {(hint || pending) && (
        <span className="text-ink-dim text-mini">
          {pending ? 'Run deep scan to compute' : hint}
        </span>
      )}
    </div>
  );
}
