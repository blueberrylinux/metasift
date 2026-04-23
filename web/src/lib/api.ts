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
