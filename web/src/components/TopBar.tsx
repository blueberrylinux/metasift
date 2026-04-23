/**
 * Sticky top header. Lifted from metasift+/MetaSift App.html::TopBar
 * (L215-L249). Logo refresh button dropped (no logo picker surface in the
 * port); Welcome Guide button is a placeholder for slice 2 to wire into
 * the WelcomeModal.
 */

import { LogoM } from './LogoM';

export function TopBar({ onOpenWelcome }: { onOpenWelcome?: () => void }) {
  return (
    <div className="h-14 border-b border-slate-800/80 backdrop-blur-md bg-slate-950/70 flex items-center justify-between px-5 sticky top-0 z-30">
      <div className="flex items-center gap-3">
        <LogoM size={30} />
        <div>
          <div className="text-[13px] font-bold text-white tracking-tight leading-none">
            MetaSift
          </div>
          <div className="text-[10px] text-slate-500 mt-0.5 leading-none">
            AI metadata analyst &amp; steward
          </div>
        </div>
        <div className="ml-5 h-5 w-px bg-slate-800" />
        <div className="flex items-center gap-2 text-[11px] text-slate-400">
          <span className="font-mono">openmetadata.local</span>
          <span className="w-1 h-1 rounded-full bg-slate-700" />
          <span className="font-mono">admin</span>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <button
          onClick={onOpenWelcome}
          className="text-[11px] px-2.5 py-1 rounded-md text-cyan-300 border border-cyan-500/20 bg-cyan-500/5 hover:bg-cyan-500/10 transition"
        >
          ⓘ Welcome guide
        </button>
        <a
          href="https://github.com/blueberrylinux/metasift"
          target="_blank"
          rel="noreferrer"
          className="text-[11px] px-2.5 py-1 rounded-md text-slate-300 hover:text-white hover:bg-slate-800/60 transition"
        >
          Docs
        </a>
      </div>
    </div>
  );
}
