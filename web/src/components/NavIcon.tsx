/**
 * Nav-icon set used by the sidebar. SVG paths lifted verbatim from
 * metasift+/MetaSift App.html::NavIcon (L263-L273). Active-state color
 * pulls from the design tokens (emerald-400 / slate-500).
 */

export type NavIconKind =
  | 'chat'
  | 'queue'
  | 'viz'
  | 'dq'
  | 'doc'
  | 'llm'
  | 'sources'
  | 'observability'
  | 'catalog'
  | 'scans';

export function NavIcon({ kind, active }: { kind: NavIconKind; active: boolean }) {
  const color = active ? '#34d399' : '#64748b';
  const common = {
    width: 16,
    height: 16,
    fill: 'none',
    stroke: color,
    strokeWidth: 1.8,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
  };
  switch (kind) {
    case 'chat':
      return (
        <svg {...common} viewBox="0 0 24 24">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
      );
    case 'queue':
      return (
        <svg {...common} viewBox="0 0 24 24">
          <rect x="3" y="4" width="18" height="4" rx="1" />
          <rect x="3" y="10" width="18" height="4" rx="1" />
          <rect x="3" y="16" width="18" height="4" rx="1" />
        </svg>
      );
    case 'viz':
      return (
        <svg {...common} viewBox="0 0 24 24">
          <path d="M3 3v18h18" />
          <path d="M7 14l4-4 4 4 5-6" />
        </svg>
      );
    case 'dq':
      // Beaker — extends the mockup's NAV set for the /dq route that lives
      // outside the original 5-item list.
      return (
        <svg {...common} viewBox="0 0 24 24">
          <path d="M9 3h6" />
          <path d="M10 3v6L4 20a1 1 0 0 0 .9 1.5h14.2A1 1 0 0 0 20 20l-6-11V3" />
          <path d="M7 14h10" />
        </svg>
      );
    case 'doc':
      return (
        <svg {...common} viewBox="0 0 24 24">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="9" y1="13" x2="15" y2="13" />
          <line x1="9" y1="17" x2="13" y2="17" />
        </svg>
      );
    case 'llm':
      return (
        <svg {...common} viewBox="0 0 24 24">
          <path d="M12 2a4 4 0 0 1 4 4v1h1a3 3 0 0 1 3 3v1a3 3 0 0 1-1 2.2V17a4 4 0 0 1-4 4h-6a4 4 0 0 1-4-4v-3.8A3 3 0 0 1 4 11v-1a3 3 0 0 1 3-3h1V6a4 4 0 0 1 4-4z" />
          <circle cx="9" cy="12" r="1" />
          <circle cx="15" cy="12" r="1" />
        </svg>
      );
    case 'sources':
      // Stacked database cylinders — the classic "connected data source" glyph.
      return (
        <svg {...common} viewBox="0 0 24 24">
          <ellipse cx="12" cy="5" rx="8" ry="2.5" />
          <path d="M4 5v6c0 1.4 3.6 2.5 8 2.5s8-1.1 8-2.5V5" />
          <path d="M4 11v6c0 1.4 3.6 2.5 8 2.5s8-1.1 8-2.5v-6" />
        </svg>
      );
    case 'observability':
      // Eye-in-scope — matches OM's Observability bucket glyph.
      return (
        <svg {...common} viewBox="0 0 24 24">
          <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" />
          <circle cx="12" cy="12" r="3" />
        </svg>
      );
    case 'catalog':
      // Open book / ledger — grouped catalog-side screens (sources + review).
      return (
        <svg {...common} viewBox="0 0 24 24">
          <path d="M4 4h6a3 3 0 0 1 3 3v13a2 2 0 0 0-2-2H4z" />
          <path d="M20 4h-6a3 3 0 0 0-3 3v13a2 2 0 0 1 2-2h7z" />
        </svg>
      );
    case 'scans':
      // Radar sweep — distinct from the magnifying glass used inline by the
      // existing scan emojis so the parent icon doesn't clash with children.
      return (
        <svg {...common} viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="9" />
          <circle cx="12" cy="12" r="4" />
          <path d="M12 12 19 7" />
        </svg>
      );
  }
}
