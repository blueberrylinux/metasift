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
import { Link, useLocation, useParams } from 'react-router-dom';

import { AppLayout } from '../components/AppLayout';
import { Composer } from '../components/Composer';
import { EmptyState } from '../components/EmptyState';
import { MessageList, type InFlightState } from '../components/MessageList';
import { PageHeader } from '../components/PageHeader';
import { Skeleton } from '../components/Skeleton';
import { ApiError, getConversation, streamChat } from '../lib/api';

interface LocationState {
  initial_question?: string;
}

export function StewConversation() {
  const { conversationId = '' } = useParams();
  const location = useLocation();
  const qc = useQueryClient();
  const detail = useQuery({
    queryKey: ['conversation', conversationId],
    queryFn: () => getConversation(conversationId),
    enabled: conversationId.length > 0,
  });

  const [inFlight, setInFlight] = useState<InFlightState | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const autoSentRef = useRef(false);

  // Keep the view glued to the bottom as new content streams or renders.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [detail.data?.messages.length, inFlight]);

  // Abort controller lives across re-renders so we can cancel an in-flight
  // stream on unmount (route change, tab close) or when a new send fires
  // before the previous one finishes. Without this the SSE connection stays
  // open on the server until it naturally ends — stuck chat workers pile up
  // on the backend's dedicated executor.
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const send = useMutation({
    mutationFn: async (question: string) => {
      // Cancel any previous in-flight stream before starting a new one.
      abortRef.current?.abort();
      const ctrl = new AbortController();
      abortRef.current = ctrl;

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
      try {
        await streamChat(
          { question, conversation_id: conversationId },
          (frame) => {
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
          },
          ctrl.signal,
        );
      } catch (e) {
        // AbortError is expected when the user navigates away — swallow it
        // so useMutation doesn't flash an error state for an intentional cancel.
        if (e instanceof DOMException && e.name === 'AbortError') return;
        throw e;
      }
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

  // One-shot auto-submit when arriving with an initial question handed over
  // from StewHome or the WelcomeModal's suggestion chips. The `autoSentRef`
  // is the authoritative guard — StrictMode's dev double-invoke, a refresh
  // that preserves history state, or back-nav would otherwise re-submit.
  // The `replaceState` call at the bottom is cosmetic (React Router reads
  // its own history cache, not the native one) but doesn't hurt.
  useEffect(() => {
    const initial = (location.state as LocationState | null)?.initial_question;
    if (!initial || autoSentRef.current) return;
    if (!detail.data || detail.data.messages.length > 0) return;
    autoSentRef.current = true;
    send.mutate(initial);
    window.history.replaceState({}, '');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail.data, location.state]);

  const title = detail.data?.conversation.title || 'Untitled conversation';
  const messageCount = detail.data ? `${detail.data.messages.length} messages` : '';

  return (
    <AppLayout activeKey="chat">
      <div className="flex-1 flex flex-col h-[calc(100vh-3.5rem)]">
        <PageHeader
          title={title}
          backLink={{ to: '/chat', label: '← Stew' }}
          rightButtons={
            <span className="text-[10px] font-mono text-slate-500">{messageCount}</span>
          }
        />

        <div ref={scrollRef} className="flex-1 overflow-y-auto scrollbar-thin px-6 py-6">
          {detail.isLoading ? (
            <ConversationSkeleton />
          ) : detail.error instanceof ApiError &&
            detail.error.code === 'conversation_not_found' ? (
            <EmptyState
              icon="◈"
              title="Conversation not found"
              body="This conversation was removed, or the URL is wrong."
              actions={
                <Link
                  to="/chat"
                  className="px-3.5 py-2 rounded-md bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-semibold text-[12px] transition"
                >
                  ← Back to Stew
                </Link>
              }
            />
          ) : detail.error ? (
            <EmptyState
              variant="error"
              icon="⚠"
              title="Couldn't load this conversation"
              body={(detail.error as Error).message}
            />
          ) : detail.data && detail.data.messages.length === 0 && !inFlight ? (
            <EmptyState
              icon="✧"
              title="Fresh conversation"
              body="Ask Stew anything about your catalog — coverage, PII tags, DQ failures, lineage impact."
              hint={
                <>
                  Try: <em className="not-italic text-slate-400">"what's our documentation coverage?"</em> or{' '}
                  <em className="not-italic text-slate-400">"auto-document the sales schema"</em>.
                </>
              }
            />
          ) : (
            <MessageList messages={detail.data?.messages ?? []} inFlight={inFlight} />
          )}
        </div>

        <Composer
          onSend={onSend}
          disabled={send.isPending}
          footerExtra={
            send.error instanceof ApiError ? (
              <span className="font-mono text-red-300 truncate">
                {send.error.code}: {send.error.message}
              </span>
            ) : null
          }
        />
      </div>
    </AppLayout>
  );
}

// Alternates user + assistant bubble widths to hint at the conversation
// shape while the history loads.
function ConversationSkeleton() {
  return (
    <div className="space-y-4 max-w-3xl">
      {[0.55, 0.75, 0.45, 0.7].map((w, i) => {
        const mine = i % 2 === 0;
        return (
          <div key={i} className={mine ? 'flex justify-end' : 'flex justify-start'}>
            <Skeleton
              className={(mine ? 'msg-user' : 'msg-stew') + ' h-[54px] rounded-2xl'}
              style={{ width: `${w * 100}%` }}
            />
          </div>
        );
      })}
    </div>
  );
}
