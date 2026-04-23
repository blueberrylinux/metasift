/**
 * Shared empty-state scaffold. Every empty/error state across the six
 * screens funnels through this so the icon, title, body, and "try this
 * next" affordance all read the same way — a single visual pattern the
 * user learns once.
 *
 * Variants:
 *   neutral  — no data yet, non-error ("run a scan to populate this")
 *   info     — informational nudge (e.g. a feature tour pointer)
 *   error    — something failed; monospace body, red tint
 *
 * The `actions` slot holds the CTA row — typically 1-2 buttons/links.
 */

import type { ReactNode } from 'react';

type Variant = 'neutral' | 'info' | 'error';

interface Props {
  icon?: ReactNode;
  title: string;
  body?: ReactNode;
  actions?: ReactNode;
  hint?: ReactNode;
  variant?: Variant;
  className?: string;
  compact?: boolean;
}

const VARIANT_CLS: Record<Variant, string> = {
  neutral: 'border-slate-800 bg-slate-900/40 text-slate-300',
  info: 'border-emerald-500/25 bg-emerald-500/5 text-emerald-100',
  error: 'border-red-500/30 bg-red-500/5 text-red-200 font-mono',
};

const ICON_CLS: Record<Variant, string> = {
  neutral: 'bg-slate-800/80 text-slate-300',
  info: 'bg-emerald-500/15 text-emerald-200',
  error: 'bg-red-500/15 text-red-200',
};

export function EmptyState({
  icon,
  title,
  body,
  actions,
  hint,
  variant = 'neutral',
  className = '',
  compact = false,
}: Props) {
  return (
    <div
      className={
        `rounded-xl border ${VARIANT_CLS[variant]} ${compact ? 'px-5 py-5' : 'px-8 py-10'} ${className}`
      }
      role={variant === 'error' ? 'alert' : undefined}
    >
      <div className="flex items-start gap-4">
        {icon !== undefined && (
          <div
            className={
              `shrink-0 w-10 h-10 rounded-lg flex items-center justify-center text-lg ${ICON_CLS[variant]}`
            }
            aria-hidden
          >
            {icon}
          </div>
        )}
        <div className="flex-1 min-w-0">
          <div className="text-[14px] font-semibold text-white">{title}</div>
          {body && (
            <div className="text-[13px] text-slate-400 mt-1 leading-relaxed">{body}</div>
          )}
          {actions && <div className="mt-4 flex flex-wrap items-center gap-2">{actions}</div>}
          {hint && (
            <div className="mt-3 text-[11px] text-slate-500 font-mono border-t border-slate-800 pt-3">
              <span className="text-slate-600 uppercase tracking-wider mr-1.5">try next</span>
              {hint}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// Convenience CTA styles — keeps call sites terse while matching the
// emerald/slate primary/secondary pair used throughout the app.
export function EmptyCTA({
  onClick,
  children,
  variant = 'primary',
  disabled,
}: {
  onClick?: () => void;
  children: ReactNode;
  variant?: 'primary' | 'secondary';
  disabled?: boolean;
}) {
  const cls =
    variant === 'primary'
      ? 'bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-semibold'
      : 'bg-slate-800 hover:bg-slate-700 text-white border border-slate-700';
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`px-3.5 py-2 rounded-md text-[12px] transition disabled:opacity-50 ${cls}`}
    >
      {children}
    </button>
  );
}
