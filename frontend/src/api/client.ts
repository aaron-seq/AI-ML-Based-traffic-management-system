/**
 * Typed HTTP client for the traffic management API.
 *
 * Uses `fetch` rather than a client library: the surface is small, and one
 * dependency fewer matters for a dashboard that may run on a control-room
 * machine with a locked-down network.
 */

import type {
  AnalyticsSummary,
  CoordinationPlan,
  DetectionResult,
  EmergencyAlert,
  EmergencyType,
  HealthStatus,
  IntersectionStatus,
  IntersectionSummary,
  LaneDirection,
  PedestrianRequest,
  SystemInfo,
  TrafficForecast,
  ImpactEstimate,
  VideoAnalysisResult,
} from './types';

/** Base URL of the API. Empty means same-origin, which the dev proxy handles. */
export const API_BASE: string = import.meta.env.VITE_API_URL ?? '';

/** Optional shared API key, sent as `X-API-Key` when configured. */
const API_KEY: string | undefined = import.meta.env.VITE_API_KEY;

const API_PREFIX = '/api/v1';

/** An error carrying the HTTP status and the server's `request_id`. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly requestId?: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

function buildHeaders(extra?: HeadersInit): Headers {
  const headers = new Headers(extra);
  if (API_KEY) headers.set('X-API-Key', API_KEY);
  return headers;
}

async function parseError(response: Response): Promise<never> {
  let detail = `${response.status} ${response.statusText}`;
  let requestId: string | undefined;

  try {
    const body = (await response.json()) as { detail?: unknown; request_id?: string };
    requestId = body.request_id;
    if (typeof body.detail === 'string') {
      detail = body.detail;
    } else if (Array.isArray(body.detail)) {
      // FastAPI validation errors arrive as a list of issues.
      detail = body.detail
        .map((issue) => (issue as { msg?: string }).msg ?? JSON.stringify(issue))
        .join('; ');
    }
  } catch {
    // Non-JSON error body (a proxy error page, say): keep the status line.
  }

  throw new ApiError(detail, response.status, requestId);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: buildHeaders(init?.headers),
  });

  if (!response.ok) await parseError(response);
  if (response.status === 204) return undefined as T;

  return (await response.json()) as T;
}

function query(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, String(value));
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : '';
}

export const api = {
  // --- system ---------------------------------------------------------------
  health: () => request<HealthStatus>('/health'),
  systemInfo: () => request<SystemInfo>(`${API_PREFIX}/system/info`),
  configurationReport: () =>
    request<{ valid: boolean; problems: string[]; environment: string }>(
      `${API_PREFIX}/system/configuration`,
    ),

  // --- intersections --------------------------------------------------------
  listIntersections: () => request<IntersectionSummary[]>(`${API_PREFIX}/intersections`),

  intersectionStatus: (id: string) =>
    request<IntersectionStatus>(`${API_PREFIX}/intersections/${encodeURIComponent(id)}`),

  createIntersection: (body: {
    intersection_id: string;
    name: string;
    distance_from_previous_metres?: number;
  }) =>
    request<IntersectionSummary>(`${API_PREFIX}/intersections`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),

  submitCounts: (id: string, counts: Partial<Record<LaneDirection, number>>) =>
    request<IntersectionStatus>(
      `${API_PREFIX}/intersections/${encodeURIComponent(id)}/counts`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ counts, intersection_id: id }),
      },
    ),

  updatePlan: (id: string, plan: Record<string, number | boolean>) =>
    request<{ applied: Record<string, unknown>; current_plan: Record<string, number | boolean> }>(
      `${API_PREFIX}/intersections/${encodeURIComponent(id)}/plan`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(plan),
      },
    ),

  startController: (id: string) =>
    request<{ running: boolean }>(`${API_PREFIX}/intersections/${encodeURIComponent(id)}/start`, {
      method: 'POST',
    }),

  stopController: (id: string) =>
    request<{ running: boolean }>(`${API_PREFIX}/intersections/${encodeURIComponent(id)}/stop`, {
      method: 'POST',
    }),

  coordinationPlan: (designSpeedKph?: number) =>
    request<CoordinationPlan>(
      `${API_PREFIX}/intersections/coordination${query({ design_speed_kph: designSpeedKph })}`,
    ),

  // --- detection ------------------------------------------------------------
  detectImage: (
    file: File,
    options: { intersectionId?: string; confidence?: number; updateSignals?: boolean } = {},
  ) => {
    const form = new FormData();
    form.append('image', file);
    return request<DetectionResult>(
      `${API_PREFIX}/detection/image${query({
        intersection_id: options.intersectionId,
        confidence: options.confidence,
        update_signals: options.updateSignals,
      })}`,
      { method: 'POST', body: form },
    );
  },

  detectVideo: (
    file: File,
    options: { intersectionId?: string; frameStride?: number; metresPerPixel?: number } = {},
  ) => {
    const form = new FormData();
    form.append('video', file);
    return request<VideoAnalysisResult>(
      `${API_PREFIX}/detection/video${query({
        intersection_id: options.intersectionId,
        frame_stride: options.frameStride,
        metres_per_pixel: options.metresPerPixel,
      })}`,
      { method: 'POST', body: form },
    );
  },

  detectionPerformance: () =>
    request<Record<string, string | number | null>>(`${API_PREFIX}/detection/performance`),

  // --- emergency ------------------------------------------------------------
  triggerEmergency: (body: {
    emergency_type: EmergencyType;
    detected_lane: LaneDirection;
    priority_level?: number;
    intersection_id?: string;
  }) =>
    request<EmergencyAlert>(`${API_PREFIX}/emergency/override`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),

  activeEmergencies: () => request<EmergencyAlert[]>(`${API_PREFIX}/emergency/active`),

  clearEmergency: (alertId: string) =>
    request<{ cleared: boolean }>(
      `${API_PREFIX}/emergency/override/${encodeURIComponent(alertId)}`,
      { method: 'DELETE' },
    ),

  // --- pedestrians ----------------------------------------------------------
  requestCrossing: (body: {
    crossing: LaneDirection;
    pedestrian_count?: number;
    accessibility_extension?: boolean;
    intersection_id?: string;
  }) =>
    request<PedestrianRequest>(`${API_PREFIX}/pedestrians/request`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),

  pendingCrossings: () => request<PedestrianRequest[]>(`${API_PREFIX}/pedestrians/pending`),

  // --- analytics ------------------------------------------------------------
  analyticsSummary: (period: 'current' | 'hourly' | 'daily' = 'current') =>
    request<AnalyticsSummary>(`${API_PREFIX}/analytics/summary${query({ period })}`),

  analyticsHistory: (hours = 24, limit = 200) =>
    request<{ source: string; count: number; records: Array<Record<string, unknown>> }>(
      `${API_PREFIX}/analytics/history${query({ hours, limit })}`,
    ),

  forecast: (id: string) =>
    request<TrafficForecast>(`${API_PREFIX}/forecast/${encodeURIComponent(id)}`),

  impact: (id: string) => request<ImpactEstimate>(`${API_PREFIX}/impact/${encodeURIComponent(id)}`),

  cumulativeImpact: (id: string) =>
    request<{
      cumulative: Record<string, number>;
      projection: Record<string, string | number | boolean>;
    }>(`${API_PREFIX}/impact/${encodeURIComponent(id)}/cumulative`),
};

/** Absolute URL of the live-updates WebSocket. */
export function websocketUrl(): string {
  const configured = import.meta.env.VITE_WS_URL;
  if (configured) return configured;

  const base = API_BASE || window.location.origin;
  const url = new URL(base);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.pathname = '/ws/traffic-updates';
  if (API_KEY) url.searchParams.set('token', API_KEY);
  return url.toString();
}
