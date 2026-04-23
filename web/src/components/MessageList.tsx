/**
 * Renders a conversation's saved messages, plus an optional in-flight preview
 * for the turn currently streaming. The in-flight view updates as frames
 * arrive: tool_call / tool_result rows fill the trace, and the assistant
 * bubble shows "…thinking" until the final frame lands.
 */

import type { PersistedMessage, ToolTraceEntry } from '../lib/api';
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
    <div className="flex flex-col gap-5">
      {messages.map((m) => (
        <MessageBubble key={m.id} role={m.role} content={m.content} traces={m.tool_trace ?? []} />
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
        <div className="max-w-[85%] rounded-lg border border-accent/30 bg-accent/10 px-4 py-2 text-sm whitespace-pre-wrap text-ink-text">
          {content}
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-1 max-w-[85%]">
      <div className="text-xs font-mono uppercase tracking-wider text-accent-soft">Stew</div>
      <div className="rounded-lg border border-ink-border bg-ink-panel/60 px-4 py-3 text-sm whitespace-pre-wrap text-ink-text leading-relaxed">
        {content}
      </div>
      <ToolTrace traces={traces} />
    </div>
  );
}

function InFlightBubble({ state }: { state: InFlightState }) {
  const traces = inFlightTraces(state);
  // Users should see their question immediately, not after the assistant replies.
  return (
    <>
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-lg border border-accent/30 bg-accent/10 px-4 py-2 text-sm whitespace-pre-wrap text-ink-text">
          {state.question}
        </div>
      </div>
      <div className="flex flex-col gap-1 max-w-[85%]">
        <div className="text-xs font-mono uppercase tracking-wider text-accent-soft">
          Stew {!state.done && <span className="text-ink-dim">· streaming</span>}
        </div>
        <div className="rounded-lg border border-ink-border bg-ink-panel/60 px-4 py-3 text-sm whitespace-pre-wrap text-ink-text leading-relaxed">
          {state.error ? (
            <span className="text-error-soft font-mono text-xs">⚠ {state.error}</span>
          ) : state.finalText ? (
            state.finalText
          ) : (
            <span className="text-ink-dim italic">
              {Object.keys(state.calls).length > 0 ? 'running tools…' : 'thinking…'}
            </span>
          )}
        </div>
        <ToolTrace traces={traces} streaming={!state.done} />
      </div>
    </>
  );
}
