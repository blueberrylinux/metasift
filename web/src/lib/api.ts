/**
 * Typed API client. One place to swap transport (fetch ↔ streaming).
 *
 * Phase 0: just /health. Later phases add chat SSE, review, viz, report, DQ,
 * scans/SSE, LLM setup, etc. — each keeps its shape here so the UI never
 * hand-rolls fetch() inside components.
 */

export const API = '/api/v1';

export class ApiError extends Error {
  code: string;
  detail: unknown;

  constructor(code: string, message: string, detail?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.detail = detail;
  }
}

async function parseOrThrow<T>(r: Response, path: string): Promise<T> {
  if (r.ok) return r.json() as Promise<T>;
  // Try to decode our structured ErrorShape; fall back to HTTP text.
  let code = 'internal_error';
  let message = `${path}: ${r.status}`;
  let detail: unknown;
  try {
    const body = await r.json();
    const raw = body?.detail ?? body;
    if (raw && typeof raw === 'object') {
      if (typeof raw.code === 'string') code = raw.code;
      if (typeof raw.message === 'string') message = raw.message;
      if ('detail' in raw) detail = raw.detail;
    }
  } catch {
    // non-JSON error body — keep the fallbacks
  }
  throw new ApiError(code, message, detail);
}

export async function getJSON<T>(path: string): Promise<T> {
  const r = await fetch(API + path);
  return parseOrThrow<T>(r, path);
}

export async function postJSON<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(API + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return parseOrThrow<T>(r, path);
}

// ── /health ────────────────────────────────────────────────────────────────

export interface HealthResponse {
  ok: boolean;
  om: boolean;
  llm: boolean;
  duck: boolean;
  sqlite: boolean;
  version: string;
}

export function getHealth(): Promise<HealthResponse> {
  return getJSON<HealthResponse>('/health');
}

// ── /analysis ──────────────────────────────────────────────────────────────
//
// Composite score drives the dashboard hero donut. `scanned` is false until
// the deep-scan has run — the UI should render accuracy/quality as em-dashes
// in that state rather than "0%". All four sub-metrics are 0-100 floats.

export interface CompositeScore {
  coverage: number;
  accuracy: number;
  consistency: number;
  quality: number;
  composite: number;
  scanned: boolean;
}

export interface CoverageRow {
  database: string;
  schema: string;
  total: number;
  documented: number;
  coverage_pct: number;
}

export interface CoverageResponse {
  rows: CoverageRow[];
}

export interface RefreshResponse {
  run_id: number;
  counts: Record<string, number>;
  duration_ms: number;
}

export interface DataSourceRow {
  service: string;
  kind: string;
  type: string | null;
  tables: number;
}

export interface DataSourcesResponse {
  rows: DataSourceRow[];
}

export function getComposite(): Promise<CompositeScore> {
  return getJSON<CompositeScore>('/analysis/composite');
}

export function getCoverage(schema?: string): Promise<CoverageResponse> {
  const qs = schema ? `?schema=${encodeURIComponent(schema)}` : '';
  return getJSON<CoverageResponse>(`/analysis/coverage${qs}`);
}

export function getDataSources(): Promise<DataSourcesResponse> {
  return getJSON<DataSourcesResponse>('/analysis/data-sources');
}

export function postRefresh(): Promise<RefreshResponse> {
  return postJSON<RefreshResponse>('/analysis/refresh');
}

// ── /chat ──────────────────────────────────────────────────────────────────
//
// POST /chat/stream is Server-Sent Events over fetch (EventSource doesn't do
// POST bodies). Five frame types — {token, tool_call, tool_result, final,
// error} — arrive `\n\n`-separated; we demux in streamChat().
//
// Conversations: POST / GET (list) / GET (detail). `conversation_id` on a
// stream request makes the backend load prior turns and persist the new
// one atomically.

export type ChatRole = 'user' | 'assistant';

