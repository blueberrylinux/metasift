/**
 * Shared screen shell — TopBar + Sidebar + main content slot. Lifts the
 * frame from metasift+/MetaSift App.html::App (L2825-L2846) so every
 * screen mounts inside the same hero-glow + grid background, a sticky
 * TopBar, and a sticky Sidebar.
 *
 * Welcome modal visibility lives here so it can be reached from any route
 * (re-open via the TopBar button on any screen). First-run detection uses
 * localStorage; the key stays stable so a user who dismissed once never
 * gets the modal again unless they explicitly click Welcome guide.
 */

import { useEffect, useState, type ReactNode } from 'react';

import { useSandbox } from '../lib/sandbox';
import { SandboxBanner } from './SandboxBanner';
import type { NavKey } from './Sidebar';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';
import { WelcomeModal } from './WelcomeModal';

const WELCOME_KEY = 'metasift_welcomed';

export function AppLayout({
  activeKey,
  children,
}: {
  activeKey: NavKey;
  children: ReactNode;
}) {
  // Default-false until the effect reads localStorage to avoid a flash of the
  // modal for returning users on slow mounts.
  const [welcomeOpen, setWelcomeOpen] = useState(false);

  useEffect(() => {
    try {
      if (!localStorage.getItem(WELCOME_KEY)) setWelcomeOpen(true);
    } catch {
      // sandboxed storage (private mode, file://) — skip auto-open
    }
  }, []);

  const dismiss = () => {
    setWelcomeOpen(false);
    try {
      localStorage.setItem(WELCOME_KEY, '1');
    } catch {
      // ignore
    }
  };

  // Read-only/public-demo flag from /health. Always false on local installs;
  // when true we render the SandboxBanner under the TopBar.
  const sandbox = useSandbox();

  return (
    <div className="relative min-h-screen hero-glow bg-ink-bg text-ink-text">
      <div className="absolute inset-0 grid-bg opacity-40 pointer-events-none" />
      <div className="relative">
        <TopBar onOpenWelcome={() => setWelcomeOpen(true)} />
        {sandbox && <SandboxBanner />}
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
      {welcomeOpen && <WelcomeModal onClose={dismiss} />}
    </div>
  );
}
