/**
 * Nav-icon set used by the sidebar. SVG paths lifted verbatim from
 * metasift+/MetaSift App.html::NavIcon (L263-L273). Active-state color
 * pulls from the design tokens (emerald-400 / slate-500).
 */

export type NavIconKind = 'chat' | 'queue' | 'viz' | 'dq' | 'doc' | 'llm';

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
  }
}
