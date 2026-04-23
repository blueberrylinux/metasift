/**
 * First-run welcome modal. Lifted from metasift+/MetaSift App.html::WelcomeModal
 * (L2200-L2323). Features grid on the left, Quick-start numbered steps + Things
 * Worth Trying chips on the right, footer with status dots + Configure LLM /
 * Start exploring buttons.
 *
 * Dismissal is session + localStorage: first visit shows the modal once, and
 * the TopBar's "Welcome guide" button re-opens it on demand.
 */

import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

import { LogoM } from './LogoM';

interface Props {
  onClose: () => void;
}

interface Feature {
  icon: string;
  title: string;
  desc: string;
  chip: string;
  tone: 'emerald' | 'cyan' | 'amber';
}

const FEATURES: Feature[] = [
  {
    icon: '◆',
    title: 'Analysis',
    desc: 'Aggregate SQL analytics over your catalog — coverage, tag conflicts, lineage impact, composite score.',
    chip: '4 tools',
    tone: 'emerald',
  },
  {
    icon: '✎',
    title: 'Cleaning',
    desc: 'Stale descriptions, DQ explanations, quality 1–5 scoring, naming drift clusters.',
    chip: '6 tools',
    tone: 'cyan',
  },
  {
    icon: '⚑',
    title: 'Stewardship',
    desc: 'Auto-document undocumented tables, detect PII, recommend DQ tests that should exist.',
    chip: '5 tools',
    tone: 'amber',
  },
  {
    icon: '💬',
    title: 'Stew',
    desc: 'Chat with a LangChain agent grounded in 25 local tools + 3 MCP. Every reply shows its work.',
    chip: '28 tools',
    tone: 'emerald',
  },
];

const QUICKSTART = [
  {
    n: 1,
    lbl: 'Refresh metadata',
    desc: "Pull your OpenMetadata catalog into MetaSift's DuckDB store.",
  },
  {
    n: 2,
    lbl: 'Run a scan',
    desc: 'Deep scan (stale + quality), PII scan, Explain DQ failures, or Recommend DQ tests.',
  },
  {
    n: 3,
    lbl: 'Ask Stew',
    desc: 'Try "what\'s my composite score?", "find tag conflicts", or "why is email_not_null failing?"',
  },
];

const TO_TRY: { q: string; w: string }[] = [
  { q: "what's my composite score?", w: 'analysis' },
  { q: 'find stale descriptions', w: 'cleaning' },
  { q: 'auto-document the sales schema', w: 'stewardship' },
  { q: 'top DQ risks across the catalog', w: 'cleaning' },
  { q: 'what DQ tests should I add to orders?', w: 'stewardship' },
  { q: 'where does PII propagate?', w: 'lineage' },
];

const TONE_CLS: Record<Feature['tone'], string> = {
  emerald: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20',
  cyan: 'bg-cyan-500/10 text-cyan-300 border-cyan-500/20',
  amber: 'bg-amber-500/10 text-amber-300 border-amber-500/20',
};

