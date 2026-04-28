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
import { useLocation } from 'react-router-dom';

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
  // Mobile sidebar drawer state. Desktop ignores this entirely — the sidebar
  // is always visible above md:. On mobile the drawer slides in over content
  // when opened from the TopBar hamburger.
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    try {
      if (!localStorage.getItem(WELCOME_KEY)) setWelcomeOpen(true);
    } catch {
      // sandboxed storage (private mode, file://) — skip auto-open
    }
  }, []);

  // Close the mobile drawer on navigation so a route change from the
  // drawer's nav doesn't leave the overlay covering the new screen.
  const { pathname } = useLocation();
  useEffect(() => {
    setSidebarOpen(false);
  }, [pathname]);

  // Esc closes the drawer. No-op on desktop where it's never "open".
  useEffect(() => {
    if (!sidebarOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSidebarOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [sidebarOpen]);

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
        <TopBar
          onOpenWelcome={() => setWelcomeOpen(true)}
          onToggleSidebar={() => setSidebarOpen((o) => !o)}
          sidebarOpen={sidebarOpen}
        />
        {sandbox && <SandboxBanner />}
        {/* Mobile drawer backdrop. Sits below the sidebar (z-30 vs z-40) and
            below the TopBar (`top-14` so the hamburger remains tappable to
            dismiss). md:hidden — desktop never renders this. */}
        {sidebarOpen && (
          <button
            type="button"
            aria-label="Close menu"
            onClick={() => setSidebarOpen(false)}
            className="md:hidden fixed top-14 inset-x-0 bottom-0 z-30 bg-black/60 backdrop-blur-sm"
          />
        )}
        <div className="flex">
          <Sidebar
            activeKey={activeKey}
            mobileOpen={sidebarOpen}
            onMobileClose={() => setSidebarOpen(false)}
          />
          {/* min-w-0 lets flex children (DQ tables etc.) shrink instead of
              forcing the document to grow — without it, a wide table inside
              main blows out the page-level horizontal scroll on mobile. */}
          <main
            className="flex-1 flex flex-col min-h-[calc(100vh-3.5rem)] min-w-0"
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
