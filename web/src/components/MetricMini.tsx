/**
 * Compact metric tile — label / value / delta stacked. Lifted from
 * metasift+/MetaSift App.html::MetricMini (L295-L309). Used in the
 * Sidebar's 2×2 health grid.
 */

export type Tone = 'slate' | 'emerald' | 'amber' | 'red';

const TONE_CLS: Record<Tone, string> = {
  slate: 'text-slate-200',
  emerald: 'text-emerald-300',
  amber: 'text-amber-300',
  red: 'text-red-300',
};

export function MetricMini({
  label,
  value,
  delta,
  tone = 'slate',
}: {
  label: string;
  value: string;
  delta?: string;
  tone?: Tone;
}) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`font-semibold text-lg ${TONE_CLS[tone]}`}>{value}</div>
      {delta && <div className="text-[10px] text-slate-500 font-mono">{delta}</div>}
    </div>
  );
}
