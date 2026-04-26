/**
 * Composite-score donut. Lifted from metasift+/MetaSift App.html::ScoreRing
 * (L275-L293) — gradient stroke (ring via #ringGrad defined in index.html)
 * with the score + "Composite" label + delta stacked inside.
 *
 * Kept the existing `value` prop name (mapped to `score` in the mockup) so
 * existing callers don't need to rename.
 */

interface Props {
  value: number;
  size?: number;
  delta?: string;
}

export function ScoreRing({ value, size = 132, delta }: Props) {
  const clamped = Math.max(0, Math.min(100, value));
  const r = (size - 12) / 2;
  const C = 2 * Math.PI * r;
  const dash = C * (clamped / 100);

  return (
    <div
      className="relative flex items-center justify-center"
      style={{ width: size, height: size }}
      role="img"
      aria-label={`Composite score: ${clamped.toFixed(1)} out of 100`}
    >
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          strokeWidth={8}
          className="score-ring-bg"
          fill="none"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          strokeWidth={8}
          fill="none"
          strokeLinecap="round"
          className="score-ring-fg"
          strokeDasharray={`${dash} ${C}`}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
        <div className="text-[10px] uppercase tracking-wider text-slate-500">Composite</div>
        <div className="text-2xl font-bold text-white leading-none mt-0.5">
          {clamped.toFixed(1)}
          <span className="text-sm text-slate-400">%</span>
        </div>
        {delta && <div className="text-[10px] text-amber-300/80 mt-1 font-medium">{delta}</div>}
      </div>
    </div>
  );
}
