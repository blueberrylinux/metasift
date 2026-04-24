/**
 * `/chat` landing. Renders `<StewHome>` hero + suggestion grid; below it,
 * a "Recent conversations" list if any are persisted. Clicking a
 * suggestion (or visiting `/chat?q=...` from the WelcomeModal) creates
 * a conversation and navigates straight to it — StewConversation picks
 * up an initial question from the location state and auto-submits it.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';

import { toast } from 'sonner';

import { AppLayout } from '../components/AppLayout';
import { Composer } from '../components/Composer';
import { StewHome } from '../components/StewHome';
import {
  type ConversationSummary,
  createConversation,
  deleteConversation,
  listConversations,
  renameConversation,
} from '../lib/api';

export function Stew() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();

  const convos = useQuery({
    queryKey: ['conversations'],
    queryFn: () => listConversations(),
  });

  const create = useMutation({
    mutationFn: async (question?: string) => {
      const row = await createConversation();
      return { row, question };
    },
    onSuccess: async ({ row, question }) => {
      await qc.invalidateQueries({ queryKey: ['conversations'] });
      nav(`/chat/${row.id}`, {
        // StewConversation auto-submits initial_question on mount.
        state: question ? { initial_question: question } : undefined,
      });
    },
  });

  // Pre-filled question from the WelcomeModal or any external link
  // (`/chat?q=what's+my+composite+score`). Consume once via a ref guard —
  // `create.isPending` isn't reliable under StrictMode double-invoke or
  // back-nav that returns `?q=` before isPending flips true.
  const consumedQRef = useRef(false);
  useEffect(() => {
    const q = searchParams.get('q');
    if (!q || consumedQRef.current) return;
    consumedQRef.current = true;
    setSearchParams({}, { replace: true });
    create.mutate(q);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const del = useMutation({
    mutationFn: (id: string) => deleteConversation(id),
    // Optimistic remove so the row vanishes immediately — fetching the list
    // again after invalidate would leave a perceptible delay otherwise.
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: ['conversations'] });
      const prev = qc.getQueryData<{ rows: ConversationSummary[] }>(['conversations']);
      if (prev) {
        qc.setQueryData(['conversations'], {
          ...prev,
          rows: prev.rows.filter((r) => r.id !== id),
        });
      }
      return { prev };
    },
    onError: (e, _id, ctx) => {
      if (ctx?.prev) qc.setQueryData(['conversations'], ctx.prev);
      toast.error('Failed to delete conversation', {
        description: e instanceof Error ? e.message : String(e),
      });
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ['conversations'] }),
  });

  const rename = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      renameConversation(id, title),
    onMutate: async ({ id, title }) => {
      await qc.cancelQueries({ queryKey: ['conversations'] });
      const prev = qc.getQueryData<{ rows: ConversationSummary[] }>(['conversations']);
      if (prev) {
        qc.setQueryData(['conversations'], {
          ...prev,
          rows: prev.rows.map((r) =>
            r.id === id ? { ...r, title: title || null } : r,
          ),
        });
      }
      // Also patch the detail cache if the conversation is already loaded so
      // navigating into it shows the new title instantly.
      const detailKey = ['conversation', id];
      const prevDetail = qc.getQueryData<{ conversation: ConversationSummary }>(detailKey);
      if (prevDetail) {
        qc.setQueryData(detailKey, {
          ...prevDetail,
          conversation: { ...prevDetail.conversation, title: title || null },
        });
      }
      return { prev, prevDetail };
    },
    onError: (e, { id }, ctx) => {
      if (ctx?.prev) qc.setQueryData(['conversations'], ctx.prev);
      if (ctx?.prevDetail) qc.setQueryData(['conversation', id], ctx.prevDetail);
      toast.error('Rename failed', {
        description: e instanceof Error ? e.message : String(e),
      });
    },
    onSettled: (_r, _e, { id }) => {
      qc.invalidateQueries({ queryKey: ['conversations'] });
      qc.invalidateQueries({ queryKey: ['conversation', id] });
    },
  });

  const recents = convos.data?.rows ?? [];

  return (
    <AppLayout activeKey="chat">
      {/* Lock the chat landing to exactly one viewport so the hero, the
          Recent conversations strip, and the Composer always coexist without
          the page scrolling — internal scrolling is restricted to the
          recents list when it gets long. */}
      <div className="flex-1 flex flex-col min-h-0 h-[calc(100vh-3.5rem)]">
        <StewHome
          onSelect={(q) => create.mutate(q)}
          pending={create.isPending}
          footer={
            recents.length > 0 ? (
              <RecentConversations
                rows={recents}
                onDelete={(id) => del.mutate(id)}
                onRename={(id, title) => rename.mutate({ id, title })}
                deletingId={del.isPending ? del.variables : null}
                renamingId={rename.isPending ? rename.variables?.id ?? null : null}
              />
            ) : null
          }
        />
        <Composer onSend={(q) => create.mutate(q)} disabled={create.isPending} />
      </div>
    </AppLayout>
  );
}

