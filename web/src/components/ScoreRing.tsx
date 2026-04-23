/**
 * Composite-score donut. SVG stroke-dashoffset trick — no chart dependency.
 *
 * The ring reads `value` (0-100) and sweeps proportionally. `label` sits
 * beneath the number for context ("Composite score"). The color ramp is
 * keyed to the score: green for healthy, amber for middling, red for bad.
 * Thresholds match the Streamlit version's gauge bands so the two UIs
 * agree visually during the port.
 */

interface Props {
  value: number;
  label?: string;
  size?: number;
  strokeWidth?: number;
}

function colorFor(score: number): string {
  if (score >= 75) return '#10b981'; // accent
  if (score >= 50) return '#f59e0b'; // warn
  return '#ef4444'; // error
}

export function ScoreRing({
  value,
  label = 'Composite score',
  size = 200,
  strokeWidth = 14,
}: Props) {
  const clamped = Math.max(0, Math.min(100, value));
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const dash = (clamped / 100) * circumference;
  const color = colorFor(clamped);

  return (
    <div
      className="relative"
      style={{ width: size, height: size }}
      role="img"
      aria-label={`${label}: ${clamped.toFixed(1)} out of 100`}
    >
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="rgba(30,41,59,0.8)"
          strokeWidth={strokeWidth}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={`${dash} ${circumference - dash}`}
          style={{ transition: 'stroke-dasharray 500ms ease-out' }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
        <span
          className="font-mono font-bold tracking-tight leading-none"
          style={{ color, fontSize: size * 0.22 }}
        >
          {clamped.toFixed(1)}
        </span>
        <span className="text-ink-dim text-tiny uppercase tracking-widest mt-2">
          {label}
        </span>
      </div>
    </div>
  );
}
