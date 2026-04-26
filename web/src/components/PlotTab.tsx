/**
 * Active-tab renderer. Fetches the Plotly JSON for a single slug and hands
 * it to react-plotly.js. The Plot component itself is lazy-loaded through
 * React.lazy so the ~3 MB plotly.js chunk never lands on non-viz routes.
 *
 * Empty state: when the builder returned None (backend emits
 * `{figure: null}`), we render a hint pointing at the scan that populates
 * this tab's data — mirroring the Streamlit `st.info(...)` fallback.
 */

import { useQuery } from '@tanstack/react-query';
import { lazy, Suspense } from 'react';

import { ApiError, getVizFigure } from '../lib/api';
import { DQFailuresVizTable, DQGapsVizTable } from './DQVizTable';

// Deferred import so plotly only ships when the user hits /viz. vite's
// manualChunks config isolates the plotly chunk; lazy loading kicks in the
// first time <Plot> mounts in this process.
//
// Using the `-dist-min` prebuilt bundle + the `factory` entry point of
// react-plotly.js — the full `plotly.js` source tree OOMs vite/rollup at
// build time (3 MB+ of source to ingest), while plotly.js-dist-min is a
// single pre-bundled file rollup doesn't need to re-parse.
const Plot = lazy(async () => {
  const [{ default: createPlotlyComponent }, plotlyMod] = await Promise.all([
    import('react-plotly.js/factory'),
    import('plotly.js-dist-min'),
  ]);
  // Dynamic ESM import always returns a Module namespace object whose
  // `.default` is the CJS `module.exports`. But some bundler configs
  // collapse single-default modules so that `plotlyMod` IS the Plotly
  // object — handle both shapes defensively.
  const Plotly =
    (plotlyMod as { default?: object }).default ?? (plotlyMod as unknown as object);
  return { default: createPlotlyComponent(Plotly) };
});

// Dispatcher: dq-failures and dq-gaps render as native HTML tables instead
// of Plotly tables. Plotly's uniform cell height made multi-line LLM
// rationales overflow into adjacent rows. The HTML table's per-row sizing
// fixes that and lets the two views share consistent typography.
//
// Split out so PlotlyTab can call useQuery unconditionally — keeps React's
// rules-of-hooks linter happy without depending on the parent's keying for
// safety.
export function PlotTab({ slug, caption }: { slug: string; caption: string }) {
  if (slug === 'dq-failures') {
    return (
      <div>
        <p className="text-ink-dim text-xs italic mb-3">{caption}</p>
        <DQFailuresVizTable />
      </div>
    );
  }
  if (slug === 'dq-gaps') {
    return (
      <div>
        <p className="text-ink-dim text-xs italic mb-3">{caption}</p>
        <DQGapsVizTable />
      </div>
    );
  }
  return <PlotlyTab slug={slug} caption={caption} />;
}

function PlotlyTab({ slug, caption }: { slug: string; caption: string }) {
  const q = useQuery({
    queryKey: ['viz', slug],
    queryFn: () => getVizFigure(slug),
    // Viz figures refresh on scan completion — Sidebar's QuickAction onSettled
    // path invalidates the ['viz'] prefix so ['viz', slug] refetches next view.
  });

  if (q.isLoading) {
    return <Hint>Loading chart…</Hint>;
  }
  if (q.error instanceof ApiError && q.error.code === 'no_metadata_loaded') {
    return (
      <Hint>
        No metadata loaded yet — hit <strong>Refresh metadata</strong> on the dashboard first.
      </Hint>
    );
  }
  if (q.error) {
    return <Hint error>Chart failed to load: {(q.error as Error).message}</Hint>;
  }
  if (!q.data?.figure) {
    return (
      <Hint>
        Not enough data yet. Run a <strong>Deep scan</strong>, <strong>PII scan</strong>, or the
        matching DQ scan from the sidebar and come back.
      </Hint>
    );
  }

  const fig = q.data.figure;
  return (
    <div>
      <p className="text-ink-dim text-xs italic mb-3">{caption}</p>
      <Suspense fallback={<Hint>Loading Plotly…</Hint>}>
        <Plot
          data={fig.data as Plotly.Data[]}
          layout={applyTheme(fig.layout as Partial<Plotly.Layout>)}
          useResizeHandler
          style={{ width: '100%', height: '560px' }}
          config={{
            displaylogo: false,
            responsive: true,
            // Strip the noisy modebar buttons the catalog viz doesn't need —
            // leaves pan/zoom/reset + download, which are the ones stewards
            // actually use. Mirrors the config we pass st.plotly_chart.
            modeBarButtonsToRemove: [
              'autoScale2d',
              'lasso2d',
              'select2d',
              'toggleSpikelines',
              'hoverClosestCartesian',
              'hoverCompareCartesian',
              'hoverClosest3d',
              'orbitRotation',
              'tableRotation',
            ],
            toImageButtonOptions: { filename: `metasift-${slug}` },
          }}
        />
      </Suspense>
    </div>
  );
}

