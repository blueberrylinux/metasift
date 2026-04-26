/**
 * LLM setup screen — Phase 3.5 slice 2b. Lifted from metasift+/MetaSift
 * App.html::LLMSetup (L2422-L2736), wired to the /llm/config + /llm/test
 * endpoints. Keeps the six-provider preset grid, MetaSift-defaults
 * one-click card, per-task routing accordion, connection test, and agent
 * tools inventory — but only the model + api_key + base_url + per-task
 * routes actually persist server-side (temperature/max-tokens/MCP toggle
 * are UI stubs matching the mockup for visual parity; wiring is a
 * follow-up once the LLM client exposes them).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';

import { AppLayout } from '../components/AppLayout';
import { EmptyState } from '../components/EmptyState';
import { PageHeader } from '../components/PageHeader';
import { Skeleton } from '../components/Skeleton';
import { toast } from 'sonner';

import {
  ApiError,
  getLLMCatalog,
  getLLMConfig,
  getOMConfig,
  resetLLMConfig,
  resetOMConfig,
  setLLMConfig,
  setOMConfig,
  testLLM,
  type LLMConfigResponse,
  type LLMTestResponse,
  type OMConfigResponse,
  type TaskModelMap,
} from '../lib/api';

// Provider presets — endpoints + curated model shortlist. Lifted from
// App.html::LLM_PROVIDERS (L2328). OpenRouter's model list is live-fetched;
// other providers use the shortlist so the dropdown isn't empty before the
// user has credentials for that endpoint.
interface Provider {
  id: string;
  name: string;
  tagline: string;
  models: string[];
  default: string;
  keyLabel: string;
  endpoint: string;
  recommended?: boolean;
  catalogNote?: string;
}

const PROVIDERS: Provider[] = [
  {
    id: 'openrouter',
    name: 'OpenRouter',
    tagline: '300+ models · MetaSift default',
    models: [
      'meta-llama/llama-3.3-70b-instruct',
      'openai/gpt-4o-mini',
      'anthropic/claude-3.5-sonnet',
      'google/gemini-2.0-flash',
    ],
    default: 'meta-llama/llama-3.3-70b-instruct',
    keyLabel: 'OPENROUTER_API_KEY',
    endpoint: 'https://openrouter.ai/api/v1',
    recommended: true,
    catalogNote: 'Live-fetched from /models',
  },
  {
    id: 'openai',
    name: 'OpenAI',
    tagline: 'gpt-4o-mini works great',
    models: ['gpt-4o', 'gpt-4o-mini', 'gpt-4.1-mini'],
    default: 'gpt-4o-mini',
    keyLabel: 'OPENAI_API_KEY',
    endpoint: 'https://api.openai.com/v1',
  },
  {
    id: 'gemini',
    name: 'Google Gemini',
    tagline: 'Flash is fast + cheap',
    models: ['gemini-2.0-flash', 'gemini-2.0-flash-lite', 'gemini-2.5-pro'],
    default: 'gemini-2.0-flash',
    keyLabel: 'GEMINI_API_KEY',
    endpoint: 'https://generativelanguage.googleapis.com/v1beta/openai',
  },
  {
    id: 'groq',
    name: 'Groq',
    tagline: 'Fastest OSS inference',
    models: ['llama-3.3-70b-versatile', 'llama-3.1-70b-versatile', 'mixtral-8x7b-32768'],
    default: 'llama-3.3-70b-versatile',
    keyLabel: 'GROQ_API_KEY',
    endpoint: 'https://api.groq.com/openai/v1',
  },
  {
    id: 'ollama',
    name: 'Ollama (local)',
    tagline: 'Air-gapped · zero cost',
    models: ['llama3.3:70b', 'llama3.1:8b', 'qwen2.5-coder:32b'],
    default: 'llama3.1:8b',
    keyLabel: 'no key required',
    endpoint: 'http://localhost:11434',
  },
  {
    id: 'custom',
    name: 'Custom (OpenAI-compatible)',
    tagline: 'Self-hosted vLLM, LiteLLM, Together, DeepSeek…',
    models: ['<your-model-id>'],
    default: '<your-model-id>',
    keyLabel: 'CUSTOM_API_KEY',
    endpoint: 'https://your-endpoint/v1',
  },
];

interface TaskRoute {
  key: keyof TaskModelMap;
  label: string;
  tip: string;
}

const TASK_ROUTES: TaskRoute[] = [
  { key: 'toolcall', label: 'Tool-calling', tip: "Reliable function-calling for Stew" },
  {
    key: 'reasoning',
    label: 'Reasoning',
    tip: 'Multi-step questions, "why is X failing?"',
  },
  { key: 'description', label: 'Auto-doc', tip: 'stewardship.auto_doc_table' },
  { key: 'stale', label: 'Stale-desc detection', tip: 'cleaning.detect_stale' },
  {
    key: 'scoring',
    label: 'Description scoring',
    tip: 'cleaning.score_quality · partial-JSON salvage',
  },
  {
    key: 'classification',
    label: 'Classification / DQ explain',
    tip: 'cleaning.run_dq_explanations · fix_type classifier',
  },
];

const METASIFT_DEFAULT_ROUTES: TaskModelMap = {
  toolcall: 'openai/gpt-4o-mini',
  reasoning: 'meta-llama/llama-3.3-70b-instruct',
  description: 'meta-llama/llama-3.3-70b-instruct',
  stale: 'meta-llama/llama-3.3-70b-instruct',
  scoring: 'meta-llama/llama-3.3-70b-instruct',
  classification: 'meta-llama/llama-3.3-70b-instruct',
};

function providerFor(endpoint: string): string {
  const match = PROVIDERS.find((p) => endpoint.startsWith(p.endpoint.replace(/\/$/, '')));
  return match?.id ?? 'custom';
}

export function Settings() {
  const qc = useQueryClient();
  // staleTime:Infinity + refetchOnWindowFocus:false so a background refetch
  // can't clobber the user's mid-edit routes. Save & Reset write to the
  // cache optimistically, which is the only refresh path we actually need.
  const configQ = useQuery({
    queryKey: ['llm', 'config'],
    queryFn: getLLMConfig,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
  const catalogQ = useQuery({
    queryKey: ['llm', 'catalog'],
    queryFn: getLLMCatalog,
    staleTime: 10 * 60_000,
  });

  // Local form state — mirrors the server config, but edits stay local
  // until the user hits Save. We don't auto-push every keystroke.
  const [providerId, setProviderId] = useState('openrouter');
  const [model, setModel] = useState('');
  const [apiKey, setApiKey] = useState(''); // empty = don't change on save
  const [showKey, setShowKey] = useState(false);
  const [apiKeyPlaceholder, setApiKeyPlaceholder] = useState('');
  const [routes, setRoutes] = useState<TaskModelMap>({
    toolcall: '',
    reasoning: '',
    description: '',
    stale: '',
    scoring: '',
    classification: '',
  });
  const [advOpen, setAdvOpen] = useState(true);
  const [defaultsApplied, setDefaultsApplied] = useState(false);
  const [testResult, setTestResult] = useState<LLMTestResponse | null>(null);

  // Seed local state from the server snapshot on initial load, and again
  // after Save/Reset cache writes (tracked via a version counter keyed to
  // the routes identity). Intentionally NOT a broad dependency on
  // configQ.data so routine refetches don't clobber the user's mid-edit
  // form — only the explicit Save/Reset paths bump this.
  const hasSeeded = useRef(false);
  useEffect(() => {
    if (!configQ.data || hasSeeded.current) return;
    hasSeeded.current = true;
    const c = configQ.data;
    setProviderId(providerFor(c.base_url));
    setModel(c.model);
    setApiKeyPlaceholder(c.api_key_preview || '');
    setRoutes(c.per_task_models);
  }, [configQ.data]);

  const provider = PROVIDERS.find((p) => p.id === providerId) ?? PROVIDERS[0];
  const modelOptions = useMemo(() => {
    if (provider.id !== 'openrouter') return provider.models;
    if (catalogQ.data?.models?.length) return catalogQ.data.models;
    return provider.models;
  }, [provider, catalogQ.data]);

  const save = useMutation({
    mutationFn: async () => {
      const body = {
        // Only send api_key if the user typed one — empty would CLEAR it.
        ...(apiKey ? { api_key: apiKey } : {}),
        base_url: provider.endpoint,
        model,
        per_task_models: routes,
      };
      return setLLMConfig(body);
    },
    onSuccess: async (next: LLMConfigResponse) => {
      qc.setQueryData(['llm', 'config'], next);
      qc.invalidateQueries({ queryKey: ['llm', 'catalog'] });
      setApiKey('');
      setApiKeyPlaceholder(next.api_key_preview);
      // Reflect server-canonical routes after save — the UI's routes object
      // is now authoritative on the server too.
      setRoutes(next.per_task_models);
    },
  });

  const reset = useMutation({
    mutationFn: resetLLMConfig,
    onSuccess: (next) => {
      qc.setQueryData(['llm', 'config'], next);
      setApiKey('');
      setApiKeyPlaceholder(next.api_key_preview);
      // Reset wipes overrides — pull the now-empty routes back into the form.
      setRoutes(next.per_task_models);
      setProviderId(providerFor(next.base_url));
      setModel(next.model);
      setDefaultsApplied(false);
      setTestResult(null);
    },
  });

  const runTest = useMutation({
    mutationFn: () =>
      testLLM({
        model,
        base_url: provider.endpoint,
        ...(apiKey ? { api_key: apiKey } : {}),
      }),
    onSuccess: (r) => setTestResult(r),
    onError: (e) => {
      setTestResult({
        ok: false,
        model,
        base_url: provider.endpoint,
        latency_ms: 0,
        response: '',
        error: e instanceof Error ? e.message : String(e),
      });
    },
  });

  const selectProvider = (id: string) => {
    setProviderId(id);
    const p = PROVIDERS.find((x) => x.id === id) ?? PROVIDERS[0];
    setModel(p.default);
    setTestResult(null);
  };

  const applyMetasiftDefaults = () => {
    selectProvider('openrouter');
    setModel(METASIFT_DEFAULT_ROUTES.reasoning);
    setRoutes(METASIFT_DEFAULT_ROUTES);
    setAdvOpen(true);
    setDefaultsApplied(true);
  };

  return (
    <AppLayout activeKey="llm">
      <PageHeader
        title="Settings"
        subtitle="OpenMetadata connection + LLM provider, model, and API key. Both can be rotated live without restarting the API."
        chips={[
          { label: `${provider.name} · ${model.split('/').pop()?.slice(0, 24) ?? model}`, tone: 'emerald' },
          { label: configQ.data?.api_key_set ? 'API key set' : 'no API key', tone: configQ.data?.api_key_set ? 'slate' : 'amber' },
        ]}
        rightButtons={
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => reset.mutate()}
              disabled={reset.isPending}
              className="text-[11px] px-2.5 py-1 rounded-md border border-slate-700 text-slate-300 hover:text-white hover:border-slate-600 disabled:opacity-50"
            >
              Reset to .env
            </button>
            <button
              type="button"
              onClick={() => runTest.mutate()}
              disabled={runTest.isPending}
              className="text-[11px] px-2.5 py-1 rounded-md border border-slate-700 text-slate-300 hover:text-emerald-300 hover:border-emerald-500/40 disabled:opacity-50"
            >
              {runTest.isPending ? 'Testing…' : 'Test connection'}
            </button>
            <button
              type="button"
              onClick={() => save.mutate()}
              disabled={save.isPending || !model}
              className="text-[11px] px-3 py-1 rounded-md bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-semibold disabled:opacity-50"
            >
              {save.isPending ? 'Saving…' : 'Save & reload agent'}
            </button>
          </div>
        }
      />

      <div className="flex-1 overflow-y-auto scrollbar-thin p-8">
        {configQ.isLoading ? (
          <SettingsSkeleton />
        ) : configQ.error ? (
          <EmptyState
            variant="error"
            icon="⚠"
            title="Couldn't load LLM config"
            body={(configQ.error as Error).message}
            hint="Check that the API is reachable on /api/v1/llm/config."
          />
        ) : (
          <>
            <OMConnectionPanel />
            <DefaultsBanner applied={defaultsApplied} onApply={applyMetasiftDefaults} />

            {save.error instanceof ApiError && (
              <Panel error>
                Save failed: {save.error.code} — {save.error.message}
              </Panel>
            )}
            {save.isSuccess && (
              <div className="mb-5 rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-4 py-2.5 text-[12px] text-emerald-300">
                ✓ Saved. The next /chat/stream call rebuilds the agent.
              </div>
            )}

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* Left: provider picker + info cards */}
              <div className="lg:col-span-1">
                <SectionLabel>Provider · {PROVIDERS.length} presets</SectionLabel>
                <div className="space-y-2">
                  {PROVIDERS.map((p) => {
                    const active = providerId === p.id;
                    return (
                      <button
                        key={p.id}
                        onClick={() => selectProvider(p.id)}
                        className={
                          'w-full text-left rounded-xl border p-4 transition ' +
                          (active
                            ? 'bg-emerald-500/10 border-emerald-500/40'
                            : 'border-slate-800 bg-slate-900/40 hover:border-slate-700')
                        }
                      >
                        <div className="flex items-center justify-between">
                          <span
                            className={
                              'text-[14px] font-semibold ' +
                              (active ? 'text-white' : 'text-slate-200')
                            }
                          >
                            {p.name}
                          </span>
                          {p.recommended && <span className="chip">recommended</span>}
                        </div>
                        <div className="text-[11px] text-slate-500 mt-1">{p.tagline}</div>
                        <div className="text-[10px] font-mono text-slate-600 mt-2">
                          {p.catalogNote ?? `${p.models.length} models`} ·{' '}
                          {p.id === 'ollama' ? 'local' : p.id === 'custom' ? 'BYO' : 'cloud'}
                        </div>
                      </button>
                    );
                  })}
                </div>

                <div className="mt-6 rounded-xl border border-slate-800 bg-slate-900/30 p-4">
                  <div className="flex items-start gap-2">
                    <span className="text-emerald-400 text-sm">🛡</span>
                    <div className="text-[11px] text-slate-400 leading-relaxed">
                      <div className="text-slate-300 font-semibold mb-1">Privacy</div>
                      MetaSift only sends <span className="text-emerald-300">structural metadata</span>{' '}
                      to external LLMs — column names, types, table names, descriptions. Never
                      sample data or actual records. Keys are session-scoped — not persisted to
                      disk by the port layer.
                    </div>
                  </div>
                </div>
              </div>

              {/* Right: config */}
              <div className="lg:col-span-2 space-y-5">
                {/* Model + endpoint + API key */}
                <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-6">
                  <SectionLabel>{provider.name} configuration</SectionLabel>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <FormField label="Model">
                      <select
                        value={model}
                        onChange={(e) => setModel(e.target.value)}
                        className="w-full bg-slate-950 border border-slate-800 rounded-md px-3 py-2 text-[13px] text-slate-200 font-mono focus:border-emerald-500/40 outline-none"
                      >
                        {modelOptions.map((m) => (
                          <option key={m} value={m}>
                            {m}
                          </option>
                        ))}
                        {!modelOptions.includes(model) && model && (
                          <option value={model}>{model} (custom)</option>
                        )}
                      </select>
                      {provider.id === 'openrouter' && catalogQ.data && (
                        <div className="text-[10px] font-mono text-slate-600 mt-1">
                          {catalogQ.data.source === 'openrouter'
                            ? `${catalogQ.data.models.length} models from /models`
                            : 'offline fallback list'}
                        </div>
                      )}
                    </FormField>
                    <FormField label="Endpoint">
                      <div className="w-full bg-slate-950 border border-slate-800 rounded-md px-3 py-2 text-[13px] text-slate-400 font-mono truncate">
                        {provider.endpoint}
                      </div>
                    </FormField>
                    <div className="md:col-span-2">
                      <label className="flex items-center justify-between text-[11px] text-slate-500 mb-1.5 font-medium">
                        <span>
                          API key{' '}
                          <span className="font-mono text-slate-600">({provider.keyLabel})</span>
                        </span>
                        {provider.id !== 'ollama' && (
                          <button
                            type="button"
                            onClick={() => setShowKey((v) => !v)}
                            className="text-[10px] text-emerald-300 hover:text-emerald-200"
                          >
                            {showKey ? 'Hide' : 'Reveal'}
                          </button>
                        )}
                      </label>
                      {provider.id === 'ollama' ? (
                        <div className="w-full bg-slate-950 border border-slate-800 rounded-md px-3 py-2 text-[13px] text-slate-500 italic">
                          No API key required — Ollama runs on {provider.endpoint}
                        </div>
                      ) : (
                        <input
                          type={showKey ? 'text' : 'password'}
                          value={apiKey}
                          onChange={(e) => setApiKey(e.target.value)}
                          placeholder={apiKeyPlaceholder || 'paste API key'}
                          className="w-full bg-slate-950 border border-slate-800 rounded-md px-3 py-2 text-[13px] text-slate-200 font-mono focus:border-emerald-500/40 outline-none"
                        />
                      )}
                      <div className="text-[10px] text-slate-600 mt-1 font-mono">
                        {apiKey
                          ? 'New key — will replace the active one on save.'
                          : apiKeyPlaceholder
                            ? `Current: ${apiKeyPlaceholder}. Leave blank to keep.`
                            : 'No key on file. .env value used as fallback.'}
                      </div>
                    </div>
                  </div>
                </div>

                {/* Advanced: per-task routing */}
                <div className="rounded-xl border border-slate-800 bg-slate-900/40 overflow-hidden">
                  <button
                    type="button"
                    onClick={() => setAdvOpen((o) => !o)}
                    className="w-full flex items-center justify-between px-6 py-4 hover:bg-slate-900/60 transition"
                  >
                    <div className="flex items-center gap-3">
                      <svg
                        className={'w-3 h-3 transition ' + (advOpen ? 'rotate-90' : '')}
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        viewBox="0 0 24 24"
                      >
                        <polyline points="9 18 15 12 9 6" />
                      </svg>
                      <div className="text-left">
                        <div className="text-[11px] uppercase tracking-wider text-emerald-400 font-semibold">
                          Advanced · per-task model routing
                        </div>
                        <div className="text-[11px] text-slate-500 mt-0.5">
                          Route each engine to a different model. Cheap-open-weight for bulk +
                          reliable-commercial for tool-calling.
                        </div>
                      </div>
                    </div>
                    <span className="chip slate">
                      {Object.values(routes).filter(Boolean).length} / {TASK_ROUTES.length}{' '}
                      overridden
                    </span>
                  </button>
                  {advOpen && (
                    <div className="px-6 pb-6 border-t border-slate-800">
                      <div className="space-y-2 mt-4">
                        {TASK_ROUTES.map((t) => {
                          const envDefault = configQ.data?.env_defaults[t.key] ?? '';
                          const routeVal = routes[t.key] || envDefault;
                          return (
                            <div
                              key={t.key}
                              className="grid grid-cols-1 md:grid-cols-[200px_1fr_auto] items-center gap-3 py-1.5 border-b border-slate-800/60 last:border-0"
                            >
                              <div>
                                <div className="text-[12px] text-slate-200 font-medium">
                                  {t.label}
                                </div>
                                <div className="text-[10px] text-slate-500">{t.tip}</div>
                              </div>
                              <select
                                value={routeVal}
                                onChange={(e) =>
                                  setRoutes((r) => ({ ...r, [t.key]: e.target.value }))
                                }
                                className="bg-slate-950 border border-slate-800 rounded-md px-3 py-1.5 text-[12px] text-slate-200 font-mono focus:border-emerald-500/40 outline-none"
                              >
                                {modelOptions.map((m) => (
                                  <option key={m} value={m}>
                                    {m}
                                  </option>
                                ))}
                                {routeVal && !modelOptions.includes(routeVal) && (
                                  <option value={routeVal}>{routeVal} (custom)</option>
                                )}
                              </select>
                              <span className="text-[10px] font-mono text-slate-600 whitespace-nowrap">
                                {routes[t.key] ? 'overridden' : `env: ${envDefault || '—'}`}
                              </span>
                            </div>
                          );
                        })}
                      </div>
                      <div className="mt-4 pt-3 border-t border-slate-800 flex items-center justify-between text-[11px]">
                        <span className="text-slate-500">
                          Ship the same config MetaSift does in prod:
                        </span>
                        <button
                          type="button"
                          onClick={applyMetasiftDefaults}
                          className="text-emerald-300 hover:text-emerald-200 underline"
                        >
                          Reset to MetaSift defaults
                        </button>
                      </div>
                    </div>
                  )}
                </div>

                {/* Test connection */}
                <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-6">
                  <div className="flex items-center justify-between mb-4">
                    <SectionLabel>Connection test</SectionLabel>
                    <button
                      type="button"
                      onClick={() => runTest.mutate()}
                      disabled={runTest.isPending}
                      className="text-[11px] px-2.5 py-1 rounded-md border border-slate-700 hover:border-emerald-500/40 text-slate-300 hover:text-emerald-300 transition disabled:opacity-50"
                    >
                      {runTest.isPending ? 'Running…' : 'Run test'}
                    </button>
                  </div>
                  {testResult === null ? (
                    <div className="text-[12px] text-slate-500">
                      Not tested yet — click Run test.
                    </div>
                  ) : testResult.ok ? (
                    <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-4">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="w-2 h-2 rounded-full bg-emerald-400" />
                        <span className="text-[13px] font-semibold text-emerald-300">
                          Connection OK
                        </span>
                        <span className="ml-auto font-mono text-[11px] text-slate-500">
                          {testResult.latency_ms}ms
                        </span>
                      </div>
                      <pre className="font-mono text-[11px] text-slate-400 leading-relaxed whitespace-pre-wrap">
                        {`> prompt: "respond with exactly: MetaSift ready"\n> ${provider.name} / ${testResult.model}\n> response: ${testResult.response}`}
                      </pre>
                    </div>
                  ) : (
                    <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-4">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="w-2 h-2 rounded-full bg-red-400" />
                        <span className="text-[13px] font-semibold text-red-300">
                          Connection failed
                        </span>
                        <span className="ml-auto font-mono text-[11px] text-slate-500">
                          {testResult.latency_ms}ms
                        </span>
                      </div>
                      <pre className="font-mono text-[11px] text-red-300/80 leading-relaxed whitespace-pre-wrap">
                        {testResult.error}
                      </pre>
                    </div>
                  )}
                </div>

                <AgentToolsCard />
              </div>
            </div>
          </>
        )}
      </div>
    </AppLayout>
  );
}

