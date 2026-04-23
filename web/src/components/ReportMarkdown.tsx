/**
 * Themed wrapper around react-markdown + remark-gfm. Overrides each element
 * so the rendered report matches the dark palette + typography the rest of
 * the app uses. No Tailwind typography plugin — stay dependency-light and
 * keep styling colocated with the markdown component.
 *
 * Lazy-loaded from `screens/Report.tsx` so the markdown chunk only lands
 * when a user visits /report.
 */

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export default function ReportMarkdown({ source }: { source: string }) {
  return (
    <article className="rounded-xl border border-ink-border bg-ink-panel/30 px-6 py-6">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => (
            <h1 className="text-2xl font-bold tracking-tight text-ink-text mt-2 mb-4 border-b border-ink-border pb-2">
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2 className="text-xl font-bold tracking-tight text-accent-bright mt-8 mb-3">
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3 className="text-lg font-semibold text-ink-text mt-6 mb-2">{children}</h3>
          ),
          p: ({ children }) => <p className="text-sm text-ink-text leading-relaxed my-3">{children}</p>,
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noreferrer"
              className="text-accent-soft underline hover:text-accent-bright"
            >
              {children}
            </a>
          ),
          em: ({ children }) => <em className="italic text-ink-dim">{children}</em>,
          strong: ({ children }) => (
            <strong className="font-semibold text-ink-text">{children}</strong>
          ),
          hr: () => <hr className="my-6 border-ink-border" />,
          ul: ({ children }) => (
            <ul className="list-disc list-inside text-sm text-ink-text my-3 space-y-1">
              {children}
            </ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal list-inside text-sm text-ink-text my-3 space-y-1">
              {children}
            </ol>
          ),
          li: ({ children }) => <li className="leading-relaxed">{children}</li>,
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-accent/40 pl-4 my-3 text-sm text-ink-soft italic">
              {children}
            </blockquote>
          ),
          code: ({ className, children, ...props }) => {
            const isBlock = className?.startsWith('language-');
            if (isBlock) {
              return (
                <pre className="bg-ink-bg border border-ink-border rounded-md p-3 overflow-auto text-xs my-3">
                  <code className="font-mono text-ink-text" {...props}>
                    {children}
                  </code>
                </pre>
              );
            }
            return (
              <code
                className="font-mono text-xs rounded px-1 py-0.5 bg-ink-panel/60 text-accent-soft border border-ink-border"
                {...props}
              >
                {children}
              </code>
            );
          },
          table: ({ children }) => (
            <div className="overflow-x-auto my-4">
              <table className="w-full text-sm border border-ink-border rounded-md overflow-hidden">
                {children}
              </table>
            </div>
          ),
          thead: ({ children }) => (
            <thead className="bg-ink-panel/60 border-b border-ink-border">{children}</thead>
          ),
          th: ({ children }) => (
            <th className="text-left text-mini font-mono uppercase tracking-wider text-ink-dim px-3 py-2">
              {children}
            </th>
          ),
          tr: ({ children }) => (
            <tr className="border-b border-ink-border/60 last:border-b-0">{children}</tr>
          ),
          td: ({ children }) => (
            <td className="px-3 py-2 text-ink-text align-top text-sm">{children}</td>
          ),
        }}
      >
        {source}
      </ReactMarkdown>
    </article>
  );
}
