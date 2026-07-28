import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { CheckCircle2, Save, XCircle } from 'lucide-react';

import { api, ApiError } from '../api/client';
import { Card, ErrorNotice, Spinner, StatTile } from '../components/common';
import { formatDuration } from '../lib/format';

/** Health, feature availability, configuration audit and signal-plan tuning. */
export function SystemView({ intersectionId }: { intersectionId: string }) {
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [plan, setPlan] = useState({
    minimum_green_duration: '',
    maximum_green_duration: '',
    seconds_per_queued_vehicle: '',
  });

  const health = useQuery({
    queryKey: ['health'],
    queryFn: api.health,
    refetchInterval: 10_000,
  });

  const info = useQuery({ queryKey: ['system', 'info'], queryFn: api.systemInfo });
  const config = useQuery({
    queryKey: ['system', 'configuration'],
    queryFn: api.configurationReport,
  });

  const updatePlan = useMutation({
    mutationFn: () => {
      const payload: Record<string, number> = {};
      for (const [key, value] of Object.entries(plan)) {
        if (value !== '') payload[key] = Number(value);
      }
      return api.updatePlan(intersectionId, payload);
    },
    onSuccess: () => {
      setError(null);
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2500);
    },
    onError: (cause) => setError(cause instanceof ApiError ? cause.message : String(cause)),
  });

  const hasPlanChanges = Object.values(plan).some((value) => value !== '');

  return (
    <div className="space-y-6">
      {error && <ErrorNotice message={error} />}

      <Card title="System health">
        {health.isLoading && <Spinner />}
        {health.data && (
          <>
            <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
              <StatTile
                label="Status"
                value={health.data.status}
                tone={
                  health.data.status === 'healthy'
                    ? 'positive'
                    : health.data.status === 'degraded'
                      ? 'warning'
                      : 'danger'
                }
              />
              <StatTile label="Version" value={health.data.version} />
              <StatTile label="Uptime" value={formatDuration(health.data.uptime_seconds)} />
              <StatTile label="WebSocket clients" value={health.data.websocket_connections} />
            </div>

            <ul className="grid gap-2 sm:grid-cols-2">
              {health.data.services.map((service) => (
                <li
                  key={service.name}
                  className="flex items-start gap-2 rounded-lg bg-slate-950/50 px-3 py-2 text-sm"
                >
                  {service.ready ? (
                    <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-green-500" />
                  ) : (
                    <XCircle size={16} className="mt-0.5 shrink-0 text-red-500" />
                  )}
                  <div>
                    <div className="text-slate-200">{service.name.replaceAll('_', ' ')}</div>
                    {service.detail && (
                      <div className="mt-0.5 text-xs text-slate-500">{service.detail}</div>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Capabilities">
          {info.data && (
            <ul className="grid grid-cols-1 gap-1.5 text-sm sm:grid-cols-2">
              {Object.entries(info.data.features).map(([feature, enabled]) => (
                <li key={feature} className="flex items-center gap-2">
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${enabled ? 'bg-green-500' : 'bg-slate-600'}`}
                  />
                  <span className={enabled ? 'text-slate-200' : 'text-slate-500'}>
                    {feature.replaceAll('_', ' ')}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Configuration audit">
          {config.data && (
            <>
              <div
                className={`mb-3 flex items-center gap-2 text-sm ${
                  config.data.valid ? 'text-green-400' : 'text-amber-400'
                }`}
              >
                {config.data.valid ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
                {config.data.valid
                  ? `No problems for the ${config.data.environment} profile.`
                  : `${config.data.problems.length} problem(s) found.`}
              </div>
              {config.data.problems.length > 0 && (
                <ul className="list-inside list-disc space-y-1 text-sm text-amber-300/90">
                  {config.data.problems.map((problem) => (
                    <li key={problem}>{problem}</li>
                  ))}
                </ul>
              )}
              <p className="mt-3 text-xs text-slate-500">
                Checks that would block a safe production deployment — wildcard CORS, a missing API
                key, debug mode left on.
              </p>
            </>
          )}
        </Card>
      </div>

      <Card title="Signal plan">
        {info.data && (
          <dl className="mb-4 grid grid-cols-2 gap-3 text-sm lg:grid-cols-3">
            {Object.entries(info.data.signal_plan).map(([key, value]) => (
              <div key={key} className="rounded-lg bg-slate-950/50 px-3 py-2">
                <dt className="text-xs text-slate-500">{key.replaceAll('_', ' ')}</dt>
                <dd className="font-medium text-slate-200 tabular-nums">{value}</dd>
              </div>
            ))}
          </dl>
        )}

        <div className="grid gap-3 sm:grid-cols-3">
          <label className="block text-xs text-slate-400">
            Minimum green (s)
            <input
              type="number"
              min={1}
              max={300}
              className="field mt-1"
              placeholder="unchanged"
              value={plan.minimum_green_duration}
              onChange={(event) =>
                setPlan({ ...plan, minimum_green_duration: event.target.value })
              }
            />
          </label>
          <label className="block text-xs text-slate-400">
            Maximum green (s)
            <input
              type="number"
              min={1}
              max={600}
              className="field mt-1"
              placeholder="unchanged"
              value={plan.maximum_green_duration}
              onChange={(event) =>
                setPlan({ ...plan, maximum_green_duration: event.target.value })
              }
            />
          </label>
          <label className="block text-xs text-slate-400">
            Seconds per queued vehicle
            <input
              type="number"
              min={0}
              max={10}
              step={0.1}
              className="field mt-1"
              placeholder="unchanged"
              value={plan.seconds_per_queued_vehicle}
              onChange={(event) =>
                setPlan({ ...plan, seconds_per_queued_vehicle: event.target.value })
              }
            />
          </label>
        </div>

        <button
          type="button"
          className="btn-primary mt-4"
          disabled={!hasPlanChanges || updatePlan.isPending}
          onClick={() => updatePlan.mutate()}
        >
          <Save size={15} />
          {updatePlan.isPending ? 'Applying…' : 'Apply to controller'}
        </button>
        {saved && <span className="ml-3 text-sm text-green-400">Plan updated.</span>}
      </Card>
    </div>
  );
}
