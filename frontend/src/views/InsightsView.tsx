import { useQuery } from '@tanstack/react-query';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { Leaf, Timer, TrendingUp, Wallet } from 'lucide-react';

import { api } from '../api/client';
import { Card, EmptyState, ErrorNotice, Spinner, StatTile } from '../components/common';
import { formatDuration } from '../lib/format';

const CHART_TOOLTIP_STYLE = {
  background: '#0f172a',
  border: '1px solid #1e293b',
  borderRadius: 8,
  color: '#e2e8f0',
} as const;

/**
 * Analytics, forecasting and impact — the screens that answer "is this
 * deployment worth it?" rather than "what is the signal doing right now?".
 */
export function InsightsView({ intersectionId }: { intersectionId: string }) {
  const summary = useQuery({
    queryKey: ['analytics', 'summary'],
    queryFn: () => api.analyticsSummary('current'),
    refetchInterval: 15_000,
  });

  const forecast = useQuery({
    queryKey: ['forecast', intersectionId],
    queryFn: () => api.forecast(intersectionId),
    refetchInterval: 30_000,
  });

  const impact = useQuery({
    queryKey: ['impact', intersectionId],
    queryFn: () => api.impact(intersectionId),
    refetchInterval: 30_000,
  });

  const cumulative = useQuery({
    queryKey: ['impact', intersectionId, 'cumulative'],
    queryFn: () => api.cumulativeImpact(intersectionId),
    refetchInterval: 60_000,
  });

  const laneDistribution = summary.data?.recent_traffic?.lane_distribution_percent
    ? Object.entries(summary.data.recent_traffic.lane_distribution_percent)
        .filter(([lane]) => lane !== 'unknown')
        .map(([lane, percent]) => ({ lane, percent }))
    : [];

  const forecastSeries =
    forecast.data?.points.map((point) => ({
      horizon: `+${point.horizon_minutes}m`,
      expected: point.expected_vehicles,
      lower: point.lower_bound,
      upper: point.upper_bound,
      band: point.upper_bound - point.lower_bound,
    })) ?? [];

  return (
    <div className="space-y-6">
      {/* --- Impact ---------------------------------------------------------- */}
      <Card title="Modelled impact versus a fixed-time plan">
        {impact.isLoading && <Spinner label="Estimating impact…" />}
        {impact.isError && <ErrorNotice message="Could not load the impact estimate." />}

        {impact.data && (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <StatTile
                label="Delay saved"
                value={formatDuration(Math.max(0, impact.data.delay_saved_seconds))}
                hint={`${impact.data.delay_reduction_percent.toFixed(1)}% less delay`}
                tone={impact.data.delay_saved_seconds > 0 ? 'positive' : 'warning'}
              />
              <StatTile
                label="Fuel saved"
                value={impact.data.fuel_litres_saved.toFixed(2)}
                unit="L"
                tone="positive"
              />
              <StatTile
                label="CO₂ avoided"
                value={impact.data.co2_kg_avoided.toFixed(2)}
                unit="kg"
                tone="positive"
              />
              <StatTile
                label="Value of time"
                value={impact.data.economic_value_saved.toFixed(2)}
                unit={impact.data.currency}
                tone="positive"
              />
            </div>

            <details className="mt-4 rounded-lg border border-slate-800 bg-slate-950/50 p-3">
              <summary className="cursor-pointer text-xs font-medium text-slate-400">
                Assumptions behind these figures
              </summary>
              <dl className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
                {Object.entries(impact.data.assumptions).map(([key, value]) => (
                  <div key={key} className="flex gap-2">
                    <dt className="shrink-0 text-slate-500">{key.replaceAll('_', ' ')}:</dt>
                    <dd className="text-slate-300">{String(value)}</dd>
                  </div>
                ))}
              </dl>
            </details>
          </>
        )}
      </Card>

      {cumulative.data?.projection?.available && (
        <Card title="Annual projection">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile
              label="Delay saved / year"
              value={String(cumulative.data.projection.annual_delay_saved_hours ?? '—')}
              unit="h"
            />
            <StatTile
              label="Fuel / year"
              value={String(cumulative.data.projection.annual_fuel_litres_saved ?? '—')}
              unit="L"
            />
            <StatTile
              label="CO₂ / year"
              value={String(cumulative.data.projection.annual_co2_tonnes_avoided ?? '—')}
              unit="t"
            />
            <StatTile
              label="Value / year"
              value={String(cumulative.data.projection.annual_economic_value_saved ?? '—')}
            />
          </div>
          <p className="mt-3 text-xs text-amber-400/80">
            {String(cumulative.data.projection.caveat ?? '')}
          </p>
        </Card>
      )}

      {/* --- Forecast -------------------------------------------------------- */}
      <Card title="Short-term demand forecast">
        {forecast.isLoading && <Spinner label="Building forecast…" />}
        {forecast.data && forecast.data.points.length === 0 && (
          <EmptyState message={forecast.data.notes ?? 'Not enough history to forecast yet.'} />
        )}

        {forecast.data && forecast.data.points.length > 0 && (
          <>
            <div className="mb-3 flex items-center gap-3 text-xs text-slate-400">
              <span className="badge bg-slate-800 text-slate-300">
                <TrendingUp size={12} /> {forecast.data.method}
              </span>
              <span>
                confidence{' '}
                <span
                  className={
                    forecast.data.confidence > 0.6
                      ? 'text-green-400'
                      : forecast.data.confidence > 0.3
                        ? 'text-amber-400'
                        : 'text-red-400'
                  }
                >
                  {(forecast.data.confidence * 100).toFixed(0)}%
                </span>
              </span>
              <span>{forecast.data.observations_used} observations</span>
            </div>

            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={forecastSeries}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="horizon" stroke="#64748b" fontSize={12} />
                  <YAxis stroke="#64748b" fontSize={12} />
                  <Tooltip contentStyle={CHART_TOOLTIP_STYLE} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Area
                    type="monotone"
                    dataKey="upper"
                    name="Upper bound"
                    stroke="#334155"
                    fill="#1e293b"
                    fillOpacity={0.6}
                  />
                  <Area
                    type="monotone"
                    dataKey="lower"
                    name="Lower bound"
                    stroke="#334155"
                    fill="#0f172a"
                    fillOpacity={1}
                  />
                  <Line
                    type="monotone"
                    dataKey="expected"
                    name="Expected vehicles"
                    stroke="#38bdf8"
                    strokeWidth={2}
                    dot={{ r: 3 }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            <p className="mt-2 text-xs text-slate-500">
              The shaded band is a 95% prediction interval; it widens with the horizon.
            </p>
          </>
        )}
      </Card>

      {/* --- Analytics ------------------------------------------------------- */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Approach distribution">
          {laneDistribution.length === 0 ? (
            <EmptyState message="Run a detection to populate the distribution." />
          ) : (
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={laneDistribution} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis type="number" stroke="#64748b" fontSize={12} unit="%" />
                  <YAxis dataKey="lane" type="category" stroke="#64748b" fontSize={12} width={60} />
                  <Tooltip contentStyle={CHART_TOOLTIP_STYLE} />
                  <Bar dataKey="percent" fill="#34d399" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>

        <Card title="Pipeline">
          {summary.isLoading && <Spinner />}
          {summary.data && (
            <dl className="space-y-3 text-sm">
              <Row
                icon={<Timer size={14} />}
                label="Mean inference"
                value={`${((summary.data.pipeline_health?.average_processing_seconds ?? 0) * 1000).toFixed(0)} ms`}
              />
              <Row
                icon={<TrendingUp size={14} />}
                label="Mean confidence"
                value={`${((summary.data.pipeline_health?.average_confidence ?? 0) * 100).toFixed(0)}%`}
              />
              <Row
                icon={<Leaf size={14} />}
                label="Detections recorded"
                value={String(summary.data.detection_count)}
              />
              <Row
                icon={<Wallet size={14} />}
                label="Persistence"
                value={summary.data.persistence_enabled ? 'Enabled' : 'In-memory only'}
              />
              {summary.data.traffic_flow && (
                <Row
                  icon={<TrendingUp size={14} />}
                  label="Demand trend"
                  value={`${summary.data.traffic_flow.trend} (${summary.data.traffic_flow.change_percent > 0 ? '+' : ''}${summary.data.traffic_flow.change_percent}%)`}
                />
              )}
            </dl>
          )}
        </Card>
      </div>
    </div>
  );
}

function Row({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center justify-between border-b border-slate-800 pb-2 last:border-0">
      <dt className="flex items-center gap-2 text-slate-400">
        {icon}
        {label}
      </dt>
      <dd className="font-medium text-slate-200 tabular-nums">{value}</dd>
    </div>
  );
}
