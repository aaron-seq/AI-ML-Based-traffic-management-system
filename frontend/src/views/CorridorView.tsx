import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { MapPin, Plus, Waves } from 'lucide-react';

import { api, ApiError } from '../api/client';
import { Card, CongestionBadge, EmptyState, ErrorNotice, Spinner, StatTile } from '../components/common';

/**
 * Corridor view: every registered intersection plus the green-wave plan that
 * coordinates them. This is where a single adaptive junction becomes a
 * coordinated network.
 */
export function CorridorView({
  selectedId,
  onSelect,
}: {
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ id: '', name: '', distance: '400' });
  const [designSpeed, setDesignSpeed] = useState('50');

  const intersections = useQuery({
    queryKey: ['intersections'],
    queryFn: api.listIntersections,
    refetchInterval: 10_000,
  });

  const plan = useQuery({
    queryKey: ['coordination', designSpeed],
    queryFn: () => api.coordinationPlan(Number(designSpeed) || undefined),
    refetchInterval: 30_000,
  });

  const addIntersection = useMutation({
    mutationFn: () =>
      api.createIntersection({
        intersection_id: form.id.trim(),
        name: form.name.trim() || form.id.trim(),
        distance_from_previous_metres: Number(form.distance) || 0,
      }),
    onSuccess: () => {
      setError(null);
      setForm({ id: '', name: '', distance: '400' });
      void queryClient.invalidateQueries({ queryKey: ['intersections'] });
      void queryClient.invalidateQueries({ queryKey: ['coordination'] });
    },
    onError: (cause) =>
      setError(cause instanceof ApiError ? cause.message : String(cause)),
  });

  const canSubmit = /^[a-z0-9_-]{1,64}$/i.test(form.id.trim());

  return (
    <div className="space-y-6">
      {error && <ErrorNotice message={error} />}

      <Card title="Registered intersections">
        {intersections.isLoading && <Spinner />}
        {intersections.data?.length === 0 && <EmptyState message="No intersections registered." />}

        <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {intersections.data?.map((intersection) => {
            const selected = intersection.intersection_id === selectedId;
            return (
              <li key={intersection.intersection_id}>
                <button
                  type="button"
                  onClick={() => onSelect(intersection.intersection_id)}
                  aria-pressed={selected}
                  className={`w-full rounded-lg border p-4 text-left transition-colors ${
                    selected
                      ? 'border-sky-500 bg-sky-500/10'
                      : 'border-slate-800 bg-slate-950/50 hover:border-slate-600'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="flex items-center gap-1.5 font-medium text-slate-100">
                        <MapPin size={14} className="text-slate-500" />
                        {intersection.name}
                      </div>
                      <div className="mt-0.5 font-mono text-xs text-slate-500">
                        {intersection.intersection_id}
                      </div>
                    </div>
                    <CongestionBadge level={intersection.congestion_level} />
                  </div>
                  <div className="mt-3 flex items-center gap-4 text-xs text-slate-400">
                    <span>{intersection.current_phase.replaceAll('_', ' ')}</span>
                    <span className="tabular-nums">{intersection.total_vehicles} veh</span>
                    {intersection.emergency_mode_active && (
                      <span className="font-medium text-red-400">pre-empted</span>
                    )}
                  </div>
                </button>
              </li>
            );
          })}
        </ul>
      </Card>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <Card title="Green-wave coordination">
          {plan.isLoading && <Spinner />}
          {plan.data && (
            <>
              <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
                <StatTile
                  label="Corridor length"
                  value={plan.data.corridor_length_metres.toFixed(0)}
                  unit="m"
                />
                <StatTile
                  label="Travel time"
                  value={plan.data.corridor_travel_time_seconds.toFixed(0)}
                  unit="s"
                />
                <StatTile
                  label="Common cycle"
                  value={plan.data.common_cycle_seconds}
                  unit="s"
                  hint="Shared so offsets stay aligned"
                />
                <StatTile label="Intersections" value={plan.data.corridor.length} />
              </div>

              <label className="mb-4 block text-xs text-slate-400">
                Design speed (km/h)
                <input
                  type="number"
                  min={10}
                  max={130}
                  className="field mt-1 max-w-40"
                  value={designSpeed}
                  onChange={(event) => setDesignSpeed(event.target.value)}
                />
              </label>

              <ol className="space-y-2">
                {plan.data.corridor.map((id, index) => {
                  const offset = plan.data.offsets_seconds[id] ?? 0;
                  const maxOffset = Math.max(...Object.values(plan.data.offsets_seconds), 1);
                  return (
                    <li key={id} className="flex items-center gap-3">
                      <span className="w-6 text-right font-mono text-xs text-slate-500">
                        {index + 1}
                      </span>
                      <span className="w-40 truncate text-sm text-slate-200">{id}</span>
                      <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-800">
                        <div
                          className="h-full rounded-full bg-linear-to-r from-sky-500 to-green-500"
                          style={{ width: `${Math.max(4, (offset / maxOffset) * 100)}%` }}
                        />
                      </div>
                      <span className="w-16 text-right text-sm text-slate-400 tabular-nums">
                        +{offset.toFixed(1)}s
                      </span>
                    </li>
                  );
                })}
              </ol>

              <p className="mt-4 flex items-start gap-2 text-xs text-slate-500">
                <Waves size={14} className="mt-0.5 shrink-0" />
                Each intersection starts its green this many seconds after the first, so a platoon
                travelling at the design speed meets a green at every junction.
              </p>
            </>
          )}
        </Card>

        <Card title="Add an intersection">
          <div className="space-y-3">
            <label className="block text-xs text-slate-400">
              Identifier
              <input
                className="field mt-1"
                placeholder="oak_ave"
                value={form.id}
                onChange={(event) => setForm({ ...form, id: event.target.value })}
              />
            </label>
            <label className="block text-xs text-slate-400">
              Display name
              <input
                className="field mt-1"
                placeholder="Oak Avenue"
                value={form.name}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
              />
            </label>
            <label className="block text-xs text-slate-400">
              Distance from previous (metres)
              <input
                type="number"
                min={0}
                className="field mt-1"
                value={form.distance}
                onChange={(event) => setForm({ ...form, distance: event.target.value })}
              />
            </label>
            <button
              type="button"
              className="btn-primary w-full"
              disabled={!canSubmit || addIntersection.isPending}
              onClick={() => addIntersection.mutate()}
            >
              <Plus size={15} />
              {addIntersection.isPending ? 'Adding…' : 'Add to corridor'}
            </button>
            {!canSubmit && form.id !== '' && (
              <p className="text-xs text-amber-400">
                Use letters, numbers, hyphens or underscores only.
              </p>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}
