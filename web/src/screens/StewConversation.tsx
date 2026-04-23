/**
 * Single conversation view at `/chat/:conversationId`.
 *
 * Loads the persisted transcript via TanStack Query. When the user sends,
 * we kick off an SSE stream and accumulate frames into an InFlightState that
 * renders live under the saved messages. On final/error, we invalidate the
 * detail query — the backend already wrote both turns atomically — and clear
 * the in-flight preview once the refetch resolves to avoid a flicker.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { Composer } from '../components/Composer';
import { MessageList, type InFlightState } from '../components/MessageList';
import { ModelQuickPicker } from '../components/ModelQuickPicker';
import { Sidebar } from '../components/Sidebar';
import { ApiError, getConversation, streamChat } from '../lib/api';

export function StewConversation() {
  const { conversationId = '' } = useParams();
  const qc = useQueryClient();
  const detail = useQuery({
    queryKey: ['conversation', conversationId],
    queryFn: () => getConversation(conversationId),
    enabled: conversationId.length > 0,
  });

  const [inFlight, setInFlight] = useState<InFlightState | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Keep the view glued to the bottom as new content streams or renders.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [detail.data?.messages.length, inFlight]);

  const send = useMutation({
    mutationFn: async (question: string) => {
      const initial: InFlightState = {
        question,
        calls: {},
        results: {},
        tokens: [],
        finalText: '',
        error: null,
        done: false,
      };
      setInFlight(initial);
      await streamChat({ question, conversation_id: conversationId }, (frame) => {
        setInFlight((prev) => {
          if (!prev) return prev;
          const next: InFlightState = {
            ...prev,
            calls: { ...prev.calls },
            results: { ...prev.results },
            tokens: prev.tokens,
          };
          switch (frame.type) {
            case 'tool_call':
              next.calls[frame.id] = { name: frame.name, args: frame.args };
              break;
            case 'tool_result':
              next.results[frame.id] = frame.content;
              break;
            case 'token':
              next.tokens = [...prev.tokens, frame.text];
              break;
            case 'final':
              next.finalText = frame.text;
              next.done = true;
              break;
            case 'error':
              next.error = frame.message;
              next.done = true;
              break;
          }
          return next;
        });
      });
    },
    onSettled: async () => {
      // Server persisted on `final`; refetch the detail (and list, for the
      // updated_at ordering) before clearing the preview so the UI doesn't
      // blink through an empty state.
      await qc.invalidateQueries({ queryKey: ['conversation', conversationId] });
      await qc.invalidateQueries({ queryKey: ['conversations'] });
      setInFlight(null);
    },
  });

  const onSend = useCallback((text: string) => send.mutate(text), [send]);

  return (
    <div className="min-h-screen bg-ink-bg text-ink-text relative flex">
      <Sidebar activeKey="stew" />
      <main className="flex-1 flex flex-col h-screen">
        <header className="px-10 pt-8 pb-4 border-b border-ink-border flex items-center justify-between">
          <div>
            <Link
              to="/chat"
              className="text-xs uppercase tracking-widest text-ink-dim hover:text-accent-soft font-semibold"
            >
              ← Stew
            </Link>
            <h1 className="text-xl font-bold tracking-tight mt-1">
              {detail.data?.conversation.title || 'Untitled conversation'}
            </h1>
          </div>
          <div className="text-mini font-mono text-ink-dim">
            {detail.data ? `${detail.data.messages.length} messages` : ''}
          </div>
        </header>

        <div ref={scrollRef} className="flex-1 overflow-y-auto px-10 py-8">
          {detail.isLoading ? (
            <EmptyPlaceholder>Loading conversation…</EmptyPlaceholder>
          ) : detail.error instanceof ApiError && detail.error.code === 'conversation_not_found' ? (
            <EmptyPlaceholder>
              That conversation doesn't exist. <Link to="/chat" className="underline">Back to Stew</Link>.
            </EmptyPlaceholder>
          ) : detail.error ? (
            <EmptyPlaceholder>
              Couldn't load this conversation: {(detail.error as Error).message}
            </EmptyPlaceholder>
          ) : detail.data && detail.data.messages.length === 0 && !inFlight ? (
            <EmptyPlaceholder>
              Fresh conversation. Ask Stew anything about your catalog.
            </EmptyPlaceholder>
          ) : (
            <MessageList messages={detail.data?.messages ?? []} inFlight={inFlight} />
          )}
        </div>

        <footer className="border-t border-ink-border px-10 py-4 bg-ink-panel/30">
          <Composer onSend={onSend} disabled={send.isPending} />
          <ModelQuickPicker />
          {send.error instanceof ApiError ? (
            <div className="mt-2 text-xs font-mono text-error-soft">
              {send.error.code}: {send.error.message}
            </div>
          ) : null}
        </footer>
      </main>
    </div>
  );
}

function EmptyPlaceholder({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-center h-full text-ink-dim text-sm">
      {children}
    </div>
  );
}
