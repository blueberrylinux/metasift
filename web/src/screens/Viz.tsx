/**
 * Visualizations screen — 11 tabs, one per entry in the viz engine's
 * ALL_VIZ. Ports the Streamlit `st.tabs` layout. Each tab's figure is
 * fetched lazily on click via PlotTab so the /viz route never blocks on
 * 11 concurrent DuckDB queries.
 *
 * Plotly itself is lazy-loaded in PlotTab — the chunk only downloads once
 * the first tab mounts, not on /viz navigation alone.
 */

import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { PlotTab } from '../components/PlotTab';
import { Sidebar } from '../components/Sidebar';
import { ApiError, listVizTabs } from '../lib/api';

export function Viz() {
  const tabs = useQuery({
    queryKey: ['viz-tabs'],
    queryFn: listVizTabs,
    staleTime: Infinity,  // tab list is static — only changes with engine updates
  });
  const [activeSlug, setActiveSlug] = useState<string | null>(null);

  // Pick the first tab as the default once the list resolves. We don't put
  // this in useState's initializer because the list isn't known yet.
  const rows = tabs.data?.tabs ?? [];
  const active = activeSlug ?? rows[0]?.slug ?? null;
  const activeTab = rows.find((t) => t.slug === active) ?? null;

  return (
    <div className="min-h-screen bg-ink-bg text-ink-text relative flex">
      <Sidebar activeKey="viz" />
      <main className="flex-1 px-10 pt-10 pb-20 max-w-6xl">
        <header className="flex items-center justify-between mb-6">
          <div>
            <div className="text-xs uppercase tracking-widest text-accent-bright font-semibold">
              MetaSift · Phase 3
            </div>
            <h1 className="text-2xl font-bold tracking-tight">Visualizations</h1>
            <p className="text-ink-soft text-sm mt-1 max-w-2xl">
              Interactive views across your catalog. Charts update after each Refresh / Deep scan /
              PII scan — some tabs need specific scans run first.
            </p>
          </div>
          <Link to="/chat" className="text-xs uppercase tracking-widest text-ink-dim hover:text-accent-soft">
            Stew →
          </Link>
        </header>

        {tabs.isLoading ? (
          <Placeholder>Loading tabs…</Placeholder>
        ) : tabs.error instanceof ApiError ? (
          <Placeholder error>
            {tabs.error.code}: {tabs.error.message}
          </Placeholder>
        ) : tabs.error ? (
          <Placeholder error>Couldn't load tabs: {(tabs.error as Error).message}</Placeholder>
        ) : (
          <>
            <div
              className="flex flex-wrap gap-1 mb-6 border-b border-ink-border pb-3"
              role="tablist"
            >
              {rows.map((t) => {
                const isActive = t.slug === active;
                return (
                  <button
                    key={t.slug}
                    onClick={() => setActiveSlug(t.slug)}
                    role="tab"
                    aria-selected={isActive}
                    className={
                      'px-3 py-1.5 rounded-md text-xs font-mono border transition-colors whitespace-nowrap ' +
                      (isActive
                        ? 'bg-accent/30 text-accent-bright border-accent/40'
                        : 'bg-ink-panel/40 text-ink-soft border-ink-border hover:text-ink-text hover:border-ink-border')
                    }
                  >
                    {t.label}
                  </button>
                );
              })}
            </div>

            {activeTab ? (
              <div key={activeTab.slug} role="tabpanel">
                <PlotTab slug={activeTab.slug} caption={activeTab.caption} />
              </div>
            ) : (
              <Placeholder>No viz tabs registered.</Placeholder>
            )}
          </>
        )}
      </main>
    </div>
  );
}

function Placeholder({ children, error }: { children: React.ReactNode; error?: boolean }) {
  return (
    <div
      className={
        'rounded-xl border px-6 py-8 text-sm ' +
        (error
          ? 'border-error/30 bg-error/5 text-error-soft font-mono'
          : 'border-ink-border bg-ink-panel/40 text-ink-soft')
      }
    >
      {children}
    </div>
  );
}
