/**
 * Markdown renderer tuned for Stew's chat bubbles.
 *
 * The agent is prompted to reply in markdown ("tight prose, bullets,
 * tables"), so rendering `content` as plain text surfaces raw `**bold**`
 * and `-` list markers to the user. This component is the minimum needed
 * to render that markdown inside a 56rem-wide chat bubble without the
 * heavy `ReportMarkdown` heading/margin scale.
 *
 * Intentionally narrower than `ReportMarkdown`:
 *   - tighter vertical rhythm (my-1 not my-3)
 *   - inline-first list styling
 *   - headings degrade to bold paragraphs — if Stew emits an h1 in a
 *     chat reply it's almost certainly a section label, not a page title
 */

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export function ChatMarkdown({ source }: { source: string }) {
  return (
    <div className="chat-md text-[14px] text-slate-200 leading-relaxed">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <p className="my-1.5 first:mt-0 last:mb-0">{children}</p>,
          strong: ({ children }) => (
            <strong className="font-semibold text-white">{children}</strong>
          ),
          em: ({ children }) => <em className="italic text-slate-300">{children}</em>,
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noreferrer"
              className="text-emerald-300 underline hover:text-emerald-200"
            >
              {children}
            </a>
          ),
          ul: ({ children }) => (
            <ul className="list-disc pl-5 my-1.5 space-y-0.5">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal pl-5 my-1.5 space-y-0.5">{children}</ol>
          ),
          li: ({ children }) => <li className="leading-snug">{children}</li>,
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-emerald-500/40 pl-3 my-2 text-slate-300 italic">
              {children}
            </blockquote>
          ),
          code: ({ className, children, ...props }) => {
            const isBlock = className?.startsWith('language-');
            if (isBlock) {
              return (
                <pre className="bg-slate-950/80 border border-slate-800 rounded-md p-3 overflow-auto text-[12px] my-2">
                  <code className="font-mono text-slate-200" {...props}>
                    {children}
                  </code>
                </pre>
              );
            }
            return (
              <code
                className="font-mono text-[12px] rounded px-1 py-0.5 bg-slate-900/70 text-emerald-200 border border-slate-800"
                {...props}
              >
                {children}
              </code>
            );
          },
          hr: () => <hr className="my-3 border-slate-800" />,
          h1: ({ children }) => (
            <div className="font-semibold text-white mt-2 mb-1">{children}</div>
          ),
          h2: ({ children }) => (
            <div className="font-semibold text-white mt-2 mb-1">{children}</div>
          ),
          h3: ({ children }) => (
            <div className="font-semibold text-slate-100 mt-2 mb-1">{children}</div>
          ),
          table: ({ children }) => (
            <div className="overflow-x-auto my-2">
              <table className="w-full text-[12px] border border-slate-800 rounded">
                {children}
              </table>
            </div>
          ),
          thead: ({ children }) => (
            <thead className="bg-slate-900/60 border-b border-slate-800">{children}</thead>
          ),
          th: ({ children }) => (
            <th className="text-left font-mono uppercase tracking-wider text-slate-400 px-2 py-1.5 text-[10px]">
              {children}
            </th>
          ),
          tr: ({ children }) => (
            <tr className="border-b border-slate-800/60 last:border-b-0">{children}</tr>
          ),
          td: ({ children }) => (
            <td className="px-2 py-1.5 text-slate-200 align-top">{children}</td>
          ),
        }}
      >
        {source}
      </ReactMarkdown>
    </div>
  );
}
