/**
 * Click-to-copy wrapper for 4-part OpenMetadata FQNs.
 *
 * Copies the full FQN regardless of what's visually rendered, so the
 * `short` variant stays scannable in dense list rows without losing the
 * canonical `service.database.schema.table` string that the clipboard
 * needs. Success state is transient (1.5s) and accompanied by a subtle
 * toast so the action is visible even when the row scrolls out.
 */

import { useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

interface Props {
  fqn: string;
  // short: trim to last three segments (postgres.sales.refund_events).
  // full:  render the whole FQN.
  variant?: 'short' | 'full';
  // Passed through so callers can match the type hierarchy of their context
  // (list row text vs. header). Defaults to the monospace FQN styling used
  // everywhere else.
  className?: string;
  // Column suffix appended after the FQN (e.g. "· customer_id"). Kept
  // outside the copy payload — clicking copies just the table FQN.
  columnSuffix?: string;
}

export function CopyableFQN({ fqn, variant = 'full', className, columnSuffix }: Props) {
  const [copied, setCopied] = useState(false);
  // Track the active "copied → not copied" timer so rapid re-clicks don't
  // leave the first timer pending. Without the clear, click 2 inside the
  // 1.5s window fires both timers and the first one flips `copied` back to
  // false before click 2's window expires.
  const resetRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    return () => {
      if (resetRef.current) clearTimeout(resetRef.current);
    };
  }, []);

  const display = variant === 'short' ? shortFQN(fqn) : fqn;
  const label = `Copy ${fqn}`;

  const onClick = async (e: React.MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation();
    if (!navigator.clipboard?.writeText) {
      toast.error('Clipboard unavailable in this browser');
      return;
    }
    try {
      await navigator.clipboard.writeText(fqn);
      setCopied(true);
      toast.success('FQN copied', { description: fqn });
      if (resetRef.current) clearTimeout(resetRef.current);
      resetRef.current = setTimeout(() => {
        setCopied(false);
        resetRef.current = null;
      }, 1500);
    } catch {
      toast.error('Copy failed');
    }
  };

  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={copied ? 'Copied!' : fqn}
      className={
        (className ?? 'font-mono text-[12px] text-slate-200') +
        ' group inline-flex items-center gap-1.5 text-left break-all hover:text-white transition rounded'
      }
    >
      <span className="break-all">
        {display}
        {columnSuffix && <span className="text-slate-500"> {columnSuffix}</span>}
      </span>
      <span
        className={
          'shrink-0 text-[10px] font-mono transition ' +
          (copied
            ? 'text-emerald-300'
            : 'text-slate-600 opacity-0 group-hover:opacity-100')
        }
        aria-hidden
      >
        {copied ? '✓' : '⧉'}
      </span>
    </button>
  );
}

// Shared short-FQN helper — the OpenMetadata form is service.db.schema.table,
// and in dense UI rows the service prefix duplicates for every entity from
// the same source, so trimming it keeps the meaningful three segments.
export function shortFQN(fqn: string): string {
  const parts = fqn.split('.');
  if (parts.length <= 3) return fqn;
  return parts.slice(-3).join('.');
}
