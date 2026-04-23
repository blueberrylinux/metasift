/**
 * `/chat` landing — conversation list and New-chat CTA.
 *
 * Create flow: POST /chat/conversations → navigate to /chat/:newId. The
 * new route renders StewConversation with an empty message list until
 * the first send.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';

import { AppLayout } from '../components/AppLayout';
import { PageHeader } from '../components/PageHeader';
import { createConversation, listConversations } from '../lib/api';

export function Stew() {
  const nav = useNavigate();
  const qc = useQueryClient();

  const convos = useQuery({
    queryKey: ['conversations'],
    queryFn: () => listConversations(),
  });

  const create = useMutation({
    mutationFn: (title: string | undefined) => createConversation(title),
    onSuccess: async (row) => {
      await qc.invalidateQueries({ queryKey: ['conversations'] });
      nav(`/chat/${row.id}`);
    },
  });

  const newChatButton = (
    <button
      onClick={() => create.mutate(undefined)}
      disabled={create.isPending}
      className={
        'text-[11px] px-2.5 py-1 rounded-md border transition ' +
        (create.isPending
          ? 'text-emerald-300/50 border-emerald-500/20 bg-emerald-500/5 cursor-wait'
          : 'text-emerald-300 border-emerald-500/20 bg-emerald-500/5 hover:bg-emerald-500/10')
      }
    >
      {create.isPending ? 'Creating…' : '+ New chat'}
    </button>
  );

  return (
    <AppLayout activeKey="chat">
      <PageHeader
        title="Stew"
        subtitle="The metadata wizard who lives in your catalog. Ask about coverage, tag conflicts, blast radius, DQ failures — anything."
        rightButtons={newChatButton}
      />

      <div className="flex-1 px-6 py-6 max-w-4xl">
        {convos.isLoading ? (
          <Placeholder>Loading conversations…</Placeholder>
        ) : convos.error ? (
          <Placeholder>
            Couldn't load conversations: {(convos.error as Error).message}
          </Placeholder>
        ) : !convos.data || convos.data.rows.length === 0 ? (
          <Placeholder>
            No conversations yet — click{' '}
            <span className="text-emerald-300">+ New chat</span> to start one.
          </Placeholder>
        ) : (
          <ul className="flex flex-col gap-2">
            {convos.data.rows.map((c) => (
              <li key={c.id}>
                <Link
                  to={`/chat/${c.id}`}
                  className="block rounded-lg border border-slate-800 bg-slate-900/40 hover:bg-slate-900 hover:border-emerald-500/30 px-4 py-3 transition-colors"
                >
                  <div className="flex items-baseline justify-between gap-4">
                    <div className="text-[13px] font-semibold text-slate-200 truncate">
                      {c.title || 'Untitled conversation'}
                    </div>
                    <div className="text-[10px] font-mono text-slate-500 shrink-0">
                      {formatTimestamp(c.updated_at)}
                    </div>
                  </div>
                  <div className="text-[11px] font-mono text-slate-500 truncate mt-0.5">
                    {c.id}
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </AppLayout>
  );
}

function Placeholder({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40 px-6 py-8 text-sm text-slate-400">
      {children}
    </div>
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
