/**
 * Inline-editable text field. Used by the conversation header (large
 * h1-style) and by each Recent conversations row on the /chat landing
 * (compact row-style). Click / enter-edit shows an input; Enter commits,
 * Escape reverts, blur commits.
 *
 * Styling is caller-driven via `inputClass` + `displayClass` so the
 * component can slot into very different typography contexts without
 * forking.
 */

import { useEffect, useRef, useState, type ReactNode } from 'react';

export function EditableTitle({
  current,
  display,
  onSave,
  saving,
  placeholder,
  inputClass,
  displayClass,
  pencilClass,
  pencilSize = 14,
  showPencil = true,
  stopPropagation = false,
}: {
  /** Persisted title — null when unset so the caller can show a placeholder. */
  current: string | null;
  /** Rendered text when not editing (e.g. 'Untitled conversation'). */
  display: ReactNode;
  /** Fires on Enter / blur with the trimmed draft. */
  onSave: (next: string) => void;
  /** When true, the input is disabled (optimistic save in flight). */
  saving: boolean;
  placeholder?: string;
  /** Tailwind classes applied to the `<input>` when editing. */
  inputClass?: string;
  /** Tailwind classes applied to the display `<span>` when not editing. */
  displayClass?: string;
  /** Tailwind classes applied to the pencil svg. Defaults to a hover-reveal. */
  pencilClass?: string;
  pencilSize?: number;
  showPencil?: boolean;
  /** When true (e.g. inside a parent `<Link>`), stop click from bubbling so
   *  entering edit mode doesn't also navigate. */
  stopPropagation?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(current ?? '');
  const inputRef = useRef<HTMLInputElement | null>(null);
  // Escape-then-blur race: pressing Escape schedules `setDraft(original)`,
  // but the follow-up onBlur's `commit` reads the closure's `draft`, which
  // is still the edited value. Without this flag, Escape would silently
  // save. The ref clears the flag after the first onBlur consumes it.
  const canceledRef = useRef(false);

  useEffect(() => {
    if (!editing) setDraft(current ?? '');
  }, [current, editing]);

  const commit = () => {
    if (canceledRef.current) {
      canceledRef.current = false;
      return;
    }
    setEditing(false);
    onSave(draft);
  };

  const cancel = () => {
    canceledRef.current = true;
    setEditing(false);
    setDraft(current ?? '');
  };

  if (editing) {
    return (
      <input
        ref={inputRef}
        value={draft}
        autoFocus
        disabled={saving}
        onChange={(e) => setDraft(e.target.value)}
        onClick={(e) => stopPropagation && e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            commit();
          } else if (e.key === 'Escape') {
            e.preventDefault();
            cancel();
          }
        }}
        onBlur={commit}
        placeholder={placeholder}
        className={
          inputClass ??
          'bg-transparent outline-none border-b border-slate-600 focus:border-emerald-400 w-full max-w-[28ch] placeholder:text-slate-600 disabled:opacity-60'
        }
      />
    );
  }

  const defaultPencilClass =
    'text-slate-600 group-hover:text-emerald-300 opacity-0 group-hover:opacity-100 transition';

  return (
    <button
      type="button"
      onClick={(e) => {
        if (stopPropagation) {
          e.preventDefault();
          e.stopPropagation();
        }
        setEditing(true);
      }}
      title="Rename"
      className="inline-flex items-center gap-2 text-left transition group"
    >
      <span className={displayClass}>{display}</span>
      {showPencil && (
        <svg
          width={pencilSize}
          height={pencilSize}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={pencilClass ?? defaultPencilClass}
        >
          <path d="M12 20h9" />
          <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />
        </svg>
      )}
    </button>
  );
}
