/**
 * Chat composer. Lifted from metasift+/MetaSift App.html::Composer
 * (L462-L508). focus-ring wrapper lights up the border while the
 * textarea has focus; Enter submits, Shift+Enter inserts a newline;
 * footer carries the ModelQuickPicker + shortcut hints.
 *
 * Disabled state is driven by the parent (`disabled` prop) while a
 * stream is in flight so the user can't fire a second turn before the
 * first finishes persisting.
 */

import { useEffect, useRef, useState, type ReactNode } from 'react';

import { ModelQuickPicker } from './ModelQuickPicker';
import { ToolsPalette } from './ToolsPalette';

interface Props {
  onSend: (text: string) => void;
  disabled: boolean;
  /** Override the placeholder (e.g. first-turn hero vs reply). */
  placeholder?: string;
  /** Extra footer affordance, e.g. tools-loaded count. */
  footerExtra?: ReactNode;
  /** When provided AND `disabled` is true, the send button swaps to a
   *  stop button that aborts the in-flight stream on click. */
  onStop?: () => void;
}

export function Composer({
  onSend,
  disabled,
  placeholder = 'Ask Stew about coverage, stale descriptions, tag conflicts, blast radius, or schemas…',
  footerExtra,
  onStop,
}: Props) {
  const [value, setValue] = useState('');
  const [paletteOpen, setPaletteOpen] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const submit = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue('');
  };

  // Global keyboard shortcuts:
  //   "/"       — focus the composer (when not already typing somewhere)
  //   ⌘K / ^K   — open the tools palette (works anywhere on the page)
  // Separate from the palette's own onKeyDown, which handles navigation
  // *within* the palette once it's open.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName;
      const inField =
        tag === 'INPUT' ||
        tag === 'TEXTAREA' ||
        tag === 'SELECT' ||
        target?.isContentEditable;

      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPaletteOpen(true);
        return;
      }
      if (e.key === '/' && !inField && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        textareaRef.current?.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  const insertFromPalette = (prompt: string) => {
    // If the prompt is self-contained (no `{placeholder}` to fill in), fire
    // it straight away — the whole point of the palette is one-click access
    // to common questions. For parametric prompts we stop at "insert" so
    // the user can type over the {placeholder} before sending.
    const placeholderMatch = prompt.match(/\{[^}]+\}/);
    if (!placeholderMatch && !disabled) {
      onSend(prompt);
      setValue('');
      return;
    }
    setValue(prompt);
    requestAnimationFrame(() => {
      const ta = textareaRef.current;
      if (!ta) return;
      ta.focus();
      if (placeholderMatch) {
        // Pre-select the first `{...}` so the user types over it — cursor
        // replacement is the fastest way to fill in an FQN or column name.
        const start = placeholderMatch.index ?? 0;
        const end = start + placeholderMatch[0].length;
        ta.setSelectionRange(start, end);
      } else {
        // Disabled (mid-stream) — queue the prompt for when the stream ends.
        ta.setSelectionRange(prompt.length, prompt.length);
      }
    });
  };

  return (
    <div className="border-t border-slate-800/80 bg-slate-950/80 backdrop-blur px-4 md:px-8 py-4 md:py-5">
      <div className="max-w-3xl mx-auto">
        <div className="focus-ring rounded-xl bg-slate-900/80 border border-slate-800 hover:border-slate-700 transition">
          <div className="flex items-end gap-2 p-2">
            <button
              type="button"
              title="Attach"
              aria-label="Attach"
              className="w-8 h-8 rounded-md text-slate-500 hover:text-emerald-300 hover:bg-slate-800 flex items-center justify-center shrink-0"
            >
              <svg
                width="14"
                height="14"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                viewBox="0 0 24 24"
              >
                <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
              </svg>
            </button>
            <textarea
              ref={textareaRef}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  submit();
                }
              }}
              placeholder={disabled ? 'Stew is thinking…' : placeholder}
              disabled={disabled}
              rows={1}
              className="flex-1 bg-transparent outline-none text-[14px] text-slate-100 placeholder:text-slate-600 resize-none py-2 px-2 max-h-32 disabled:opacity-70"
            />
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                title="Browse Stew's tools (⌘K / Ctrl+K)"
                onClick={() => setPaletteOpen(true)}
                className="text-[10px] font-mono px-2 py-1 rounded bg-slate-800 text-slate-400 hover:text-white transition"
              >
                ⌘K tools
              </button>
              {disabled && onStop ? (
                <button
                  type="button"
                  onClick={onStop}
                  aria-label="Stop generating"
                  title="Stop"
                  className="w-8 h-8 rounded-md bg-red-500/90 hover:bg-red-400 text-slate-950 flex items-center justify-center font-bold transition"
                >
                  <svg
                    width="12"
                    height="12"
                    viewBox="0 0 24 24"
                    fill="currentColor"
                  >
                    <rect x="6" y="6" width="12" height="12" rx="1.5" />
                  </svg>
                </button>
              ) : (
                <button
                  type="button"
                  onClick={submit}
                  disabled={disabled || !value.trim()}
                  aria-label="Send message"
                  className="w-8 h-8 rounded-md bg-emerald-500 hover:bg-emerald-400 text-slate-950 flex items-center justify-center font-bold transition disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <svg
                    width="14"
                    height="14"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.5"
                    viewBox="0 0 24 24"
                  >
                    <line x1="12" y1="19" x2="12" y2="5" />
                    <polyline points="5 12 12 5 19 12" />
                  </svg>
                </button>
              )}
            </div>
          </div>
          <div className="flex items-center justify-between px-3 py-1.5 border-t border-slate-800 text-[10px] text-slate-500 gap-2 flex-wrap">
            <div className="flex items-center gap-3 min-w-0">
              <ModelQuickPicker />
              <span className="font-mono">· 30 tools</span>
              <span className="font-mono">· writes gated</span>
              {footerExtra}
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <kbd>↵</kbd>
              <span>send</span>
              <kbd>shift+↵</kbd>
              <span>newline</span>
            </div>
          </div>
        </div>
        <div className="mt-2 text-center text-[10px] text-slate-600">
          Stew only sends structural metadata to the LLM — never sample data.
        </div>
      </div>
      <ToolsPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onPick={(prompt) => insertFromPalette(prompt)}
      />
    </div>
  );
}
