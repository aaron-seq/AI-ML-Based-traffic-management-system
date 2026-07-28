import clsx from 'clsx';
import type { ReactNode } from 'react';
import type { CongestionLevel } from '../api/types';

interface StatTileProps {
  label: string;
  value: ReactNode;
  unit?: string;
  hint?: string;
  tone?: 'default' | 'positive' | 'warning' | 'danger';
}

const TONE_CLASSES = {
  default: 'text-slate-100',
  positive: 'text-green-400',
  warning: 'text-amber-400',
  danger: 'text-red-400',
} as const;

/** A single labelled metric. */
export function StatTile({ label, value, unit, hint, tone = 'default' }: StatTileProps) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
      <div className="text-xs font-medium tracking-wide text-slate-500 uppercase">{label}</div>
      <div className={clsx('mt-1 text-2xl font-semibold tabular-nums', TONE_CLASSES[tone])}>
        {value}
        {unit && <span className="ml-1 text-sm font-normal text-slate-500">{unit}</span>}
      </div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

const CONGESTION_STYLES: Record<CongestionLevel, string> = {
  free_flow: 'bg-green-500/15 text-green-400 ring-1 ring-green-500/30',
  light: 'bg-lime-500/15 text-lime-400 ring-1 ring-lime-500/30',
  moderate: 'bg-amber-500/15 text-amber-400 ring-1 ring-amber-500/30',
  heavy: 'bg-orange-500/15 text-orange-400 ring-1 ring-orange-500/30',
  congested: 'bg-red-500/15 text-red-400 ring-1 ring-red-500/30',
};

export function CongestionBadge({ level }: { level: CongestionLevel }) {
  return (
    <span className={clsx('badge', CONGESTION_STYLES[level])}>{level.replaceAll('_', ' ')}</span>
  );
}

export function Card({
  title,
  action,
  children,
  className,
}: {
  title?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={clsx('card', className)}>
      {(title || action) && (
        <header className="mb-4 flex items-center justify-between gap-3">
          {title && <h2 className="card-title">{title}</h2>}
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

/** Non-blocking error notice; the rest of the dashboard keeps working. */
export function ErrorNotice({ message }: { message: string }) {
  return (
    <div
      role="alert"
      className="rounded-lg border border-red-900/60 bg-red-950/40 px-4 py-3 text-sm text-red-300"
    >
      {message}
    </div>
  );
}

export function EmptyState({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-700 px-4 py-8 text-center text-sm text-slate-500">
      {message}
    </div>
  );
}

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-slate-500" role="status">
      <span className="h-3 w-3 animate-spin rounded-full border-2 border-slate-600 border-t-sky-400" />
      {label}
    </div>
  );
}

