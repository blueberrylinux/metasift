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

export function getComposite(): Promise<CompositeScore> {
  return getJSON<CompositeScore>('/analysis/composite');
}

export function getCoverage(schema?: string): Promise<CoverageResponse> {
  const qs = schema ? `?schema=${encodeURIComponent(schema)}` : '';
  return getJSON<CoverageResponse>(`/analysis/coverage${qs}`);
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
