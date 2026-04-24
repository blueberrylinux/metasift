/**
 * Quick-launch palette for Stew's tools. Opens on ⌘K / Ctrl+K or via the
 * `⌘K tools` chip in the composer. Filterable list grouped by category;
 * Enter picks the selected row; arrow keys navigate; Escape closes.
 *
 * On pick we hand the tool's natural-language prompt back to the composer
 * via `onPick`. The composer decides whether to auto-send or leave the
 * prompt for the user to edit.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import { STEW_TOOLS, TOOL_CATEGORIES, type StewTool } from '../lib/tools';

export function ToolsPalette({
  open,
  onClose,
  onPick,
}: {
  open: boolean;
  onClose: () => void;
  onPick: (prompt: string, tool: StewTool) => void;
}) {
  const [q, setQ] = useState('');
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  const filtered = useMemo(() => {
    const needle = q.toLowerCase();
    if (!needle) return STEW_TOOLS;
    return STEW_TOOLS.filter(
      (t) =>
        t.name.toLowerCase().includes(needle) ||
        t.description.toLowerCase().includes(needle) ||
        t.category.toLowerCase().includes(needle) ||
        t.prompt.toLowerCase().includes(needle),
    );
  }, [q]);

  // Reset selection when the filter narrows so cursor doesn't dangle past
  // the end of the visible list.
  useEffect(() => {
    setCursor(0);
  }, [q]);

  // Focus input + reset state whenever we re-open. Keep the filter text
  // cleared so each open starts fresh — users will usually pick a tool
  // relevant to the current thought, not the last one they typed.
  useEffect(() => {
    if (open) {
      setQ('');
      setCursor(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  // Keep the selected row in view as the user arrows through the list.
  useEffect(() => {
    if (!open || !listRef.current) return;
    const el = listRef.current.querySelector<HTMLElement>(`[data-row="${cursor}"]`);
    el?.scrollIntoView({ block: 'nearest' });
  }, [cursor, open]);

  if (!open) return null;

  const grouped: Record<string, StewTool[]> = {};
  for (const t of filtered) {
    (grouped[t.category] ||= []).push(t);
  }

  const pick = (t: StewTool) => {
    onClose();
    onPick(t.prompt, t);
  };

  const onKey = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      setCursor((i) => Math.min(filtered.length - 1, i + 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setCursor((i) => Math.max(0, i - 1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const t = filtered[cursor];
      if (t) pick(t);
    }
  };

  // Portal into document.body so the overlay isn't positioned relative to the
  // Composer's containing block — the Composer has `backdrop-blur`, which
  // establishes a containing block for `position: fixed` descendants in
  // Chromium, which would otherwise pin the palette INSIDE the composer bar
  // and force the page itself to scroll.
  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Tool palette"
      className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-start justify-center pt-[4vh] px-4"
      onClick={onClose}
      onKeyDown={onKey}
    >
      <div
        className="w-full max-w-xl rounded-xl bg-slate-950 border border-slate-800 shadow-2xl overflow-hidden flex flex-col max-h-[92vh]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-800">
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="text-slate-500"
          >
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.3-4.3" />
          </svg>
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search Stew's tools… (26 local + 3 MCP)"
            className="flex-1 bg-transparent outline-none text-[13px] text-slate-100 placeholder:text-slate-600"
          />
          <kbd className="text-[9px] font-mono text-slate-600 border border-slate-800 px-1 py-0.5 rounded">
            esc
          </kbd>
        </div>

        <div ref={listRef} className="flex-1 overflow-y-auto scrollbar-thin min-h-0">
          {filtered.length === 0 ? (
            <div className="px-4 py-8 text-center text-[12px] text-slate-500">
              No tools match "{q}"
            </div>
          ) : (
            TOOL_CATEGORIES.filter((c) => grouped[c]?.length).map((cat) => (
              <section key={cat}>
                <div className="sticky top-0 px-4 py-1 text-[9px] uppercase tracking-widest text-slate-500 font-semibold bg-slate-950/95 backdrop-blur border-b border-slate-900 z-[1]">
                  {cat}
                </div>
                {grouped[cat]!.map((t) => {
                  const idx = filtered.indexOf(t);
                  const active = idx === cursor;
                  return (
                    <button
                      key={t.name}
                      type="button"
                      data-row={idx}
                      onMouseEnter={() => setCursor(idx)}
                      onClick={() => pick(t)}
                      className={
                        'w-full text-left px-4 py-2 border-b border-slate-900 flex items-start gap-3 transition ' +
                        (active
                          ? 'bg-emerald-500/10 text-emerald-100'
                          : 'text-slate-300 hover:bg-slate-900')
                      }
                    >
                      <div className="flex-1 min-w-0">
                        <div className="text-[12px] font-mono truncate">
                          <span className={active ? 'text-emerald-300' : 'text-slate-200'}>
                            {t.name}
                          </span>
                        </div>
                        <div className="text-[11px] text-slate-500 truncate mt-0.5">
                          {t.description}
                        </div>
                      </div>
                      <span
                        className={
                          'text-[9px] font-mono shrink-0 px-1.5 py-0.5 rounded ' +
                          (active
                            ? 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20'
                            : 'text-slate-600 border border-slate-800')
                        }
                      >
                        {t.category}
                      </span>
                    </button>
                  );
                })}
              </section>
            ))
          )}
        </div>

        <div className="px-4 py-2 border-t border-slate-800 flex items-center justify-between text-[9px] font-mono text-slate-600">
          <span>
            {filtered.length} of {STEW_TOOLS.length} · click or <kbd>↵</kbd> to insert
          </span>
          <span className="flex items-center gap-1.5">
            <kbd>↑</kbd>
            <kbd>↓</kbd>
            <span>navigate</span>
          </span>
        </div>
      </div>
    </div>,
    document.body,
  );
}
