/**
 * Compact model picker that sits alongside the Composer. Fetches the full
 * OpenRouter catalog (cached server-side for an hour) and shows the current
 * selection; on change POSTs to /llm/model which clears the LLM cache and
 * drops the agent singleton so the next /chat/stream call rebuilds with
 * the new model.
 *
 * Session-scoped like the Streamlit version — not persisted across restarts.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { ApiError, getLLMCatalog, setLLMModel, type LLMCatalogResponse } from '../lib/api';

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

  if (catalog.isLoading) {
    return <Wrapper>Loading models…</Wrapper>;
  }
  if (catalog.error) {
    return <Wrapper>LLM config unavailable</Wrapper>;
  }
  if (!catalog.data) return null;

  const { models, current, source } = catalog.data;
  const options = models.includes(current) ? models : [current, ...models];

  return (
    <Wrapper>
      <span className="font-mono text-slate-500 shrink-0">🧠</span>
      <select
        value={current}
        disabled={apply.isPending}
        onChange={(e) => apply.mutate(e.target.value)}
        className="bg-slate-800 border border-slate-700 rounded px-1.5 py-0.5 text-[10px] text-slate-300 font-mono focus:outline-none focus:border-emerald-500/60 disabled:opacity-60 max-w-[160px]"
        title={source === 'fallback' ? 'Showing offline fallback list — OpenRouter fetch failed' : ''}
      >
        {options.map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
      </select>
      {apply.isPending && <span className="font-mono text-slate-500 shrink-0">saving…</span>}
      {apply.error instanceof ApiError ? (
        <span className="font-mono text-red-300 shrink-0 truncate">{apply.error.message}</span>
      ) : null}
    </Wrapper>
  );
}

function Wrapper({ children }: { children: React.ReactNode }) {
  // Inline in the Composer footer — no top margin, tight gap so the picker
  // sits flush with the other footer hints ("tools · writes gated").
  return <div className="flex items-center gap-1.5 min-w-0">{children}</div>;
}
