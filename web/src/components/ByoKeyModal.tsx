/**
 * BYO-key modal — sandbox-only. Triggered when the API returns 402
 * `byo_key_required` from /chat/stream or one of the LLM-bearing scan
 * endpoints. The user pastes their free OpenRouter key, we validate it
 * against /llm/validate-key, persist to localStorage on success, and
 * close. Subsequent fetches in this tab pick the key up automatically
 * via byoKeyHeaders() in lib/api.ts.
 *
 * Never logs the key. Never sends it anywhere except `POST /llm/validate-key`
 * (which proxies to OpenRouter's `/auth/key`). The "Get a free key" link
 * deep-links to OpenRouter's keys page.
 */

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';

import {
  ApiError,
  setStoredOpenRouterKey,
  validateOpenRouterKey,
  type ValidateKeyResponse,
} from '../lib/api';

interface ByoKeyTrapHandle {
  /** Open the modal explicitly (e.g. from a Settings "Update key" button). */
  open: () => void;
  /**
   * Inspect a thrown error. If it's a 402 byo_key_required from the API,
   * open the modal and return true (so the caller can swallow the error
   * — the user will retry after pasting a key). Otherwise return false
   * and the caller continues its normal error handling.
   */
  trap: (err: unknown) => boolean;
}

const ByoKeyTrapContext = createContext<ByoKeyTrapHandle | null>(null);

export function useByoKeyTrap(): ByoKeyTrapHandle {
  const ctx = useContext(ByoKeyTrapContext);
  if (!ctx) {
    throw new Error('useByoKeyTrap must be used inside <ByoKeyTrapProvider>');
  }
  return ctx;
}

export function ByoKeyTrapProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);

  const trap = useCallback((err: unknown): boolean => {
    if (err instanceof ApiError && err.code === 'byo_key_required') {
      setOpen(true);
      return true;
    }
    return false;
  }, []);

  const handle: ByoKeyTrapHandle = {
    open: () => setOpen(true),
    trap,
  };

  return (
    <ByoKeyTrapContext.Provider value={handle}>
      {children}
      {open && <ByoKeyModal onClose={() => setOpen(false)} />}
    </ByoKeyTrapContext.Provider>
  );
}

function ByoKeyModal({ onClose }: { onClose: () => void }) {
  const [key, setKey] = useState('');
  const [validating, setValidating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Esc closes — except while a validation request is in flight, since the
  // user dismissing mid-validate would be confusing (key stays unsaved with
  // no feedback). Mirrors WelcomeModal's pattern.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !validating) onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose, validating]);

  const submit = async () => {
    const trimmed = key.trim();
    if (!trimmed) {
      setError('Paste an OpenRouter key to continue.');
      return;
    }
    setValidating(true);
    setError(null);
    let resp: ValidateKeyResponse;
    try {
      resp = await validateOpenRouterKey(trimmed);
    } catch (e) {
      setValidating(false);
      setError(
        e instanceof Error ? e.message : 'Could not reach the server to validate.',
      );
      return;
    }
    setValidating(false);
    if (!resp.ok) {
      setError(resp.error ?? 'OpenRouter rejected this key.');
      return;
    }
    setStoredOpenRouterKey(trimmed);
    onClose();
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="byo-key-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4"
      onClick={(e) => {
        // Click on the backdrop (not the panel) closes — same exception as Esc.
        if (e.target === e.currentTarget && !validating) onClose();
      }}
    >
      <div className="w-full max-w-md rounded-xl border border-slate-700 bg-slate-900/95 shadow-2xl p-6">
        <h2 id="byo-key-modal-title" className="text-lg font-semibold text-white mb-2">
          Bring your own OpenRouter key
        </h2>
        <p className="text-[13px] text-slate-400 leading-relaxed mb-4">
          This is a public read-only sandbox. Each visitor uses their own free
          OpenRouter key so no one shares quota. Paste yours below — it stays
          in your browser{' '}
          <code className="font-mono text-[12px] text-slate-300">
            (localStorage)
          </code>{' '}
          and is sent only on chat / scan requests.
        </p>
        <label
          htmlFor="byo-or-key"
          className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1"
        >
          OpenRouter API key
        </label>
        <input
          id="byo-or-key"
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={key}
          onChange={(e) => setKey(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !validating) submit();
          }}
          placeholder="sk-or-v1-…"
          className="w-full font-mono text-[13px] bg-slate-950 border border-slate-700 rounded px-3 py-2 text-slate-100 outline-none focus:border-emerald-500/50"
          disabled={validating}
          autoFocus
        />
        {error && (
          <div className="mt-3 text-[12px] text-red-300 font-mono">⚠ {error}</div>
        )}
        <div className="mt-5 flex items-center justify-between gap-3">
          <a
            href="https://openrouter.ai/keys"
            target="_blank"
            rel="noreferrer"
            className="text-[12px] text-cyan-300 hover:text-cyan-200 underline-offset-2 hover:underline"
          >
            Get a free key →
          </a>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={validating}
              className="px-3 py-1.5 text-[12px] rounded-md text-slate-300 border border-slate-700 hover:bg-slate-800/60 disabled:opacity-50 transition"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={submit}
              disabled={validating || !key.trim()}
              className="px-3 py-1.5 text-[12px] rounded-md bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-semibold disabled:opacity-50 transition"
            >
              {validating ? 'Validating…' : 'Save & continue'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
