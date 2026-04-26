/**
 * Stew landing grid — "Meet Stew" hero + 6 suggestion chips. Lifted from
 * metasift+/MetaSift App.html::StewHome (L424-L460). Clicking a suggestion
 * hands the text to the screen's onSelect which creates a conversation
 * and auto-submits the question.
 */

import { type ReactNode } from 'react';

interface Suggestion {
  icon: string;
  label: string;
  hint: string;
}

const SUGGESTIONS: Suggestion[] = [
  { icon: '◆', label: "What's my composite score?", hint: 'analysis · 4 tools' },
  { icon: '✎', label: 'Find stale descriptions', hint: 'cleaning · LLM' },
  { icon: '⚑', label: 'Check for tag conflicts', hint: 'cleaning · SQL' },
  { icon: '⌕', label: 'Auto-document sales schema', hint: 'stewardship · bulk' },
  { icon: '◈', label: 'Blast-radius top 10', hint: 'analysis · DuckDB' },
  { icon: '⚙', label: 'Who owns customer_id drift?', hint: 'stewardship · team' },
];

export function StewHome({
  onSelect,
  pending = false,
  footer,
}: {
  onSelect: (question: string) => void;
  /** When true, suggestion buttons are disabled — prevents rapid-click
   *  multi-create while a conversation is being spun up. */
  pending?: boolean;
  footer?: ReactNode;
}) {
  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      <div className="flex-1 flex flex-col items-center justify-center px-10 py-6 min-h-0">
        <h1 className="text-4xl font-bold text-white tracking-tight">Meet Stew</h1>
        <p className="mt-3 text-slate-400 text-[15px] max-w-xl text-center">
          Your metadata wizard — ask anything about your catalog.
        </p>
        <div className="mt-3 flex items-center gap-3 text-[11px] text-slate-500">
          <span className="chip">30 tools</span>
          <span className="font-mono">27 local · 3 MCP</span>
        </div>

        <div className="mt-8 grid grid-cols-1 md:grid-cols-2 gap-2.5 w-full max-w-3xl">
          {SUGGESTIONS.map((s) => (
            <button
              key={s.label}
              onClick={() => onSelect(s.label)}
              disabled={pending}
              className="suggest-btn rounded-lg px-4 py-3 flex items-center gap-3 text-left disabled:opacity-60 disabled:cursor-wait"
            >
              <div className="w-8 h-8 rounded-md bg-emerald-500/10 text-emerald-300 flex items-center justify-center text-sm border border-emerald-500/20">
                {s.icon}
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-[13px] text-slate-200 font-medium truncate">{s.label}</div>
                <div className="text-[10px] text-slate-500 font-mono truncate">{s.hint}</div>
              </div>
              <span className="text-slate-600 text-xs">{pending ? '…' : '↵'}</span>
            </button>
          ))}
        </div>
      </div>
      {footer}
    </div>
  );
}
