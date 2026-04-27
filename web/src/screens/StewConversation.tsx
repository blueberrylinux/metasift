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
import { toast } from 'sonner';

import { AppLayout } from '../components/AppLayout';
import { useByoKeyTrap } from '../components/ByoKeyModal';
import { Composer } from '../components/Composer';
import { EditableTitle } from '../components/EditableTitle';
import { EmptyState } from '../components/EmptyState';
import { MessageList, type InFlightState } from '../components/MessageList';
import { PageHeader } from '../components/PageHeader';
import { Skeleton } from '../components/Skeleton';
import {
  ApiError,
  type ConversationDetail,
  getConversation,
  renameConversation,
  streamChat,
} from '../lib/api';

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
  const contentRef = useRef<HTMLDivElement>(null);
  const autoSentRef = useRef(false);
  // Sandbox public-demo: traps a 402 byo_key_required from streamChat and
  // opens the BYO-key modal. No-op for non-sandbox users (the API never
  // returns 402 in that mode).
  const byoKey = useByoKeyTrap();
  // `stickRef` holds the authoritative "should I follow new content?" flag —
  // a ref so the ResizeObserver callback always reads the latest value
  // without re-subscribing. `atBottom` mirrors it for the pill's render.
  const stickRef = useRef(true);
  const [atBottom, setAtBottom] = useState(true);

  // Streamlit-style auto-scroll: whenever the rendered content grows, if the
  // user was at the bottom before the growth, keep them there. If they'd
  // scrolled up to re-read something, leave them alone and let the pill
  // tell them there's more below. The observer has to watch the INNER
  // content node, not the scroller — the scroller's own bounding box
  // doesn't change when `scrollHeight` grows, so a ResizeObserver on the
  // scroller silently ignores streamed messages.
  useEffect(() => {
    const scroller = scrollRef.current;
    const content = contentRef.current;
    if (!scroller || !content) return;
    const BOTTOM_THRESHOLD_PX = 80;

    const measureStick = () => {
      const distance = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
      const near = distance < BOTTOM_THRESHOLD_PX;
      stickRef.current = near;
      setAtBottom(near);
    };

    const pinIfSticky = () => {
      if (stickRef.current) scroller.scrollTop = scroller.scrollHeight;
    };

    measureStick();
    scroller.addEventListener('scroll', measureStick, { passive: true });
    const ro = new ResizeObserver(() => {
      pinIfSticky();
      // A follow-up rAF covers async layout that finalizes on the next
      // frame (markdown fonts, tool-trace expanders). After re-pinning we
      // re-measure so `atBottom` reflects reality.
      requestAnimationFrame(() => {
        pinIfSticky();
        measureStick();
      });
    });
    ro.observe(content);

    return () => {
      scroller.removeEventListener('scroll', measureStick);
      ro.disconnect();
    };
  }, []);

  // Initial snap so navigating into an existing conversation lands on the
  // newest turn instead of the oldest.
  useEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller || !detail.data) return;
    scroller.scrollTop = scroller.scrollHeight;
    stickRef.current = true;
    setAtBottom(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId, detail.data?.messages.length === 0 ? 'empty' : 'loaded']);

  const scrollToBottom = useCallback((smooth = true) => {
    const scroller = scrollRef.current;
    if (!scroller) return;
    scroller.scrollTo({
      top: scroller.scrollHeight,
      behavior: smooth ? 'smooth' : 'auto',
    });
    stickRef.current = true;
    setAtBottom(true);
  }, []);

  // User clicked send → force-stick + scroll. This is an explicit "show me
  // what's happening" intent, so override any prior manual scroll-up.
  useEffect(() => {
    if (inFlight?.question) scrollToBottom(true);
  }, [inFlight?.question, scrollToBottom]);

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
        // Sandbox: a 402 byo_key_required opens the BYO-key modal. Swallow
        // the error and clear the in-flight bubble so the user can retry
        // their question after pasting a key. Non-sandbox: trap returns
        // false and the original throw path runs.
        if (byoKey.trap(e)) {
          setInFlight(null);
          return;
        }
        throw e;
      }
    },
    onSettled: async (_data, _error, _vars, _ctx) => {
      // Server persisted on `final`; refetch the detail (and list, for the
      // updated_at ordering) before clearing the preview so the UI doesn't
      // blink through an empty state.
      await qc.invalidateQueries({ queryKey: ['conversation', conversationId] });
      await qc.invalidateQueries({ queryKey: ['conversations'] });
      // Preserve the in-flight bubble when the SSE stream ended in an `error`
      // frame — `streamChat` resolves normally for in-band errors so
      // `send.error` stays null, and clearing inFlight here would erase the
      // user's only signal that the turn failed. Keep it visible until the
      // user sends another message or navigates away.
      setInFlight((cur) => (cur && cur.error ? cur : null));
    },
  });

  const onSend = useCallback((text: string) => send.mutate(text), [send]);

  // One-shot auto-submit when arriving with an initial question handed over
  // from StewHome or the WelcomeModal's suggestion chips. The `autoSentRef`
  // is the authoritative guard — StrictMode's dev double-invoke, a refresh
  // that preserves history state, or back-nav would otherwise re-submit.
  useEffect(() => {
    const initial = (location.state as LocationState | null)?.initial_question;
    if (!initial || autoSentRef.current) return;
    if (!detail.data || detail.data.messages.length > 0) return;
    autoSentRef.current = true;
    send.mutate(initial);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail.data, location.state]);

  const persistedTitle = detail.data?.conversation.title ?? null;
  const displayTitle = persistedTitle || 'Untitled conversation';
  const messageCount = detail.data ? `${detail.data.messages.length} messages` : '';

  const rename = useMutation({
    mutationFn: (next: string) => renameConversation(conversationId, next),
    onMutate: async (next) => {
      await qc.cancelQueries({ queryKey: ['conversation', conversationId] });
      const prev = qc.getQueryData<ConversationDetail>(['conversation', conversationId]);
      if (prev) {
        qc.setQueryData<ConversationDetail>(['conversation', conversationId], {
          ...prev,
          conversation: { ...prev.conversation, title: next || null },
        });
      }
      return { prev };
    },
    onError: (e, _vars, ctx) => {
      if (ctx?.prev) {
        qc.setQueryData(['conversation', conversationId], ctx.prev);
      }
      toast.error('Rename failed', {
        description: e instanceof Error ? e.message : String(e),
      });
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['conversations'] });
      // Also refetch this conversation's detail so the persisted title
      // reflects what the server actually stored (e.g. after the validator
      // trims whitespace). Without this the detail cache can stay on the
      // optimistic value if server normalization changed it.
      qc.invalidateQueries({ queryKey: ['conversation', conversationId] });
    },
  });

  return (
    <AppLayout activeKey="chat">
      <div className="flex-1 flex flex-col h-[calc(100vh-3.5rem)]">
        <PageHeader
          title={
            <EditableTitle
              key={conversationId}
              current={persistedTitle}
              display={
                <span className={persistedTitle ? 'text-white' : 'text-slate-400 italic'}>
                  {displayTitle}
                </span>
              }
              onSave={(next) => {
                const trimmed = next.trim();
                const previous = persistedTitle ?? '';
                if (trimmed === previous) return;
                rename.mutate(trimmed);
              }}
              saving={rename.isPending}
              placeholder="Untitled conversation"
              inputClass="bg-transparent outline-none border-b border-slate-600 focus:border-emerald-400 text-xl font-bold text-white tracking-tight w-full max-w-[28ch] placeholder:text-slate-600 disabled:opacity-60"
              displayClass="text-xl font-bold tracking-tight text-white hover:text-emerald-200 transition"
            />
          }
          backLink={{ to: '/chat', label: 'Stew' }}
          rightButtons={
            <span className="text-[10px] font-mono text-slate-500">{messageCount}</span>
          }
        />

        <div className="relative flex-1 min-h-0">
          <div ref={scrollRef} className="absolute inset-0 overflow-y-auto scrollbar-thin px-6 py-6">
          <div ref={contentRef}>
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
          </div>
          {!atBottom && (
            <button
              type="button"
              onClick={() => scrollToBottom(true)}
              title="Scroll to latest"
              aria-label="Scroll to latest message"
              className="absolute bottom-4 left-1/2 -translate-x-1/2 z-10 w-9 h-9 rounded-full bg-slate-900/90 border border-slate-700 hover:border-emerald-500/40 hover:bg-slate-800 text-slate-300 hover:text-emerald-300 shadow-lg backdrop-blur flex items-center justify-center transition"
            >
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <line x1="12" y1="5" x2="12" y2="19" />
                <polyline points="19 12 12 19 5 12" />
              </svg>
            </button>
          )}
        </div>

        <Composer
          onSend={onSend}
          disabled={send.isPending}
          onStop={() => abortRef.current?.abort()}
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
