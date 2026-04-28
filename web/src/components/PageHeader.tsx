/**
 * Shared page header. Lifted from metasift+/MetaSift Port Scaffolding.html
 * ::PageHeader (L1249-L1283). Gives every screen a consistent top strip —
 * left-accent bar, title + subtitle, optional status chips, optional
 * right-aligned action buttons.
 */

import { type ReactNode } from 'react';
import { Link } from 'react-router-dom';

export type HeaderChipTone = 'emerald' | 'amber' | 'red' | 'cyan' | 'slate';

export interface HeaderChip {
  label: string;
  tone?: HeaderChipTone;
}

const TONE_TO_CHIP_CLS: Record<HeaderChipTone, string> = {
  emerald: 'chip',
  amber: 'chip amber',
  red: 'chip red',
  cyan: 'chip cyan',
  slate: 'chip slate',
};

export function PageHeader({
  title,
  subtitle,
  chips = [],
  rightButtons,
  backLink,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  chips?: HeaderChip[];
  rightButtons?: ReactNode;
  /** Optional breadcrumb link rendered above the title (e.g. `← Stew`). */
  backLink?: { to: string; label: ReactNode };
}) {
  return (
    <div className="flex items-start justify-between gap-4 px-4 md:px-6 pt-5 pb-4 border-b border-slate-800/80">
      <div className="section-accent">
        {backLink && (
          <Link
            to={backLink.to}
            className="inline-flex items-center gap-2 text-[10px] uppercase tracking-widest text-slate-400 hover:text-emerald-300 font-semibold transition group"
          >
            <span className="w-6 h-6 rounded-md border border-slate-700 bg-slate-900/60 group-hover:border-emerald-500/40 group-hover:bg-emerald-500/5 flex items-center justify-center text-slate-300 group-hover:text-emerald-300 transition">
              <svg
                width="12"
                height="12"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <line x1="19" y1="12" x2="5" y2="12" />
                <polyline points="12 19 5 12 12 5" />
              </svg>
            </span>
            {backLink.label}
          </Link>
        )}
        <h1 className={'text-xl font-bold text-white tracking-tight' + (backLink ? ' mt-1' : '')}>
          {title}
        </h1>
        {subtitle && <p className="text-[12px] text-slate-400 mt-1 max-w-3xl">{subtitle}</p>}
        {chips.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {chips.map((c, i) => (
              <span
                key={`${c.label}-${c.tone ?? 'slate'}-${i}`}
                className={TONE_TO_CHIP_CLS[c.tone ?? 'slate']}
              >
                {c.label}
              </span>
            ))}
          </div>
        )}
      </div>
      {rightButtons && <div className="flex items-center gap-2 shrink-0">{rightButtons}</div>}
    </div>
  );
}
