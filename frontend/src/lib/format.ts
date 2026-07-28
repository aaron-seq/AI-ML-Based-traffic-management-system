/** Formatting helpers shared across views. */

/** Formats a duration in seconds as a compact human-readable string. */
export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '—';
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)} min`;
  if (seconds < 86_400) return `${(seconds / 3600).toFixed(1)} h`;
  return `${(seconds / 86_400).toFixed(1)} days`;
}

/** Formats a count with thousands separators. */
export function formatCount(value: number): string {
  return new Intl.NumberFormat().format(value);
}
