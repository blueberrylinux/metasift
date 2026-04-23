/**
 * Message renderer. Lifted from metasift+/MetaSift App.html::Message
 * (L585-L608) — user bubbles right-aligned with `msg-user` gradient;
 * Stew replies left-aligned with a LogoM avatar, "Stew" label, and
 * `msg-stew` panel. In-flight turns render the user question immediately
 * and a placeholder Stew bubble that swaps to the final text on the
 * `final` frame.
 */

import type { PersistedMessage, ToolTraceEntry } from '../lib/api';
import { LogoM } from './LogoM';
import { ToolTrace } from './ToolTrace';

export interface InFlightState {
  question: string;
  calls: Record<string, { name: string; args: unknown }>;
  results: Record<string, string>;
  tokens: string[];
  finalText: string;
  error: string | null;
  done: boolean;
}

export function inFlightTraces(state: InFlightState): ToolTraceEntry[] {
  return Object.entries(state.calls).map(([id, info]) => ({
    tool: info.name,
    args: info.args,
    result: state.results[id] ?? '',
  }));
}

export function MessageList({
  messages,
  inFlight,
}: {
  messages: PersistedMessage[];
  inFlight: InFlightState | null;
}) {
  return (
    <div className="max-w-3xl mx-auto space-y-6">
      {messages.map((m) => (
        <MessageBubble
          key={m.id}
          role={m.role}
          content={m.content}
          traces={m.tool_trace ?? []}
        />
      ))}
      {inFlight && <InFlightBubble state={inFlight} />}
    </div>
  );
}

function MessageBubble({
  role,
  content,
  traces,
}: {
  role: 'user' | 'assistant';
  content: string;
  traces: ToolTraceEntry[];
}) {
  if (role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="msg-user rounded-2xl rounded-br-md px-4 py-2.5 max-w-xl">
          <div className="text-[14px] text-slate-100 leading-relaxed whitespace-pre-wrap">
            {content}
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="flex gap-3">
      <div className="shrink-0">
        <LogoM size={28} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-[11px] text-emerald-400 font-semibold mb-1">Stew</div>
        <div className="msg-stew rounded-2xl rounded-tl-md px-4 py-3 text-[14px] text-slate-200 leading-relaxed whitespace-pre-wrap">
          {content}
        </div>
        <ToolTrace traces={traces} />
      </div>
    </div>
  );
}

function InFlightBubble({ state }: { state: InFlightState }) {
  const traces = inFlightTraces(state);
  const hasTools = Object.keys(state.calls).length > 0;
  return (
    <>
      <div className="flex justify-end">
        <div className="msg-user rounded-2xl rounded-br-md px-4 py-2.5 max-w-xl">
          <div className="text-[14px] text-slate-100 leading-relaxed whitespace-pre-wrap">
            {state.question}
          </div>
        </div>
      </div>
      <div className="flex gap-3">
        <div className="shrink-0">
          <LogoM size={28} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[11px] text-emerald-400 font-semibold mb-1">
            Stew {!state.done && <span className="text-slate-500">· streaming</span>}
          </div>
          <div className="msg-stew rounded-2xl rounded-tl-md px-4 py-3 text-[14px] text-slate-200 leading-relaxed whitespace-pre-wrap">
            {state.error ? (
              <span className="text-red-300 font-mono text-xs">⚠ {state.error}</span>
            ) : state.finalText ? (
              state.finalText
            ) : (
              <span className="inline-flex items-center gap-1 text-slate-500 italic">
                {hasTools ? 'running tools' : 'thinking'}
                <span className="typing-dot">.</span>
                <span className="typing-dot">.</span>
                <span className="typing-dot">.</span>
              </span>
            )}
          </div>
          <ToolTrace traces={traces} streaming={!state.done} />
        </div>
      </div>
    </>
  );
}
