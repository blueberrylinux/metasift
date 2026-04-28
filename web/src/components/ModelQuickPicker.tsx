/**
 * Compact model picker that sits alongside the Composer. Fetches the full
 * OpenRouter catalog (cached server-side for an hour) and shows the current
 * selection; on change POSTs to /llm/model which clears the LLM cache and
 * drops the agent singleton so the next /chat/stream call rebuilds with
 * the new model.
 *
 * Session-scoped like the Streamlit version — not persisted across restarts.
 *
 * Presentation lifted from metasift+/MetaSift App.html::ModelQuickPicker
 * (L513-L551): green-dot + model-suffix button that opens a 320px
 * filterable popover above the composer. Click-outside / Escape close;
 * checkmark flags the current selection.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';

import { ApiError, getLLMCatalog, setLLMModel, type LLMCatalogResponse } from '../lib/api';

const MAX_VISIBLE = 16;

export function ModelQuickPicker() {
  const qc = useQueryClient();
  const catalog = useQuery({
    queryKey: ['llm', 'catalog'],
    queryFn: getLLMCatalog,
    staleTime: 10 * 60_000,
  });
  const apply = useMutation({
    mutationFn: (model: string) => setLLMModel(model),
    onSuccess: (r) => {
      qc.setQueryData<LLMCatalogResponse>(['llm', 'catalog'], (prev) =>
        prev ? { ...prev, current: r.model } : prev,
      );
    },
  });

  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const rootRef = useRef<HTMLDivElement | null>(null);

  // Close on click-outside + Escape. Bound only while open so the document
  // listener doesn't stay live for every Composer on the page.
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  if (catalog.isLoading) {
    return <span className="font-mono text-slate-500 shrink-0">Loading models…</span>;
  }
  if (catalog.error || !catalog.data) {
    return <span className="font-mono text-slate-500 shrink-0">LLM config unavailable</span>;
  }

  const { models, current, source } = catalog.data;
  const options = models.includes(current) ? models : [current, ...models];
  const filtered = options.filter((m) => m.toLowerCase().includes(q.toLowerCase()));
  const visible = filtered.slice(0, MAX_VISIBLE);

  const choose = (m: string) => {
    if (m !== current) apply.mutate(m);
    setOpen(false);
    setQ('');
  };

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        disabled={apply.isPending}
        title={
          source === 'fallback'
            ? 'Showing offline fallback list — OpenRouter fetch failed'
            : undefined
        }
        className="flex items-center gap-1.5 text-[10px] text-slate-400 hover:text-slate-100 transition disabled:opacity-60"
      >
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
        <span className="font-mono">{modelSuffix(current)}</span>
        <svg
          width="9"
          height="9"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          viewBox="0 0 24 24"
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>
      {apply.isPending && (
        <span className="ml-2 font-mono text-slate-500 shrink-0 text-[10px]">saving…</span>
      )}
      {apply.error ? (
        <span className="ml-2 font-mono text-red-300 shrink-0 truncate text-[10px]">
          {apply.error instanceof ApiError
            ? apply.error.message
            : apply.error instanceof Error
              ? apply.error.message
              : String(apply.error)}
        </span>
      ) : null}

      {open && (
        <div className="absolute bottom-full left-0 mb-2 w-[min(320px,calc(100vw-2rem))] rounded-lg bg-slate-950 border border-slate-800 shadow-2xl overflow-hidden z-40">
          <div className="px-3 py-2 border-b border-slate-800">
            <input
              autoFocus
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={`Filter ${options.length} models…`}
              className="w-full bg-transparent outline-none text-[12px] text-slate-200 placeholder:text-slate-600"
            />
          </div>
          <div className="max-h-[240px] overflow-y-auto scrollbar-thin">
            {visible.map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => choose(m)}
                className={
                  'w-full text-left px-3 py-1.5 text-[11px] font-mono transition flex items-center gap-2 ' +
                  (m === current
                    ? 'bg-emerald-500/10 text-emerald-200'
                    : 'text-slate-300 hover:bg-slate-900')
                }
              >
                {m === current ? <span className="text-emerald-400">✓</span> : <span className="w-3" />}
                <span className="truncate">{m}</span>
              </button>
            ))}
            {filtered.length === 0 && (
              <div className="px-3 py-3 text-[11px] text-slate-500">No models match "{q}"</div>
            )}
          </div>
          <div className="px-3 py-1.5 border-t border-slate-800 text-[9px] font-mono text-slate-600">
            showing {visible.length} of {filtered.length} · full catalog in LLM setup
          </div>
        </div>
      )}
    </div>
  );
}

// Model IDs look like `meta-llama/llama-3.3-70b-instruct:free` — the
// mockup only shows the segment after the provider slash so the button
// stays narrow enough to coexist with the rest of the footer hints.
function modelSuffix(id: string): string {
  return id.split('/').pop() ?? id;
}
