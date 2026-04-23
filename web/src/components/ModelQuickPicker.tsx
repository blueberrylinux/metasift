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
      <span className="text-mini font-mono text-ink-dim">🧠</span>
      <select
        value={current}
        disabled={apply.isPending}
        onChange={(e) => apply.mutate(e.target.value)}
        className="bg-ink-panel border border-ink-border rounded px-2 py-1 text-xs text-ink-text font-mono focus:outline-none focus:border-accent/60 disabled:opacity-60 max-w-xs"
        title={source === 'fallback' ? 'Showing offline fallback list — OpenRouter fetch failed' : ''}
      >
        {options.map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
      </select>
      {apply.isPending && <span className="text-mini font-mono text-ink-dim">saving…</span>}
      {apply.error instanceof ApiError ? (
        <span className="text-mini font-mono text-error-soft">{apply.error.message}</span>
      ) : null}
    </Wrapper>
  );
}

function Wrapper({ children }: { children: React.ReactNode }) {
  return <div className="flex items-center gap-2 mt-2">{children}</div>;
}
