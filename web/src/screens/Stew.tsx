/**
 * `/chat` landing. Renders `<StewHome>` hero + suggestion grid; below it,
 * a "Recent conversations" list if any are persisted. Clicking a
 * suggestion (or visiting `/chat?q=...` from the WelcomeModal) creates
 * a conversation and navigates straight to it — StewConversation picks
 * up an initial question from the location state and auto-submits it.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';

import { AppLayout } from '../components/AppLayout';
import { StewHome } from '../components/StewHome';
import { createConversation, listConversations } from '../lib/api';

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

  return (
    <AppLayout activeKey="chat">
      <StewHome
        onSelect={(q) => create.mutate(q)}
        pending={create.isPending}
        footer={
          convos.data && convos.data.rows.length > 0 ? (
            <div className="border-t border-slate-800/80 bg-slate-950/40 px-6 py-4">
              <div className="max-w-3xl mx-auto">
                <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-2">
                  Recent conversations
                </div>
                <ul className="flex flex-col gap-1">
                  {convos.data.rows.slice(0, 6).map((c) => (
                    <li key={c.id}>
                      <Link
                        to={`/chat/${c.id}`}
                        className="flex items-baseline justify-between gap-3 rounded-md px-3 py-2 hover:bg-slate-900/60 transition"
                      >
                        <span className="text-[13px] text-slate-200 truncate">
                          {c.title || 'Untitled conversation'}
                        </span>
                        <span className="text-[10px] font-mono text-slate-500 shrink-0">
                          {formatTimestamp(c.updated_at)}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          ) : null
        }
      />
    </AppLayout>
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