// ── Small pieces ──────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[11px] uppercase tracking-wider text-emerald-400 font-semibold mb-3">
      {children}
    </div>
  );
}

function FormField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-[11px] text-slate-500 mb-1.5 font-medium">{label}</label>
      {children}
    </div>
  );
}

// OpenMetadata connection — host + JWT entry. Server validates the token
// against /v1/services/databaseServices before persisting; on success the OM client
// cache is dropped so the next request hits OM with the new credentials.
// Existing /env values are kept as the bootstrap fallback if the user
// resets here. The token is never read back after save (server returns
// only `has_token`), so the input is empty on reload.
function OMConnectionPanel() {
  const qc = useQueryClient();
  const cfg = useQuery({
    queryKey: ['om', 'config'],
    queryFn: getOMConfig,
    retry: false,
  });
  const [host, setHost] = useState('');
  const [jwt, setJwt] = useState('');
  const [hostDirty, setHostDirty] = useState(false);
  const [revealJwt, setRevealJwt] = useState(false);

  // Load the persisted host into the editable input once on first fetch so
  // the user can edit without retyping. Only sync when the user hasn't
  // started typing — otherwise refetches would clobber their draft.
  useEffect(() => {
    if (cfg.data && !hostDirty) setHost(cfg.data.host);
  }, [cfg.data, hostDirty]);

  const save = useMutation({
    mutationFn: () => setOMConfig({ host: host.trim(), jwt: jwt.trim() }),
    onSuccess: (next: OMConfigResponse) => {
      qc.setQueryData(['om', 'config'], next);
      qc.invalidateQueries({ queryKey: ['health'] });
      qc.invalidateQueries({ queryKey: ['composite'] });
      setJwt('');
      setRevealJwt(false);
      toast.success('OpenMetadata connection updated', {
        description: 'Token rotated; clients reloaded.',
      });
    },
  });

  const reset = useMutation({
    mutationFn: () => resetOMConfig(),
    onSuccess: (next: OMConfigResponse) => {
      qc.setQueryData(['om', 'config'], next);
      qc.invalidateQueries({ queryKey: ['health'] });
      qc.invalidateQueries({ queryKey: ['composite'] });
      setJwt('');
      setHost(next.host);
      setHostDirty(false);
      toast.success('OpenMetadata connection reset to .env');
    },
  });

  if (cfg.isLoading) {
    return (
      <div className="mb-6 rounded-xl border border-slate-800 bg-slate-900/40 p-5">
        <Skeleton className="h-[14px] w-40 mb-3" />
        <Skeleton className="h-[36px] w-full mb-2" />
        <Skeleton className="h-[36px] w-full" />
      </div>
    );
  }
  if (cfg.error) {
    return (
      <Panel error>
        Couldn't load OpenMetadata config: {(cfg.error as Error).message}
      </Panel>
    );
  }
  const data = cfg.data!;
  const dirty = host.trim() !== data.host || jwt.trim().length > 0;
  const sourceTone =
    data.source === 'sqlite'
      ? 'text-emerald-300 border-emerald-500/30 bg-emerald-500/10'
      : data.source === 'env'
        ? 'text-slate-300 border-slate-700 bg-slate-900/60'
        : 'text-amber-300 border-amber-500/30 bg-amber-500/10';

  return (
    <div className="mb-6 rounded-xl border border-slate-800 bg-slate-900/40 p-5">
      <div className="flex items-start justify-between mb-3 gap-4">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">
            OpenMetadata connection
          </div>
          <div className="text-[12px] text-slate-400 mt-1 max-w-2xl">
            Rotate the JWT after a <code className="font-mono text-slate-300">make stack-down</code>{' '}
            without editing <code className="font-mono text-slate-300">.env</code>. The server
            validates against <code className="font-mono text-slate-300">/v1/services/databaseServices</code>{' '}
            before saving — a typo can't lock you out.
          </div>
        </div>
        <span
          className={
            'shrink-0 text-[10px] font-mono uppercase tracking-wider px-2 py-1 rounded border ' +
            sourceTone
          }
        >
          {data.source === 'sqlite'
            ? 'set via UI'
            : data.source === 'env'
              ? 'from .env'
              : 'no token'}
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <FormField label="Host">
          <input
            type="text"
            value={host}
            placeholder="http://localhost:8585"
            onChange={(e) => {
              setHost(e.target.value);
              setHostDirty(true);
            }}
            className="w-full bg-slate-950 border border-slate-800 rounded-md px-3 py-2 text-[13px] text-slate-200 font-mono focus:border-emerald-500/40 outline-none"
          />
        </FormField>
        <FormField label="JWT token">
          <div className="relative">
            <input
              type={revealJwt ? 'text' : 'password'}
              value={jwt}
              onChange={(e) => setJwt(e.target.value)}
              placeholder={data.has_token ? '•••••••• (token configured)' : 'Paste ingestion-bot JWT'}
              autoComplete="off"
              className="w-full bg-slate-950 border border-slate-800 rounded-md px-3 py-2 pr-16 text-[13px] text-slate-200 font-mono focus:border-emerald-500/40 outline-none"
            />
            <button
              type="button"
              onClick={() => setRevealJwt((r) => !r)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] font-mono text-slate-500 hover:text-slate-300 px-1.5 py-0.5"
            >
              {revealJwt ? 'hide' : 'show'}
            </button>
          </div>
        </FormField>
      </div>

      {save.error instanceof ApiError && (
        <div className="mt-3 rounded-md border border-red-500/30 bg-red-500/5 px-3 py-2 text-[12px] text-red-300">
          {save.error.message}
        </div>
      )}

      <div className="flex items-center gap-2 mt-4">
        <button
          type="button"
          onClick={() => save.mutate()}
          disabled={save.isPending || !dirty || !host.trim() || !jwt.trim()}
          className="text-[12px] px-4 py-1.5 rounded-md bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-semibold disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {save.isPending ? 'Saving…' : 'Save & test'}
        </button>
        <button
          type="button"
          onClick={() => reset.mutate()}
          disabled={reset.isPending || data.source !== 'sqlite'}
          title={data.source === 'sqlite' ? 'Drop the UI-saved values and fall back to .env' : 'Already using .env'}
          className="text-[11px] px-2.5 py-1 rounded-md border border-slate-700 text-slate-300 hover:text-white hover:border-slate-600 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {reset.isPending ? 'Resetting…' : 'Reset to .env'}
        </button>
        <div className="flex-1" />
        <a
          href="http://localhost:8585/bots/ingestion-bot"
          target="_blank"
          rel="noreferrer"
          className="text-[11px] text-cyan-300 hover:text-cyan-200 underline"
        >
          Open ingestion-bot in OpenMetadata ↗
        </a>
      </div>
    </div>
  );
}