// Unified dark theme applied to every figure. Builder overrides win where
// they set explicit values (lineage fades edges to slate-500; score-gauge
// sets its own colors), but the background / font / axis / hover-label
// defaults come from here so the /viz page feels cohesive instead of 11
// Plotly-default screenshots.
function applyTheme(layout: Partial<Plotly.Layout>): Partial<Plotly.Layout> {
  const merged: Record<string, unknown> = {
    ...layout,
    autosize: true,
    paper_bgcolor:
      (layout as { paper_bgcolor?: string }).paper_bgcolor ?? 'rgba(0,0,0,0)',
    plot_bgcolor: (layout as { plot_bgcolor?: string }).plot_bgcolor ?? 'rgba(0,0,0,0)',
    font: {
      family:
        'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
      size: 12,
      color: 'rgba(226, 232, 240, 0.92)',
      ...((layout as { font?: object }).font ?? {}),
    },
    hoverlabel: {
      bgcolor: 'rgba(15, 23, 42, 0.95)',
      bordercolor: 'rgba(148, 163, 184, 0.4)',
      font: {
        color: 'rgba(226, 232, 240, 0.95)',
        family: 'ui-monospace, SFMono-Regular, Menlo, monospace',
        size: 12,
      },
      ...((layout as { hoverlabel?: object }).hoverlabel ?? {}),
    },
    margin: {
      l: 40,
      r: 24,
      t: 48,
      b: 40,
      ...((layout as { margin?: object }).margin ?? {}),
    },
    colorway: (layout as { colorway?: string[] }).colorway ?? [
      '#38bdf8', // sky-400 — primary accent
      '#a78bfa', // violet-400
      '#f59e0b', // amber-500 — tainted / warning
      '#34d399', // emerald-400
      '#f472b6', // pink-400
      '#fb7185', // rose-400 — errors / critical
      '#22d3ee', // cyan-400
      '#facc15', // yellow-400
    ],
  };

  // Style x/y axes consistently. We mutate in-place on the nested dicts so
  // builder-set properties (e.g. `visible: false` on DAG axes) still apply.
  for (const axis of ['xaxis', 'yaxis']) {
    const a = (merged[axis] ?? {}) as Record<string, unknown>;
    merged[axis] = {
      gridcolor: 'rgba(148, 163, 184, 0.14)',
      linecolor: 'rgba(148, 163, 184, 0.35)',
      tickcolor: 'rgba(148, 163, 184, 0.35)',
      zerolinecolor: 'rgba(148, 163, 184, 0.25)',
      tickfont: { color: 'rgba(203, 213, 225, 0.85)', size: 11 },
      ...a,
    };
  }

  // Titles render a shade softer than body text so the chart dominates.
  if (merged.title && typeof merged.title === 'object') {
    merged.title = {
      ...(merged.title as Record<string, unknown>),
      font: {
        size: 14,
        color: 'rgba(226, 232, 240, 0.9)',
        ...((merged.title as { font?: object }).font ?? {}),
      },
    };
  }

  return merged as Partial<Plotly.Layout>;
}

function Hint({ children, error }: { children: React.ReactNode; error?: boolean }) {
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