export function WelcomeModal({ onClose }: Props) {
  const nav = useNavigate();
  const dialogRef = useRef<HTMLDivElement | null>(null);

  // Escape-to-close + focus trap. Not using a modal library because the rest
  // of the app is tiny and Radix/HeadlessUI would be a sledgehammer — but we
  // do owe users the basics: return key restores focus, Tab stays inside the
  // dialog, previously-focused element gets focus back on close.
  useEffect(() => {
    const root = dialogRef.current;
    if (!root) return;

    const previouslyFocused = document.activeElement as HTMLElement | null;
    const focusables = () =>
      Array.from(
        root.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((el) => !el.hasAttribute('data-focus-skip'));

    // Focus the first interactive control so keyboard users land inside the
    // dialog immediately — starting on the close button specifically would
    // make "Enter" dismiss the modal before anyone sees it.
    const first = focusables()[0];
    first?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key !== 'Tab') return;
      const items = focusables();
      if (items.length === 0) return;
      const firstEl = items[0];
      const lastEl = items[items.length - 1];
      const active = document.activeElement as HTMLElement | null;
      if (e.shiftKey && active === firstEl) {
        e.preventDefault();
        lastEl.focus();
      } else if (!e.shiftKey && active === lastEl) {
        e.preventDefault();
        firstEl.focus();
      }
    };

    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      previouslyFocused?.focus?.();
    };
  }, [onClose]);

  const startWith = (q: string) => {
    // Hand the suggestion text through to /chat via URL query param.
    // Stew.tsx reads `?q=` and auto-creates a conversation + submits on mount.
    onClose();
    nav(`/chat?q=${encodeURIComponent(q)}`);
  };

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby="welcome-title"
      className="fixed inset-0 z-50 bg-slate-950/85 backdrop-blur-sm flex items-center justify-center p-8 overflow-y-auto"
      onClick={onClose}
    >
      <div
        className="relative max-w-5xl w-full my-auto bg-slate-950 border border-slate-800 rounded-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="absolute inset-0 grid-bg opacity-30 pointer-events-none" />

        {/* Header */}
        <div className="relative px-8 pt-8 pb-6 border-b border-slate-800 flex items-start justify-between">
          <div className="flex items-start gap-5">
            <LogoM size={64} />
            <div>
              <div className="text-[10px] uppercase tracking-wider text-cyan-400 font-semibold">
                Welcome to
              </div>
              <h2
                id="welcome-title"
                className="text-3xl font-bold text-white tracking-tight leading-tight"
              >
                MetaSift
              </h2>
              <p className="text-[13px] text-slate-400 mt-1 max-w-xl">
                An <span className="text-emerald-300">AI metadata analyst &amp; steward</span> for
                OpenMetadata. Documentation coverage is a lie — a catalog can be 100% documented
                and still full of wrong, stale, or conflicting metadata. MetaSift introduces a{' '}
                <span className="text-white font-medium">composite score</span> that measures what
                actually matters.
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close welcome modal"
            className="w-8 h-8 rounded-md bg-slate-900 border border-slate-800 text-slate-400 hover:text-white hover:border-slate-700"
          >
            ✕
          </button>
        </div>

        <div className="relative p-8 grid grid-cols-1 md:grid-cols-5 gap-6">
          {/* Features */}
          <div className="md:col-span-3 space-y-3">
            <div className="text-[11px] uppercase tracking-wider text-emerald-400 font-semibold mb-1">
              Four engines, one wizard
            </div>
            {FEATURES.map((f) => (
              <div
                key={f.title}
                className="flex items-start gap-4 p-4 rounded-xl border border-slate-800 bg-slate-900/30 hover:border-slate-700 transition"
              >
                <div
                  className={`w-10 h-10 rounded-lg border flex items-center justify-center text-lg ${TONE_CLS[f.tone]}`}
                >
                  {f.icon}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <div className="text-[14px] font-semibold text-white">{f.title}</div>
                    <span className="text-[10px] font-mono text-slate-500">{f.chip}</span>
                  </div>
                  <div className="text-[12px] text-slate-400 leading-relaxed mt-0.5">{f.desc}</div>
                </div>
              </div>
            ))}
          </div>

          {/* Right column: quickstart + things to try */}
          <div className="md:col-span-2 space-y-5">
            <div>
              <div className="text-[11px] uppercase tracking-wider text-emerald-400 font-semibold mb-2">
                Quick start
              </div>
              <div className="space-y-2">
                {QUICKSTART.map((q) => (
                  <div
                    key={q.n}
                    className="flex items-start gap-3 p-3 rounded-lg border border-slate-800 bg-slate-900/40"
                  >
                    <div className="w-6 h-6 rounded-full bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center text-[11px] font-bold text-emerald-300 shrink-0">
                      {q.n}
                    </div>
                    <div className="min-w-0">
                      <div className="text-[12px] text-slate-200 font-medium">{q.lbl}</div>
                      <div className="text-[11px] text-slate-500 leading-snug mt-0.5">{q.desc}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-wider text-emerald-400 font-semibold mb-2">
                Things worth trying
              </div>
              <div className="space-y-1.5">
                {TO_TRY.map((t) => (
                  <button
                    key={t.q}
                    onClick={() => startWith(t.q)}
                    className="w-full text-left suggest-btn rounded-lg px-3 py-2 flex items-center gap-2"
                  >
                    <span className="text-emerald-300 text-xs">›</span>
                    <span className="text-[12px] text-slate-200 truncate flex-1">{t.q}</span>
                    <span className="text-[9px] font-mono text-slate-600">{t.w}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="relative px-8 pb-6 flex items-center justify-between border-t border-slate-800 pt-5 bg-slate-950/40">
          <div className="flex items-center gap-4 text-[11px] text-slate-500">
            <span className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 pulse-dot" />
              OpenMetadata connected
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 pulse-dot" />
              LLM ready
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                onClose();
                nav('/settings');
              }}
              className="text-[12px] px-3 py-1.5 rounded-md text-slate-300 border border-slate-700 hover:border-slate-600 hover:bg-slate-900"
            >
              Configure LLM →
            </button>
            <button
              onClick={onClose}
              className="text-[12px] px-3.5 py-1.5 rounded-md bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-semibold"
            >
              Start exploring
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
