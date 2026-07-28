import { useCallback, useEffect, useRef, useState } from 'react';
import { websocketUrl } from '../api/client';
import type { IntersectionStatus, WebSocketEnvelope } from '../api/types';

export type ConnectionState = 'connecting' | 'open' | 'closed';

export interface TrafficEvent {
  id: number;
  type: string;
  timestamp: string;
  summary: string;
}

/** Events worth showing in the activity log; status spam is filtered out. */
const NOTABLE_EVENT_TYPES = new Set([
  'emergency_alert',
  'emergency_cleared',
  'pedestrian_request',
  'pedestrian_served',
  'vehicle_detection',
  'video_analysis',
  'cycle_completed',
  'phase_change',
]);

const MAX_EVENTS = 40;
const MAX_RECONNECT_DELAY_MS = 15_000;

function summarise(envelope: WebSocketEnvelope): string {
  const data = (envelope.data ?? {}) as Record<string, unknown>;

  switch (envelope.type) {
    case 'emergency_alert':
      return `${String(data.emergency_type ?? 'emergency')} pre-empting ${String(data.detected_lane ?? '?')}`;
    case 'emergency_cleared':
      return `Pre-emption ${String(data.alert_id ?? '')} cleared`;
    case 'pedestrian_request':
      return `${String(data.pedestrian_count ?? 1)} waiting to cross ${String(data.crossing ?? '?')}`;
    case 'pedestrian_served':
      return 'Pedestrian phase served';
    case 'vehicle_detection':
      return `${String(data.total_vehicles ?? 0)} vehicles detected`;
    case 'video_analysis':
      return `${String(data.unique_vehicles ?? 0)} unique vehicles tracked`;
    case 'cycle_completed':
      return `Cycle ${String(data.cycles_completed ?? '')} completed`;
    case 'phase_change':
      return `Phase -> ${String(data.phase ?? '?')} (${String(data.duration_seconds ?? '?')}s)`;
    default:
      return envelope.type;
  }
}

/**
 * Subscribes to the live traffic feed.
 *
 * Reconnects with exponential backoff so a backend restart or a brief network
 * blip heals on its own instead of leaving a control-room display frozen on
 * stale state. The whole connection lifecycle lives inside a single effect,
 * which keeps every mutable handle scoped to that effect's cleanup.
 */
export function useTrafficSocket() {
  const [connectionState, setConnectionState] = useState<ConnectionState>('connecting');
  const [statuses, setStatuses] = useState<Record<string, IntersectionStatus>>({});
  const [events, setEvents] = useState<TrafficEvent[]>([]);
  const [lastMessageAt, setLastMessageAt] = useState<string | null>(null);

  const eventIdRef = useRef(0);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let reconnectTimer: number | undefined;
    let attempts = 0;
    let disposed = false;

    const handleMessage = (raw: string) => {
      let envelope: WebSocketEnvelope;
      try {
        envelope = JSON.parse(raw) as WebSocketEnvelope;
      } catch {
        return;
      }

      setLastMessageAt(envelope.timestamp);

      if (envelope.type === 'intersection_status' || envelope.type === 'counts_updated') {
        const status = envelope.data as IntersectionStatus;
        if (status?.intersection_id) {
          setStatuses((previous) => ({ ...previous, [status.intersection_id]: status }));
        }
        return;
      }

      if (NOTABLE_EVENT_TYPES.has(envelope.type)) {
        eventIdRef.current += 1;
        const entry: TrafficEvent = {
          id: eventIdRef.current,
          type: envelope.type,
          timestamp: envelope.timestamp,
          summary: summarise(envelope),
        };
        setEvents((previous) => [entry, ...previous].slice(0, MAX_EVENTS));
      }
    };

    const connect = () => {
      if (disposed) return;
      setConnectionState('connecting');

      try {
        socket = new WebSocket(websocketUrl());
      } catch {
        // A malformed URL should not take the dashboard down; keep retrying.
        setConnectionState('closed');
        return;
      }

      socket.onopen = () => {
        attempts = 0;
        setConnectionState('open');
      };

      socket.onmessage = (message: MessageEvent<string>) => handleMessage(message.data);

      socket.onclose = () => {
        setConnectionState('closed');
        if (disposed) return;
        attempts += 1;
        const delay = Math.min(500 * 2 ** attempts, MAX_RECONNECT_DELAY_MS);
        reconnectTimer = window.setTimeout(connect, delay);
      };

      // An error is always followed by a close event, which owns the retry.
      socket.onerror = () => socket?.close();
    };

    connect();

    return () => {
      disposed = true;
      if (reconnectTimer !== undefined) window.clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, []);

  const clearEvents = useCallback(() => setEvents([]), []);

  return { connectionState, statuses, events, lastMessageAt, clearEvents };
}
