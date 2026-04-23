/**
 * Shared screen shell — TopBar + Sidebar + main content slot. Lifts the
 * frame from metasift+/MetaSift App.html::App (L2825-L2846) so every
 * screen mounts inside the same hero-glow + grid background, a sticky
 * TopBar, and a sticky Sidebar.
 *
 * Welcome modal hook is threaded through to the TopBar's "Welcome guide"
 * button; slice 2 wires the actual modal behind it. For now callers can
 * pass a no-op handler (or omit the prop) to get a placeholder click.
 */

import { type ReactNode } from 'react';

import type { NavKey } from './Sidebar';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';

export function AppLayout({
  activeKey,
  onOpenWelcome,
  children,
}: {
  activeKey: NavKey;
  onOpenWelcome?: () => void;
  children: ReactNode;
}) {
  return (
    <div className="relative min-h-screen hero-glow bg-ink-bg text-ink-text">
      <div className="absolute inset-0 grid-bg opacity-40 pointer-events-none" />
      <div className="relative">
        <TopBar onOpenWelcome={onOpenWelcome} />
        <div className="flex">
          <Sidebar activeKey={activeKey} />
          <main
            className="flex-1 flex flex-col min-h-[calc(100vh-3.5rem)]"
            data-screen={activeKey}
          >
            {children}
          </main>
        </div>
      </div>
    </div>
  );
}