export interface ChatMessage {
  role: ChatRole;
  content: string;
}

export interface ToolTraceEntry {
  tool: string;
  args: unknown;
  result: unknown;
}

export interface ConversationSummary {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConversationListResponse {
  rows: ConversationSummary[];
}

export interface PersistedMessage {
  id: number;
  role: ChatRole;
  content: string;
  tool_trace: ToolTraceEntry[] | null;
  created_at: string;
}

export interface ConversationDetail {
  conversation: ConversationSummary;
  messages: PersistedMessage[];
}

export function createConversation(title?: string): Promise<ConversationSummary> {
  return postJSON<ConversationSummary>('/chat/conversations', { title: title ?? null });
}

export function listConversations(limit = 50): Promise<ConversationListResponse> {
  return getJSON<ConversationListResponse>(`/chat/conversations?limit=${limit}`);
}

export function getConversation(id: string): Promise<ConversationDetail> {
  return getJSON<ConversationDetail>(`/chat/conversations/${encodeURIComponent(id)}`);
}

// ── SSE frames ─────────────────────────────────────────────────────────────

export type ChatFrame =
  | { type: 'token'; text: string }
  | { type: 'tool_call'; id: string; name: string; args: Record<string, unknown> }
  | { type: 'tool_result'; id: string; content: string }
  | { type: 'final'; text: string }
  | { type: 'error'; message: string };

export interface ChatStreamRequest {
  question: string;
  conversation_id?: string;
  history?: ChatMessage[];
}

// SSE event blocks can be terminated by \r\n\r\n (sse-starlette's default),
// \n\n, or \r\r per the WHATWG SSE spec. Match any of the three.
const SSE_BLOCK_SPLIT = /\r\n\r\n|\n\n|\r\r/;

function parseSSEBlock(block: string): ChatFrame | null {
  // Inside a block, lines can end with \r\n or \n or \r. Split on any of them,
  // then pick out `data:` lines (ignoring the `event:` hint — our payload's
  // JSON carries `type` already).
  const dataLines: string[] = [];
  for (const line of block.split(/\r\n|\n|\r/)) {
    if (line.startsWith('data: ')) dataLines.push(line.slice(6));
    else if (line.startsWith('data:')) dataLines.push(line.slice(5));
  }
  if (!dataLines.length) return null;
  try {
    return JSON.parse(dataLines.join('\n')) as ChatFrame;
  } catch {
    return null;
  }
}

function splitNextBlock(buf: string): { block: string; rest: string } | null {
  const m = SSE_BLOCK_SPLIT.exec(buf);
  if (!m) return null;
  return { block: buf.slice(0, m.index), rest: buf.slice(m.index + m[0].length) };
}

export async function streamChat(
  req: ChatStreamRequest,
  onFrame: (frame: ChatFrame) => void,
  signal?: AbortSignal,
): Promise<void> {
  const r = await fetch(`${API}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(req),
    signal,
  });
  if (!r.ok) {
    // Non-2xx before streaming starts — e.g. 404 for missing conversation_id.
    // Reuse parseOrThrow so the error shape matches the rest of the client.
    await parseOrThrow<unknown>(r, '/chat/stream');
    return;
  }
  if (!r.body) throw new ApiError('internal_error', '/chat/stream: empty body');

  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      while (true) {
        const next = splitNextBlock(buf);
        if (!next) break;
        buf = next.rest;
        const frame = parseSSEBlock(next.block);
        if (frame) onFrame(frame);
      }
    }
    // Flush any trailing block if the server closed without a final separator.
    if (buf.trim()) {
      const frame = parseSSEBlock(buf);
      if (frame) onFrame(frame);
    }
  } finally {
    // Always release the reader lock so the underlying stream can be GC'd,
    // even if the caller aborts or onFrame throws.
    try {
      reader.releaseLock();
    } catch {
      // reader may already be in a released state if cancel() fired
    }
  }
}

// ── /llm ───────────────────────────────────────────────────────────────────
//
// Slice-4 scope: the dropdown only picks a shared model. api_key / base_url
// / per-task routing land in a later phase alongside a richer settings UI.

export interface LLMCatalogResponse {
  models: string[];
  current: string;
  source: 'openrouter' | 'fallback';
}

export interface ModelConfig {
  model: string;
}

export function getLLMCatalog(): Promise<LLMCatalogResponse> {
  return getJSON<LLMCatalogResponse>('/llm/catalog');
}

export function setLLMModel(model: string): Promise<ModelConfig> {
  return postJSON<ModelConfig>('/llm/model', { model });
}

// Full config surface (Phase 3.5 slice 2b).

export interface TaskModelMap {
  toolcall: string;
  reasoning: string;
  description: string;
  stale: string;
  scoring: string;
  classification: string;
}

export interface LLMConfigResponse {
  api_key_set: boolean;
  api_key_preview: string;
  base_url: string;
  model: string;
  per_task_models: TaskModelMap;
  env_defaults: TaskModelMap;
}

export interface SetLLMConfigRequest {
  api_key?: string;
  base_url?: string;
  model?: string;
  per_task_models?: Partial<TaskModelMap>;
}

export interface LLMTestRequest {
  model?: string;
  api_key?: string;
  base_url?: string;
}

export interface LLMTestResponse {
  ok: boolean;
  model: string;
  base_url: string;
  latency_ms: number;
  response: string;
  error: string | null;
}

export function getLLMConfig(): Promise<LLMConfigResponse> {
  return getJSON<LLMConfigResponse>('/llm/config');
}

export function setLLMConfig(req: SetLLMConfigRequest): Promise<LLMConfigResponse> {
  return postJSON<LLMConfigResponse>('/llm/config', req);
}

export async function resetLLMConfig(): Promise<LLMConfigResponse> {
  const r = await fetch(`${API}/llm/config`, { method: 'DELETE' });
  return parseOrThrow<LLMConfigResponse>(r, '/llm/config');
}

export function testLLM(req: LLMTestRequest = {}): Promise<LLMTestResponse> {
  return postJSON<LLMTestResponse>('/llm/test', req);
}

// ── /review ────────────────────────────────────────────────────────────────
//
// Pending suggestions from the cleaning + PII scans, plus auto-drafts for
// undocumented tables. `key` is the opaque id the accept/edit/reject
// endpoints expect — do not construct it client-side.

export type ReviewKind = 'description' | 'pii_tag';

export interface ReviewItem {
  kind: ReviewKind;
  key: string;
  fqn: string;
  column: string | null;
  old: string | null;
  new: string;
  confidence: number;
  reason: string;
}

export interface ReviewListResponse {
  rows: ReviewItem[];
}

export type ReviewActionStatus = 'accepted' | 'rejected' | 'accepted_edited';

export interface ReviewAcceptResponse {
  action_id: number;
  status: ReviewActionStatus;
  after_val: string;
}

export function listReview(kind?: ReviewKind): Promise<ReviewListResponse> {
  const qs = kind ? `?kind=${kind}` : '';
  return getJSON<ReviewListResponse>(`/review${qs}`);
}

export function acceptReview(itemId: string): Promise<ReviewAcceptResponse> {
  return postJSON<ReviewAcceptResponse>(`/review/${encodeURIComponent(itemId)}/accept`);
}

export function acceptEditedReview(itemId: string, value: string): Promise<ReviewAcceptResponse> {
  return postJSON<ReviewAcceptResponse>(
    `/review/${encodeURIComponent(itemId)}/accept-edited`,
    { value },
  );
}

export function rejectReview(itemId: string): Promise<ReviewAcceptResponse> {
  return postJSON<ReviewAcceptResponse>(`/review/${encodeURIComponent(itemId)}/reject`);
}

// ── /scans ─────────────────────────────────────────────────────────────────
//
// Each endpoint is an SSE POST mirroring the /chat/stream adapter — same
// \r\n\r\n tolerance, same fetch-plus-ReadableStream plumbing. Three frame
// types: progress, done, error. Scans without a progress_cb (refresh,
// pii_scan) emit only done or error.

export type ScanKind =
  | 'refresh'
  | 'deep_scan'
  | 'pii_scan'
  | 'dq_explain'
  | 'dq_recommend'
  | 'bulk_doc';

// URL-path form differs from the store/kind id for the two snake_case kinds.
const SCAN_PATH: Record<ScanKind, string> = {
  refresh: 'refresh',
  deep_scan: 'deep-scan',
  pii_scan: 'pii-scan',
  dq_explain: 'dq-explain',
  dq_recommend: 'dq-recommend',
  bulk_doc: 'bulk-doc',
};

export type ScanFrame =
  | { type: 'progress'; run_id: number; step: number; total: number; label: string }
  | { type: 'done'; run_id: number; counts: Record<string, unknown> }
  | { type: 'error'; run_id: number; message: string };

export interface BulkDocBody {
  schema_name: string;
  max_tables?: number;
}

export interface ScanRun {
  id: number;
  kind: string;
  started_at: string;
  finished_at: string | null;
  status: 'running' | 'completed' | 'failed' | 'cancelled';
  counts: Record<string, unknown> | null;
  error: string | null;
}

export interface ScanStatusResponse {
  kinds: Record<string, ScanRun | null>;
}

export function getScanStatus(): Promise<ScanStatusResponse> {
  return getJSON<ScanStatusResponse>('/scans/status');
}

// Parse an SSE block the same way `parseSSEBlock` does for /chat/stream, but
// typed to the ScanFrame union. Extracted inline — lifting into a shared
// helper would require widening the frame type and lose the narrowing the
// two callers get today.
function parseSSEBlockScan(block: string): ScanFrame | null {
  const dataLines: string[] = [];
  for (const line of block.split(/\r\n|\n|\r/)) {
    if (line.startsWith('data: ')) dataLines.push(line.slice(6));
    else if (line.startsWith('data:')) dataLines.push(line.slice(5));
  }
  if (!dataLines.length) return null;
  try {
    return JSON.parse(dataLines.join('\n')) as ScanFrame;
  } catch {
    return null;
  }
}

// ── /viz ───────────────────────────────────────────────────────────────────
//
// Each /viz/{slug} returns a Plotly figure JSON (data + layout + frames) or
// {figure: null} when the builder had no data. React hands the non-null
// payload straight to <Plot data={fig.data} layout={fig.layout} />.

export interface VizTabMeta {
  slug: string;
  label: string;
  caption: string;
}

export interface VizListResponse {
  tabs: VizTabMeta[];
}

export interface VizFigureResponse {
  figure: {
    data: unknown[];
    layout: Record<string, unknown>;
    frames?: unknown[];
  } | null;
}

export function listVizTabs(): Promise<VizListResponse> {
  return getJSON<VizListResponse>('/viz');
}

export function getVizFigure(slug: string): Promise<VizFigureResponse> {
  return getJSON<VizFigureResponse>(`/viz/${encodeURIComponent(slug)}`);
}

// ── /dq ────────────────────────────────────────────────────────────────────
//
// All DQ views read from the DuckDB caches populated by the slice-2 scan
// endpoints. Empty responses carry hints (`scan_run: false`,
// `explanations_loaded: false`) so the UI can render specific CTAs instead
// of a blanket "no data" message.

export type FixType =
  | 'schema_change'
  | 'etl_investigation'
  | 'data_correction'
  | 'upstream_fix'
  | 'other';
export type Severity = 'critical' | 'recommended' | 'nice-to-have';

export interface DQSummaryResponse {
  total: number;
  failed: number;
  passed: number;
  failing_tables: number;
}

export interface DQExplanation {
  summary: string;
  likely_cause: string;
  next_step: string;
  fix_type: FixType;
}

export interface DQFailure {
  test_id: string;
  test_name: string;
  table_fqn: string;
  column_name: string | null;
  test_definition_name: string | null;
  result_message: string | null;
  explanation: DQExplanation | null;
}

export interface DQFailuresResponse {
  summary: DQSummaryResponse;
  rows: DQFailure[];
  explanations_loaded: boolean;
}

export interface DQRecommendation {
  table_fqn: string;
  column_name: string | null;
  test_definition: string;
  parameters: Array<Record<string, unknown>>;
  rationale: string;
  severity: Severity;
}

export interface DQRecommendationsResponse {
  rows: DQRecommendation[];
  scan_run: boolean;
}

export interface DQRiskRow {
  fqn: string;
  failed_tests: number;
  direct: number;
  transitive: number;
  pii_downstream: number;
  risk_score: number;
}

export interface DQRiskResponse {
  rows: DQRiskRow[];
}

export interface DQImpactResponse {
  fqn: string;
  failed_tests: number;
  failing_test_names: string[];
  direct: number;
  transitive: number;
  pii_downstream: number;
  downstream_fqns: string[];
  risk_score: number;
}

export function getDQSummary(): Promise<DQSummaryResponse> {
  return getJSON<DQSummaryResponse>('/dq/summary');
}

export function getDQFailures(): Promise<DQFailuresResponse> {
  // Schema filtering is client-side. Earlier server-side filter caused
  // chip counts to zero out once the user selected a schema, since the
  // response only contained matching rows. Always returning the full list
  // lets the UI compute accurate counts per chip.
  return getJSON<DQFailuresResponse>('/dq/failures');
}

export function getDQRecommendations(severity?: Severity): Promise<DQRecommendationsResponse> {
  const qs = severity ? `?severity=${encodeURIComponent(severity)}` : '';
  return getJSON<DQRecommendationsResponse>(`/dq/recommendations${qs}`);
}

export function getDQRisk(limit = 20): Promise<DQRiskResponse> {
  return getJSON<DQRiskResponse>(`/dq/risk?limit=${limit}`);
}

export function getDQImpact(fqn: string): Promise<DQImpactResponse> {
  return getJSON<DQImpactResponse>(`/dq/impact/${encodeURIComponent(fqn)}`);
}

// ── /report ────────────────────────────────────────────────────────────────
//
// Full executive report — single GET, cheap enough to regenerate on every
// /report visit. The UI renders `markdown` with react-markdown + remark-gfm
// and offers it as a .md download.

export interface ReportResponse {
  markdown: string;
  generated_at: string;
}

export function getReport(): Promise<ReportResponse> {
  return getJSON<ReportResponse>('/report');
}

export async function streamScan(
  kind: ScanKind,
  onFrame: (frame: ScanFrame) => void,
  body?: BulkDocBody,
  signal?: AbortSignal,
): Promise<void> {
  const path = `/scans/${SCAN_PATH[kind]}`;
  const r = await fetch(API + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  if (!r.ok) {
    // 409 scan_already_running, 503 om_unreachable, 422 on a malformed body.
    await parseOrThrow<unknown>(r, path);
    return;
  }
  if (!r.body) throw new ApiError('internal_error', `${path}: empty body`);

  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      while (true) {
        const m = /\r\n\r\n|\n\n|\r\r/.exec(buf);
        if (!m) break;
        const block = buf.slice(0, m.index);
        buf = buf.slice(m.index + m[0].length);
        const frame = parseSSEBlockScan(block);
        if (frame) onFrame(frame);
      }
    }
    if (buf.trim()) {
      const frame = parseSSEBlockScan(buf);
      if (frame) onFrame(frame);
    }
  } finally {
    try {
      reader.releaseLock();
    } catch {
      // already released
    }
  }
}
