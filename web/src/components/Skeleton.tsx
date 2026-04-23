/**
 * Shared skeleton primitive. Uses Tailwind's built-in `animate-pulse`
 * plus a slate gradient so loading placeholders match the app's dark
 * palette without a bespoke keyframe.
 *
 * Two variants are exposed as named helpers so call sites read cleanly:
 *   <Skeleton className="h-4 w-32" />         generic bar
 *   <SkeletonRing size={124} />               score-ring placeholder
 *   <SkeletonList rows={5} height={72} />     pre-sized list rows
 */

interface SkeletonProps {
  className?: string;
  style?: React.CSSProperties;
}

export function Skeleton({ className = '', style }: SkeletonProps) {
  return (
    <div
      aria-hidden
      style={style}
      className={
        'animate-pulse rounded bg-gradient-to-r from-slate-800/80 via-slate-700/60 to-slate-800/80 ' +
        className
      }
    />
  );
}

export function SkeletonRing({ size = 124 }: { size?: number }) {
  return (
    <div
      aria-hidden
      className="animate-pulse rounded-full bg-gradient-to-br from-slate-800/80 via-slate-700/40 to-slate-800/80"
      style={{ width: size, height: size }}
    />
  );
}

export function SkeletonList({
  rows = 5,
  height = 72,
  gap = 0,
}: {
  rows?: number;
  height?: number;
  gap?: number;
}) {
  return (
    <div className="flex flex-col" style={{ gap }}>
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="w-full" style={{ height }} />
      ))}
    </div>
  );
}
