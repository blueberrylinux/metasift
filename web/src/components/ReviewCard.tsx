/**
 * One card in the review queue. Mirrors `app/main.py::_render_review_card`:
 *
 *   - description items: current-vs-suggested side-by-side; Edit opens a
 *     textarea pre-filled with the suggested value.
 *   - pii_tag items: current-vs-suggested labels; Edit opens a <select>
 *     constrained to the PII tag allowlist.
 *
 * The three action buttons call the backend dispatcher — Accept applies as-
 * is, Save & apply (edit mode) posts the edited value, Reject records a
 * dismissal. On any success we invalidate ['review'] so the card drops off
 * and the filter counts refresh.
 */

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import {
  acceptEditedReview,
  acceptReview,
  ApiError,
  rejectReview,
  type ReviewItem,
} from '../lib/api';

const PII_TAG_OPTIONS = ['PII.Sensitive', 'PII.NonSensitive', 'PII.None'] as const;

export function ReviewCard({ item }: { item: ReviewItem }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(item.new);

  // Reset the edit draft when the underlying card identity changes (rare —
  // only happens if a rescan replaces an in-flight card with a different
  // suggestion for the same key, since React's key prop unmounts cards whose
  // key changed). Keying on item.key avoids clobbering in-progress typing.
  useEffect(() => {
    setDraft(item.new);
    setEditing(false);
  }, [item.key]);

  const invalidate = () => qc.invalidateQueries({ queryKey: ['review'] });

  const accept = useMutation({
    mutationFn: () => acceptReview(item.key),
    onSuccess: invalidate,
  });
  const acceptEdited = useMutation({
    mutationFn: (value: string) => acceptEditedReview(item.key, value),
    onSuccess: invalidate,
  });
  const rej = useMutation({
    mutationFn: () => rejectReview(item.key),
    onSuccess: invalidate,
  });

  const pending = accept.isPending || acceptEdited.isPending || rej.isPending;
  const lastError =
    accept.error instanceof ApiError
      ? accept.error
      : acceptEdited.error instanceof ApiError
        ? acceptEdited.error
        : rej.error instanceof ApiError
          ? rej.error
          : null;

  return (
    <div className="rounded-xl border border-ink-border bg-ink-panel/40 p-5 flex flex-col gap-3">
      <CardHeader item={item} />
      {item.reason && (
        <p className="text-xs text-ink-dim italic">
          <span className="text-ink-soft not-italic">Why:</span> {item.reason}
        </p>
      )}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <Column label="Current">
          {item.kind === 'description' ? (
            <BlockquoteOrEmpty text={item.old ?? ''} />
          ) : (
            <TagPill value={item.old} muted />
          )}
        </Column>
        <Column label="Suggested">
          {editing ? (
            item.kind === 'description' ? (
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                rows={4}
                className="w-full rounded-md border border-accent/40 bg-ink-panel px-2 py-1.5 text-sm text-ink-text focus:outline-none focus:border-accent/60"
              />
            ) : (
              <select
                value={PII_TAG_OPTIONS.includes(draft as (typeof PII_TAG_OPTIONS)[number]) ? draft : item.new}
                onChange={(e) => setDraft(e.target.value)}
                className="w-full rounded-md border border-accent/40 bg-ink-panel px-2 py-1.5 text-sm text-ink-text focus:outline-none focus:border-accent/60"
              >
                {PII_TAG_OPTIONS.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            )
          ) : item.kind === 'description' ? (
            <BlockquoteOrEmpty text={item.new} />
          ) : (
            <TagPill value={item.new} />
          )}
        </Column>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        {editing ? (
          <>
            <button
              onClick={() => acceptEdited.mutate(draft)}
              disabled={pending || !draft.trim()}
              className="px-3 py-1.5 rounded-md text-sm font-mono bg-accent/30 hover:bg-accent/40 text-accent-bright border border-accent/40 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              💾 Save & apply
            </button>
            <button
              onClick={() => {
                setEditing(false);
                setDraft(item.new);
              }}
              disabled={pending}
              className="px-3 py-1.5 rounded-md text-sm font-mono bg-ink-panel hover:bg-ink-panel/80 text-ink-soft border border-ink-border"
            >
              Cancel
            </button>
          </>
        ) : (
          <>
            <button
              onClick={() => accept.mutate()}
              disabled={pending}
              className="px-3 py-1.5 rounded-md text-sm font-mono bg-accent/30 hover:bg-accent/40 text-accent-bright border border-accent/40 disabled:opacity-50"
            >
              ✔ Accept
            </button>
            <button
              onClick={() => setEditing(true)}
              disabled={pending}
              className="px-3 py-1.5 rounded-md text-sm font-mono bg-ink-panel hover:bg-ink-panel/80 text-ink-soft border border-ink-border disabled:opacity-50"
            >
              ✎ Edit
            </button>
            <button
              onClick={() => rej.mutate()}
              disabled={pending}
              className="px-3 py-1.5 rounded-md text-sm font-mono bg-ink-panel hover:bg-error/10 hover:text-error-soft text-ink-soft border border-ink-border disabled:opacity-50"
            >
              ✖ Reject
            </button>
          </>
        )}
        {pending && <span className="text-xs font-mono text-ink-dim ml-1">working…</span>}
        {lastError && (
          <span className="text-xs font-mono text-error-soft ml-1">
            {lastError.code}: {lastError.message}
          </span>
        )}
      </div>
    </div>
  );
}

function CardHeader({ item }: { item: ReviewItem }) {
  if (item.kind === 'description') {
    const isDraft = item.key.startsWith('doc::');
    return (
      <div>
        <div className="flex items-center gap-2 text-sm">
          <span>{isDraft ? '✏️' : '🧹'}</span>
          <span className="font-semibold">{isDraft ? 'New description' : 'Stale description'}</span>
          <span className="text-xs font-mono text-ink-dim">· confidence {pct(item.confidence)}</span>
        </div>
        <code className="text-xs font-mono text-ink-dim block mt-0.5 break-all">{item.fqn}</code>
      </div>
    );
  }
  return (
    <div>
      <div className="flex items-center gap-2 text-sm">
        <span>🔐</span>
        <span className="font-semibold">PII tag gap</span>
        <span className="text-xs font-mono text-ink-dim">· confidence {pct(item.confidence)}</span>
      </div>
      <code className="text-xs font-mono text-ink-dim block mt-0.5 break-all">
        {item.fqn} · column <span className="text-accent-soft">{item.column}</span>
      </code>
    </div>
  );
}

function Column({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs font-mono uppercase tracking-wider text-ink-dim mb-1">{label}</div>
      {children}
    </div>
  );
}

function BlockquoteOrEmpty({ text }: { text: string }) {
  if (!text) {
    return <div className="text-xs italic text-ink-dim">(empty)</div>;
  }
  return (
    <blockquote className="text-sm text-ink-text border-l-2 border-ink-border pl-3 whitespace-pre-wrap">
      {text}
    </blockquote>
  );
}

function TagPill({ value, muted }: { value: string | null; muted?: boolean }) {
  if (!value) {
    return <span className="text-xs italic text-ink-dim">(untagged)</span>;
  }
  return (
    <span
      className={
        'inline-block px-2 py-0.5 rounded font-mono text-xs border ' +
        (muted
          ? 'text-ink-soft bg-ink-panel border-ink-border'
          : 'text-accent-bright bg-accent/20 border-accent/40')
      }
    >
      {value}
    </span>
  );
}

function pct(x: number): string {
  return `${Math.round(x * 100)}%`;
}