function RecentConversations({
  rows,
  onDelete,
  onRename,
  deletingId,
  renamingId,
}: {
  rows: ConversationSummary[];
  onDelete: (id: string) => void;
  onRename: (id: string, title: string) => void;
  deletingId: string | null;
  renamingId: string | null;
}) {
  // Show up to ~4 rows inline (fits cleanly in the sliver between suggestions
  // and the composer). Beyond that the list becomes internally scrollable so
  // the rest of the layout stays pinned.
  const scrolls = rows.length > 4;
  return (
    <div className="border-t border-slate-800/80 bg-slate-950/40 px-6 py-3">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-baseline justify-between mb-2">
          <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">
            Recent conversations
          </div>
          <div className="text-[10px] font-mono text-slate-600">{rows.length}</div>
        </div>
        <ul
          className={
            'flex flex-col gap-1 ' +
            (scrolls ? 'max-h-[168px] overflow-y-auto scrollbar-thin pr-1' : '')
          }
        >
          {rows.map((c) => (
            <RecentRow
              key={c.id}
              convo={c}
              onDelete={onDelete}
              onRename={onRename}
              deleting={deletingId === c.id}
              renaming={renamingId === c.id}
            />
          ))}
        </ul>
      </div>
    </div>
  );
}

function RecentRow({
  convo,
  onDelete,
  onRename,
  deleting,
  renaming,
}: {
  convo: ConversationSummary;
  onDelete: (id: string) => void;
  onRename: (id: string, title: string) => void;
  deleting: boolean;
  renaming: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(convo.title ?? '');
  // Escape-then-blur race: onBlur=commit runs after Escape and would
  // otherwise save the pre-cancel draft via the captured closure. This
  // flag tells commit to skip exactly once.
  const canceledRef = useRef(false);

  // Resync draft when the canonical title changes from outside (optimistic
  // update lands, another tab renames, etc.) and we're not actively editing.
  useEffect(() => {
    if (!editing) setDraft(convo.title ?? '');
  }, [convo.title, editing]);

  const commit = () => {
    if (canceledRef.current) {
      canceledRef.current = false;
      return;
    }
    setEditing(false);
    const trimmed = draft.trim();
    const previous = convo.title ?? '';
    if (trimmed !== previous) onRename(convo.id, trimmed);
  };

  const cancel = () => {
    canceledRef.current = true;
    setEditing(false);
    setDraft(convo.title ?? '');
  };

  return (
    <li className="group relative">
      {editing ? (
        <div className="flex items-baseline justify-between gap-3 rounded-md px-3 py-2 bg-slate-900/60">
          <input
            value={draft}
            autoFocus
            disabled={renaming}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                commit();
              } else if (e.key === 'Escape') {
                e.preventDefault();
                cancel();
              }
            }}
            onBlur={commit}
            placeholder="Untitled conversation"
            className="flex-1 bg-transparent outline-none text-[13px] text-slate-100 placeholder:text-slate-600 border-b border-slate-700 focus:border-emerald-400 disabled:opacity-60"
          />
          <span className="text-[10px] font-mono text-slate-500 shrink-0">
            enter to save · esc to cancel
          </span>
        </div>
      ) : (
        <Link
          to={`/chat/${convo.id}`}
          className="flex items-baseline justify-between gap-3 rounded-md px-3 py-2 hover:bg-slate-900/60 transition"
        >
          <span className="text-[13px] text-slate-200 truncate">
            {convo.title || 'Untitled conversation'}
          </span>
          <span className="text-[10px] font-mono text-slate-500 shrink-0 pr-14">
            {formatTimestamp(convo.updated_at)}
          </span>
        </Link>
      )}
      {/* Rename + delete action buttons stacked to the row's right edge. Kept
          outside the Link (nested interactives are an a11y foot-gun) and
          revealed on hover so the list stays visually quiet by default. */}
      {!editing && (
        <div className="absolute top-1/2 -translate-y-1/2 right-2 flex items-center gap-1 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition">
          <button
            type="button"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              setEditing(true);
            }}
            aria-label={`Rename ${convo.title || 'conversation'}`}
            title="Rename"
            className="w-5 h-5 rounded text-slate-500 hover:text-emerald-300 hover:bg-slate-800 flex items-center justify-center transition"
          >
            <svg
              width="11"
              height="11"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M12 20h9" />
              <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />
            </svg>
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              if (!deleting) onDelete(convo.id);
            }}
            disabled={deleting}
            aria-label={`Delete ${convo.title || 'conversation'}`}
            title="Delete"
            className="w-5 h-5 rounded text-slate-500 hover:text-red-300 hover:bg-slate-800 flex items-center justify-center transition disabled:opacity-40 disabled:cursor-wait"
          >
            <svg
              width="10"
              height="10"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
            >
              <line x1="6" y1="6" x2="18" y2="18" />
              <line x1="18" y1="6" x2="6" y2="18" />
            </svg>
          </button>
        </div>
      )}
    </li>
  );
}

function formatTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString();
  } catch {
    return iso;
  }
}
