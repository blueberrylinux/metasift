/**
 * `/chat` landing — shows the conversation list and the New-chat CTA.
 *
 * Create flow: POST /chat/conversations → navigate to /chat/:newId. The new
 * route renders StewConversation with an empty message list until the first
 * send.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';

import { Sidebar } from '../components/Sidebar';
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

  return (
    <div className="min-h-screen bg-ink-bg text-ink-text relative flex">
      <Sidebar activeKey="stew" />
      <main className="flex-1 px-10 pt-10 pb-20 max-w-4xl">
        <header className="flex items-center justify-between mb-10">
          <div>
            <div className="text-xs uppercase tracking-widest text-accent-bright font-semibold">
              MetaSift · Phase 2
            </div>
            <h1 className="text-2xl font-bold tracking-tight">Stew</h1>
            <p className="text-ink-soft text-sm mt-1">
              The metadata wizard who lives in your catalog. Ask about coverage, tag
              conflicts, blast radius, DQ failures — anything.
            </p>
          </div>
          <button
            onClick={() => create.mutate(undefined)}
            disabled={create.isPending}
            className={
              'px-4 py-2 rounded-md text-sm font-mono transition-colors border ' +
              (create.isPending
                ? 'bg-accent/20 text-accent-soft border-accent/30 cursor-wait'
                : 'bg-accent/30 hover:bg-accent/40 text-accent-bright border-accent/40')
            }
          >
            {create.isPending ? 'Creating…' : '+ New chat'}
          </button>
        </header>

        {convos.isLoading ? (
          <Placeholder>Loading conversations…</Placeholder>
        ) : convos.error ? (
          <Placeholder>Couldn't load conversations: {(convos.error as Error).message}</Placeholder>
        ) : !convos.data || convos.data.rows.length === 0 ? (
          <Placeholder>
            No conversations yet — click <span className="text-accent-soft">+ New chat</span> to
            start one.
          </Placeholder>
        ) : (
          <ul className="flex flex-col gap-2">
            {convos.data.rows.map((c) => (
              <li key={c.id}>
                <Link
                  to={`/chat/${c.id}`}
                  className="block rounded-md border border-ink-border bg-ink-panel/40 hover:bg-ink-panel/70 hover:border-accent/30 px-4 py-3 transition-colors"
                >
                  <div className="flex items-baseline justify-between gap-4">
                    <div className="text-sm font-semibold text-ink-text truncate">
                      {c.title || 'Untitled conversation'}
                    </div>
                    <div className="text-mini font-mono text-ink-dim shrink-0">
                      {formatTimestamp(c.updated_at)}
                    </div>
                  </div>
                  <div className="text-xs font-mono text-ink-dim truncate mt-0.5">{c.id}</div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </main>
    </div>
  );
}

function Placeholder({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-ink-border bg-ink-panel/40 px-6 py-8 text-sm text-ink-soft">
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