function DefaultsBanner({ applied, onApply }: { applied: boolean; onApply: () => void }) {
  return (
    <div
      className={
        'mb-6 rounded-xl border p-5 flex items-center gap-5 transition ' +
        (applied
          ? 'border-emerald-500/40 bg-emerald-500/[0.07]'
          : 'border-cyan-500/30 bg-gradient-to-r from-cyan-500/[0.06] to-emerald-500/[0.06]')
      }
    >
      <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-emerald-500/20 to-cyan-500/20 border border-emerald-500/30 flex items-center justify-center shrink-0">
        <span className="text-2xl">⚡</span>
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <div className="text-[14px] font-semibold text-white">Use MetaSift defaults</div>
          {applied && <span className="chip">applied</span>}
        </div>
        <div className="text-[12px] text-slate-400 mt-0.5 leading-snug">
          One-click config: <span className="font-mono text-emerald-300">Llama 3.3 70B</span>{' '}
          for 5 tasks + <span className="font-mono text-emerald-300">GPT-4o-mini</span> for
          tool-calling (avoids Llama's introspection loops). Paste an OpenRouter key to use it.
        </div>
      </div>
      <button
        type="button"
        onClick={onApply}
        className="shrink-0 text-[12px] px-4 py-2 rounded-md bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-semibold"
      >
        {applied ? 'Re-apply' : 'Apply defaults'}
      </button>
    </div>
  );
}

// Agent-tools inventory card — mirrors the mockup's 6-bucket grid with
// fixed content (the engine's tool lists don't change per-request, so we
// keep the copy static until a /llm/tools surface is needed).
function AgentToolsCard() {
  const buckets: { title: string; items: string[]; muted?: boolean }[] = [
    {
      title: 'Discovery',
      items: ['list_services', 'list_schemas', 'list_tables', 'about_metasift', 'run_sql'],
    },
    {
      title: 'Analysis',
      items: [
        'composite_score',
        'documentation_coverage',
        'ownership_report',
        'impact_check',
        'pii_propagation',
      ],
    },
    {
      title: 'Cleaning',
      items: [
        'check_description_staleness',
        'find_tag_conflicts',
        'score_descriptions',
        'find_naming_inconsistencies',
      ],
    },
    {
      title: 'Stewardship',
      items: [
        'generate_description_for',
        'auto_document_schema',
        'apply_description',
        'scan_pii',
        'find_pii_gaps',
        'apply_pii_tag',
      ],
    },
    {
      title: 'DQ · risk',
      items: [
        'dq_failures_summary',
        'dq_explain',
        'recommend_dq_tests',
        'find_dq_gaps',
        'dq_impact',
        'dq_risk_catalog',
      ],
    },
    {
      title: 'MCP (OpenMetadata)',
      items: ['search_metadata', 'get_entity_details', 'get_entity_lineage'],
    },
  ];
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <SectionLabel>Agent tools</SectionLabel>
          <div className="text-[11px] text-slate-500 mt-0.5">
            27 local MetaSift tools + 3 allowlisted MCP = up to 30 tools per turn
          </div>
        </div>
        <span className="chip">30 loaded</span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {buckets.map((b) => (
          <div
            key={b.title}
            className="rounded-lg border border-slate-800 bg-slate-950/40 p-3"
          >
            <div className="flex items-center justify-between mb-2">
              <div className="text-[12px] font-semibold text-slate-200">{b.title}</div>
              <span className="text-[10px] font-mono text-slate-600">{b.items.length}</span>
            </div>
            <ul className="space-y-0.5 text-[10px] font-mono text-slate-500 leading-relaxed">
              {b.items.map((i) => (
                <li key={i} className="truncate">
                  {i}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="mt-4 pt-3 border-t border-slate-800 flex items-center gap-2 flex-wrap text-[10px] font-mono">
        <span className="text-slate-500">Explicitly excluded from MCP:</span>
        <span className="px-1.5 py-0.5 rounded bg-slate-900 border border-slate-800 text-slate-600 line-through">
          patch_entity
        </span>
        <span className="px-1.5 py-0.5 rounded bg-slate-900 border border-slate-800 text-slate-600 line-through">
          create_glossary*
        </span>
        <span className="text-slate-500">— writes must flow through the review queue.</span>
      </div>
    </div>
  );
}

function Panel({ children, error }: { children: React.ReactNode; error?: boolean }) {
  return (
    <div
      className={
        'rounded-xl border px-6 py-4 text-sm mb-5 ' +
        (error
          ? 'border-red-500/30 bg-red-500/5 text-red-300 font-mono'
          : 'border-slate-800 bg-slate-900/40 text-slate-400')
      }
    >
      {children}
    </div>
  );
}

// Settings is dense enough that a single skeleton block would feel wrong —
// mirror the provider-panel + routing-grid split so first-paint matches
// the resolved layout.
function SettingsSkeleton() {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <div className="lg:col-span-1 space-y-3">
        <Skeleton className="h-[16px] w-40" />
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-[58px] w-full rounded-lg" />
        ))}
      </div>
      <div className="lg:col-span-2 space-y-3">
        <Skeleton className="h-[16px] w-48" />
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-[46px] w-full rounded-lg" />
        ))}
      </div>
    </div>
  );
}
