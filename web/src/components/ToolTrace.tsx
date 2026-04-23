/**
 * Collapsible "Show your work" panel under an assistant turn. Mirrors the
 * expander in the Streamlit UI (`app/main.py::_render_assistant`) — one row
 * per tool call with its args and the result payload.
 */

import type { ToolTraceEntry } from '../lib/api';

export function ToolTrace({ traces, streaming }: { traces: ToolTraceEntry[]; streaming?: boolean }) {
  if (!traces.length) return null;

  const count = traces.length;
  const label = streaming
    ? `Running tools (${count})…`
    : `Show your work (${count} tool call${count === 1 ? '' : 's'})`;

  return (
    <details className="mt-2 rounded-md border border-ink-border/60 bg-ink-panel/30" open={streaming}>
      <summary className="cursor-pointer select-none px-3 py-1.5 text-xs font-mono text-ink-dim hover:text-ink-soft">
        {label}
      </summary>
      <div className="divide-y divide-ink-border/40">
        {traces.map((t, i) => (
          <div key={i} className="px-3 py-2 space-y-1">
            <div className="font-mono text-xs text-accent-soft break-all">
              {t.tool}({formatArgs(t.args)})
            </div>
            <pre className="whitespace-pre-wrap text-xs text-ink-soft font-mono leading-relaxed max-h-48 overflow-auto">
              {formatResult(t.result)}
            </pre>
          </div>
        ))}
      </div>
    </details>
  );
}

function formatArgs(args: unknown): string {
  if (args == null) return '';
  if (typeof args === 'object') return JSON.stringify(args);
  return String(args);
}

function formatResult(result: unknown): string {
  if (result == null) return '';
  if (typeof result === 'string') return result;
  return JSON.stringify(result, null, 2);
}
