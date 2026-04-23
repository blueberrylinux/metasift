/**
 * Shared sidebar. Navigation lives here; each screen passes an `activeKey`
 * so the right row lights up. Disabled entries (Review / Viz / DQ / Report)
 * stay until the phases that wire them land.
 */

import { Link } from 'react-router-dom';

type NavKey = 'dashboard' | 'stew' | 'review' | 'viz' | 'dq' | 'report';

interface NavItem {
  key: NavKey;
  label: string;
  to?: string; // if set, the row is a router link
}

const NAV_ITEMS: NavItem[] = [
  { key: 'dashboard', label: 'Dashboard', to: '/' },
  { key: 'stew', label: 'Stew (chat)', to: '/chat' },
  { key: 'review', label: 'Review queue' },
  { key: 'viz', label: 'Visualizations' },
  { key: 'dq', label: 'Data quality' },
  { key: 'report', label: 'Report' },
];

export function Sidebar({ activeKey }: { activeKey: NavKey }) {
  return (
    <aside className="w-56 min-h-screen border-r border-ink-border bg-ink-panel/40 px-5 pt-10 pb-6 flex flex-col gap-8">
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-lg bg-accent-glow border border-accent/30 flex items-center justify-center">
          <span className="font-bold text-accent-soft text-lg">M</span>
        </div>
        <div>
          <div className="font-bold tracking-tight">MetaSift</div>
          <div className="text-ink-dim text-mini font-mono">v0.5.0-port.1</div>
        </div>
      </div>
      <nav className="flex flex-col gap-1">
        {NAV_ITEMS.map((item) => {
          const active = item.key === activeKey;
          const base = 'text-left text-sm px-3 py-2 rounded-md transition-colors';
          const activeCls = 'bg-accent-glow text-accent-soft border border-accent/20';
          const linkCls = 'text-ink-soft hover:bg-ink-panel/60 hover:text-ink-text';
          const disabledCls = 'text-ink-dim cursor-not-allowed';
          if (active && item.to) {
            return (
              <Link key={item.key} to={item.to} className={`${base} ${activeCls}`}>
                {item.label}
              </Link>
            );
          }
          if (item.to) {
            return (
              <Link key={item.key} to={item.to} className={`${base} ${linkCls}`}>
                {item.label}
              </Link>
            );
          }
          return (
            <button key={item.key} disabled className={`${base} ${disabledCls}`}>
              {item.label}
            </button>
          );
        })}
      </nav>
      <div className="mt-auto text-ink-dim text-mini font-mono">
        Phase 2 · Stew chat
      </div>
    </aside>
  );
}
