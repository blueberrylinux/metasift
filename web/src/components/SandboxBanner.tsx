/**
 * Read-only-sandbox topbar banner. Slim strip under the TopBar that signals
 * the public-demo state and counts down to the nightly reset. Renders only
 * when /health says `sandbox: true`; on local installs / self-hosted, this
 * component never mounts.
 *
 * Kept dense — every screen inherits the AppLayout shell, so a thick banner
 * eats persistent vertical real-estate. One line, monospace timestamp,
 * subdued amber so it reads as "advisory" not "error".
 */

import { useEffect, useState } from 'react';

import { formatResetCountdown } from '../lib/sandbox';

export function SandboxBanner() {
  // Re-render on a 60s tick so the countdown stays current. Don't bind to
  // requestAnimationFrame — the countdown only moves once a minute.
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 60_000);
    return () => window.clearInterval(id);
  }, []);

  return (
    <div
      role="status"
      className="text-[11px] px-5 py-1.5 border-b border-amber-500/20 bg-amber-500/5 text-amber-200/90 flex items-center gap-3 sticky top-14 z-20 backdrop-blur-md"
    >
      <span className="font-semibold uppercase tracking-wider text-amber-300">
        Public sandbox
      </span>
      <span className="text-amber-200/70">
        Read-only demo. Bring your own free OpenRouter key on first chat.
      </span>
      <span className="ml-auto font-mono text-amber-200/60">
        Resets daily 04:00 UTC · {formatResetCountdown(now)}
      </span>
    </div>
  );
}
