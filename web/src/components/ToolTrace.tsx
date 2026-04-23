/**
 * "Show your work" expander under an assistant turn. Lifted from
 * metasift+/MetaSift App.html::ToolTrace (L610-L639).
 *
 * Collapsed: chevron + "Show your work" + tool count + "transparent" label
 * (ms total omitted since our SSE frames don't carry per-tool timing).
 * Expanded: per-tool card with name (emerald mono) + args (truncate) +
 * output (slate box, whitespace-pre-wrap).
 */

import { useState } from 'react';

import type { ToolTraceEntry } from '../lib/api';

export function ToolTrace({
  traces,
  streaming,
}: {
  traces: ToolTraceEntry[];
  streaming?: boolean;
}) {
  const [open, setOpen] = useState(!!streaming);
  if (!traces.length) return null;
  return (
    <div className="mt-2 border border-slate-800 rounded-lg bg-slate-900/40 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-3 py-2 text-[11px] text-slate-400 hover:text-slate-200 transition"
      >
        <div className="flex items-center gap-2">
          <svg
            className={'w-3 h-3 transition ' + (open ? 'rotate-90' : '')}
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            viewBox="0 0 24 24"
          >
            <polyline points="9 18 15 12 9 6" />
          </svg>
          <span className="font-semibold">
            {streaming ? 'Running tools' : 'Show your work'}
          </span>
          <span className="font-mono text-slate-600">
            {traces.length} tool{traces.length > 1 ? 's' : ''}
          </span>
        </div>
        <span className="text-[10px] text-slate-600 font-mono">transparent</span>
      </button>
      {open && (
        <div className="px-3 pb-3 space-y-2 border-t border-slate-800 pt-2">
          {traces.map((t, i) => (
            <div key={i} className="rounded border border-slate-800 bg-slate-950/60 p-2">
              <div className="flex items-center justify-between text-[11px] gap-2">
                <div className="font-mono text-emerald-300 truncate">{t.tool}</div>
              </div>
              <div className="font-mono text-[10px] text-slate-500 mt-1 truncate">
                {formatArgs(t.args)}
              </div>
              <pre className="font-mono text-[10px] text-slate-400 mt-1 whitespace-pre-wrap bg-slate-900/80 rounded px-2 py-1.5 border border-slate-800 max-h-48 overflow-auto">
                {formatResult(t.result)}
              </pre>
            </div>
          ))}
        </div>
      )}
    </div>
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
