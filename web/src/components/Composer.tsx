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

interface Props {
  onSend: (text: string) => void;
  disabled: boolean;
  /** Override the placeholder (e.g. first-turn hero vs reply). */
  placeholder?: string;
  /** Extra footer affordance, e.g. tools-loaded count. */
  footerExtra?: ReactNode;
}

export function Composer({
  onSend,
  disabled,
  placeholder = 'Ask Stew about coverage, stale descriptions, tag conflicts, blast radius, or schemas…',
  footerExtra,
}: Props) {
  const [value, setValue] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const submit = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue('');
  };

  // Global "/" shortcut: focus the composer when the user isn't already
  // typing in a field. Mirrors the convention GitHub / Slack / Linear use
  // and makes the chat instantly usable without reaching for the mouse.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== '/') return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName;
      if (
        tag === 'INPUT' ||
        tag === 'TEXTAREA' ||
        tag === 'SELECT' ||
        target?.isContentEditable
      )
        return;
      e.preventDefault();
      textareaRef.current?.focus();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  return (
    <div className="border-t border-slate-800/80 bg-slate-950/80 backdrop-blur px-6 py-4">
      <div className="max-w-3xl mx-auto">
        <div className="focus-ring rounded-xl bg-slate-900/80 border border-slate-800 hover:border-slate-700 transition">
          <div className="flex items-end gap-2 p-2">
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
            </div>
          </div>
          <div className="flex items-center justify-between px-3 py-1.5 border-t border-slate-800 text-[10px] text-slate-500 gap-2 flex-wrap">
            <div className="flex items-center gap-3 min-w-0">
              <ModelQuickPicker />
              {footerExtra}
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <kbd>/</kbd>
              <span>focus</span>
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
    </div>
  );
}
