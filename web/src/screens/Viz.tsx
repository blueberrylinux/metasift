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

import { AppLayout } from '../components/AppLayout';
import { PageHeader } from '../components/PageHeader';
import { PlotTab } from '../components/PlotTab';
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
    <AppLayout activeKey="viz">
      <PageHeader
        title="Visualizations"
        subtitle="Interactive views across your catalog. Charts update after each Refresh / Deep scan / PII scan — some tabs need specific scans run first."
        rightButtons={
          <Link
            to="/chat"
            className="text-[11px] px-2.5 py-1 rounded-md text-slate-300 hover:text-white hover:bg-slate-800/60 transition"
          >
            Stew →
          </Link>
        }
      />

      <div className="flex-1 px-6 py-6 max-w-6xl">
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
              className="flex flex-wrap gap-1 mb-6 border-b border-slate-800/80 pb-3"
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
                      'px-3 py-1.5 rounded-md text-[11px] font-mono border transition-colors whitespace-nowrap ' +
                      (isActive
                        ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
                        : 'bg-slate-900/40 text-slate-400 border-slate-800 hover:text-slate-200 hover:border-slate-700')
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
      </div>
    </AppLayout>
  );
}

function Placeholder({ children, error }: { children: React.ReactNode; error?: boolean }) {
  return (
    <div
      className={
        'rounded-xl border px-6 py-8 text-sm ' +
        (error
          ? 'border-red-500/30 bg-red-500/5 text-red-300 font-mono'
          : 'border-slate-800 bg-slate-900/40 text-slate-400')
      }
    >
      {children}
    </div>
  );
}
