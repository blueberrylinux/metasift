/**
 * Sandbox-mode helpers — single source of truth for "are we in the public
 * read-only demo?" Reads from the existing /health query so we don't fire a
 * second poll just for the flag.
 *
 * Local / self-hosted users: API returns `sandbox: false` (or omits the
 * field on older builds), every helper here returns `false` / no-op, the
 * banner / BYO-key modal / read-only Settings stay hidden. Zero footprint.
 */

import { useQuery } from '@tanstack/react-query';

import { getActiveScan, getHealth, type ScanRun } from './api';

export function useSandbox(): boolean {
  // Mirrors TopBar.tsx's queryKey + interval so React Query coalesces the
  // two consumers onto a single fetch. Don't change either side without
  // updating the other.
  const q = useQuery({
    queryKey: ['health'],
    queryFn: getHealth,
    refetchInterval: 30_000,
    retry: false,
    staleTime: 10_000,
  });
  return q.data?.sandbox === true;
}

/**
 * Returns the next 04:00 UTC reset time as a Date, given a `now`. The
 * sandbox VPS runs `make reset-all && make seed` via systemd timer at this
 * hour every day per SANDBOX_DEPLOYMENT_PLAN.md §8. Pure function — easy
 * to unit-test and avoids surprising clock-driven re-renders.
 */
export function nextResetAt(now: Date = new Date()): Date {
  const next = new Date(
    Date.UTC(
      now.getUTCFullYear(),
      now.getUTCMonth(),
      now.getUTCDate(),
      4,
      0,
      0,
      0,
    ),
  );
  if (next.getTime() <= now.getTime()) {
    next.setUTCDate(next.getUTCDate() + 1);
  }
  return next;
}

/** Human-readable countdown to the next reset. e.g. "in 3h 12m" / "in 47m". */
export function formatResetCountdown(now: Date = new Date()): string {
  const ms = nextResetAt(now).getTime() - now.getTime();
  const totalMin = Math.max(0, Math.floor(ms / 60_000));
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  if (h === 0) return `in ${m}m`;
  return `in ${h}h ${m}m`;
}

/**
 * Active-scan polling — sandbox-only. Returns the in-flight scan_runs row
 * (or null) on a 5s cadence, used by sidebar QuickActions to disable
 * themselves while another visitor's scan is mid-flight on the shared
 * deployment.
 *
 * Outside sandbox the query is `enabled: false` so no traffic is spent
 * polling locally — single-user installs already get the same effect from
 * the per-button `state.running` flag.
 */
export function useActiveScan(): { active: ScanRun | null } {
  const sandbox = useSandbox();
  const q = useQuery({
    queryKey: ['scans', 'active'],
    queryFn: getActiveScan,
    enabled: sandbox,
    refetchInterval: sandbox ? 5_000 : false,
    staleTime: 2_000,
    retry: false,
  });
  return { active: q.data?.active ?? null };
}
