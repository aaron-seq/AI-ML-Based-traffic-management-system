import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Footprints, Pause, Play, Send } from 'lucide-react';

import { api, ApiError } from '../api/client';
import type { EmergencyType, IntersectionStatus, LaneDirection } from '../api/types';
import { IntersectionDiagram } from '../components/IntersectionDiagram';
import { Card, CongestionBadge, EmptyState, ErrorNotice, StatTile } from '../components/common';
import type { TrafficEvent } from '../hooks/useTrafficSocket';

const LANES: LaneDirection[] = ['north', 'south', 'east', 'west'];
const EMERGENCY_TYPES: EmergencyType[] = ['ambulance', 'fire_truck', 'police', 'rescue'];

interface LiveViewProps {
  intersectionId: string;
  status: IntersectionStatus | null;
  events: TrafficEvent[];
}

export function LiveView({ intersectionId, status, events }: LiveViewProps) {
  const queryClient = useQueryClient();
  const [actionError, setActionError] = useState<string | null>(null);
  const [counts, setCounts] = useState<Record<LaneDirection, string>>({
    north: '',
    south: '',
    east: '',
    west: '',
    unknown: '',
  });
  const [emergencyLane, setEmergencyLane] = useState<LaneDirection>('north');
  const [emergencyType, setEmergencyType] = useState<EmergencyType>('ambulance');

  const { data: activeAlerts } = useQuery({
    queryKey: ['emergency', 'active'],
    queryFn: api.activeEmergencies,
    refetchInterval: 5000,
  });

  function handleError(error: unknown) {
    const message =
      error instanceof ApiError
        ? `${error.message}${error.requestId ? ` (request ${error.requestId})` : ''}`
        : String(error);
    setActionError(message);
  }

  const submitCounts = useMutation({
    mutationFn: () => {
      const payload: Partial<Record<LaneDirection, number>> = {};
      for (const lane of LANES) {
        const raw = counts[lane];
        payload[lane] = raw === '' ? 0 : Math.max(0, Number.parseInt(raw, 10) || 0);
      }
      return api.submitCounts(intersectionId, payload);
    },
    onSuccess: () => setActionError(null),
    onError: handleError,
  });

  const triggerEmergency = useMutation({
    mutationFn: () =>
      api.triggerEmergency({
        emergency_type: emergencyType,
        detected_lane: emergencyLane,
        priority_level: 5,
        intersection_id: intersectionId,
      }),
    onSuccess: () => {
      setActionError(null);
      void queryClient.invalidateQueries({ queryKey: ['emergency', 'active'] });
    },
    onError: handleError,
  });

  const clearEmergency = useMutation({
    mutationFn: (alertId: string) => api.clearEmergency(alertId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['emergency', 'active'] }),
    onError: handleError,
  });

  const requestCrossing = useMutation({
    mutationFn: (crossing: LaneDirection) =>
      api.requestCrossing({ crossing, pedestrian_count: 1, intersection_id: intersectionId }),
    onSuccess: () => setActionError(null),
    onError: handleError,
  });

  const toggleController = useMutation({
    mutationFn: (running: boolean) =>
      running ? api.stopController(intersectionId) : api.startController(intersectionId),
    onSuccess: () => setActionError(null),
    onError: handleError,
  });

  const isRunning = status?.system_status === 'operational';

  return (
    <div className="space-y-6">
      {actionError && <ErrorNotice message={actionError} />}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Card
          title="Intersection"
          action={
            <button
              type="button"
              className={isRunning ? 'btn-danger' : 'btn-primary'}
              onClick={() => toggleController.mutate(Boolean(isRunning))}
              disabled={toggleController.isPending || !status}
            >
              {isRunning ? <Pause size={15} /> : <Play size={15} />}
              {isRunning ? 'Stop controller' : 'Start controller'}
            </button>
          }
        >
          <IntersectionDiagram status={status} />
        </Card>

        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3">
            <StatTile label="Queued" value={status?.total_vehicles ?? 0} unit="veh" />
            <StatTile
              label="Avg wait"
              value={(status?.average_wait_time ?? 0).toFixed(1)}
              unit="s"
              tone={(status?.average_wait_time ?? 0) > 45 ? 'warning' : 'positive'}
            />
            <StatTile label="Cycles" value={status?.cycles_completed ?? 0} />
            <StatTile
              label="Mode"
              value={status?.adaptive_mode ? 'Adaptive' : 'Fixed'}
              tone={status?.adaptive_mode ? 'positive' : 'default'}
            />
          </div>

          <Card title="Per-approach queues">
            {status ? (
              <ul className="space-y-2">
                {LANES.map((lane) => {
                  const stats = status.lane_statistics[lane];
                  const signal = status.traffic_signals[lane];
                  return (
                    <li
                      key={lane}
                      className="flex items-center justify-between rounded-lg bg-slate-950/50 px-3 py-2"
                    >
                      <span className="flex items-center gap-2 text-sm capitalize">
                        <span
                          className={
                            signal?.current_state === 'green'
                              ? 'h-2 w-2 rounded-full bg-green-500'
                              : signal?.current_state === 'yellow'
                                ? 'h-2 w-2 rounded-full bg-amber-400'
                                : 'h-2 w-2 rounded-full bg-red-500'
                          }
                        />
                        {lane}
                      </span>
                      <span className="flex items-center gap-3 text-sm text-slate-400">
                        <span className="tabular-nums">{stats?.vehicle_count ?? 0} veh</span>
                        <span className="tabular-nums text-slate-500">
                          {(stats?.passenger_car_units ?? 0).toFixed(1)} PCU
                        </span>
                        {stats && <CongestionBadge level={stats.congestion_level} />}
                      </span>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <EmptyState message="No data yet." />
            )}
          </Card>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Submit counts">
          <p className="mb-3 text-xs text-slate-500">
            Feed demand from loops, radar or a simulator without running detection.
          </p>
          <div className="grid grid-cols-2 gap-3">
            {LANES.map((lane) => (
              <label key={lane} className="text-xs text-slate-400 capitalize">
                {lane}
                <input
                  type="number"
                  min={0}
                  max={999}
                  className="field mt-1"
                  value={counts[lane]}
                  placeholder="0"
                  onChange={(event) =>
                    setCounts((previous) => ({ ...previous, [lane]: event.target.value }))
                  }
                />
              </label>
            ))}
          </div>
          <button
            type="button"
            className="btn-primary mt-4 w-full"
            onClick={() => submitCounts.mutate()}
            disabled={submitCounts.isPending}
          >
            <Send size={15} />
            {submitCounts.isPending ? 'Submitting…' : 'Submit counts'}
          </button>
        </Card>

        <Card title="Emergency pre-emption">
          <p className="mb-3 text-xs text-slate-500">
            Grants the chosen approach right of way after a safe yellow and all-red clearance.
          </p>
          <div className="space-y-3">
            <label className="block text-xs text-slate-400">
              Vehicle type
              <select
                className="field mt-1"
                value={emergencyType}
                onChange={(event) => setEmergencyType(event.target.value as EmergencyType)}
              >
                {EMERGENCY_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {type.replaceAll('_', ' ')}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-xs text-slate-400">
              Approach
              <select
                className="field mt-1"
                value={emergencyLane}
                onChange={(event) => setEmergencyLane(event.target.value as LaneDirection)}
              >
                {LANES.map((lane) => (
                  <option key={lane} value={lane}>
                    {lane}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="btn-danger w-full"
              onClick={() => triggerEmergency.mutate()}
              disabled={triggerEmergency.isPending}
            >
              <AlertTriangle size={15} />
              Trigger pre-emption
            </button>
          </div>

          {activeAlerts && activeAlerts.length > 0 && (
            <ul className="mt-4 space-y-2 border-t border-slate-800 pt-3">
              {activeAlerts.map((alert) => (
                <li key={alert.alert_id} className="flex items-center justify-between text-xs">
                  <span className="text-red-300">
                    {alert.emergency_type.replaceAll('_', ' ')} · {alert.detected_lane}
                  </span>
                  <button
                    type="button"
                    className="text-slate-400 underline hover:text-slate-200"
                    onClick={() => clearEmergency.mutate(alert.alert_id)}
                  >
                    clear
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Pedestrian crossing">
          <p className="mb-3 text-xs text-slate-500">
            Served at the next safe boundary, and pre-empts vehicles once the maximum wait is
            reached.
          </p>
          <div className="grid grid-cols-2 gap-2">
            {LANES.map((lane) => (
              <button
                key={lane}
                type="button"
                className="btn-secondary capitalize"
                onClick={() => requestCrossing.mutate(lane)}
                disabled={requestCrossing.isPending}
              >
                <Footprints size={15} />
                {lane}
              </button>
            ))}
          </div>
          <div className="mt-4 rounded-lg bg-slate-950/50 px-3 py-2 text-xs text-slate-400">
            Pending requests:{' '}
            <span className="font-medium text-slate-200">
              {status?.pending_pedestrian_requests ?? 0}
            </span>
          </div>
        </Card>
      </div>

      <Card title="Activity log">
        {events.length === 0 ? (
          <EmptyState message="No events yet. Trigger a detection or a pre-emption to see activity." />
        ) : (
          <ul className="max-h-72 space-y-1.5 overflow-y-auto text-sm">
            {events.map((event) => (
              <li
                key={event.id}
                className="flex items-baseline gap-3 rounded-md px-2 py-1.5 hover:bg-slate-800/40"
              >
                <time className="shrink-0 font-mono text-xs text-slate-500">
                  {new Date(event.timestamp).toLocaleTimeString()}
                </time>
                <span className="shrink-0 rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
                  {event.type}
                </span>
                <span className="text-slate-300">{event.summary}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
