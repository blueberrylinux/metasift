/**
 * Message composer. Enter to send, Shift+Enter for a newline.
 * Disabled while a stream is in flight so the user can't fire a second
 * request before the first one finishes persisting.
 */

import { useState } from 'react';

export function Composer({
  onSend,
  disabled,
}: {
  onSend: (text: string) => void;
  disabled: boolean;
}) {
  const [value, setValue] = useState('');

  const submit = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue('');
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      className="flex gap-3 items-end"
    >
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
        placeholder={disabled ? 'Stew is thinking…' : 'Ask Stew about your catalog…'}
        disabled={disabled}
        rows={2}
        className="flex-1 resize-none rounded-md border border-ink-border bg-ink-panel/60 px-3 py-2 text-sm text-ink-text placeholder:text-ink-dim focus:outline-none focus:border-accent/60 disabled:opacity-60"
      />
      <button
        type="submit"
        disabled={disabled || !value.trim()}
        className={
          'px-4 py-2 rounded-md text-sm font-mono transition-colors border ' +
          (disabled || !value.trim()
            ? 'bg-accent/10 text-accent-soft/60 border-accent/20 cursor-not-allowed'
            : 'bg-accent/30 hover:bg-accent/40 text-accent-bright border-accent/40')
        }
      >
        Send
      </button>
    </form>
  );
}
