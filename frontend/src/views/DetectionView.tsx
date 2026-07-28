import { useCallback, useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Film, ImageUp, Loader2 } from 'lucide-react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { API_BASE, api, ApiError } from '../api/client';
import type { DetectionResult, VideoAnalysisResult } from '../api/types';
import { Card, EmptyState, ErrorNotice, StatTile } from '../components/common';

const LANE_COLOURS = ['#38bdf8', '#34d399', '#fbbf24', '#f472b6'];

/** Serves the annotated image the backend wrote to ./output_images. */
function annotatedImageUrl(path: string | null): string | null {
  if (!path) return null;
  const filename = path.split('/').pop();
  return filename ? `${API_BASE}/static/${filename}` : null;
}

export function DetectionView({ intersectionId }: { intersectionId: string }) {
  const [imageResult, setImageResult] = useState<DetectionResult | null>(null);
  const [videoResult, setVideoResult] = useState<VideoAnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  const imageInputRef = useRef<HTMLInputElement>(null);
  const videoInputRef = useRef<HTMLInputElement>(null);

  const describeError = (cause: unknown) =>
    setError(
      cause instanceof ApiError
        ? `${cause.message}${cause.requestId ? ` (request ${cause.requestId})` : ''}`
        : String(cause),
    );

  const analyseImage = useMutation({
    mutationFn: (file: File) => api.detectImage(file, { intersectionId }),
    onSuccess: (result) => {
      setImageResult(result);
      setError(null);
    },
    onError: describeError,
  });

  const analyseVideo = useMutation({
    mutationFn: (file: File) => api.detectVideo(file, { intersectionId }),
    onSuccess: (result) => {
      setVideoResult(result);
      setError(null);
    },
    onError: describeError,
  });

  const onDrop = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      setIsDragging(false);
      const file = event.dataTransfer.files[0];
      if (!file) return;
      if (file.type.startsWith('video/')) analyseVideo.mutate(file);
      else analyseImage.mutate(file);
    },
    [analyseImage, analyseVideo],
  );

  const laneChartData = imageResult
    ? Object.entries(imageResult.lane_counts)
        .filter(([lane]) => lane !== 'unknown')
        .map(([lane, count]) => ({ lane, count: count ?? 0 }))
    : [];

  const busy = analyseImage.isPending || analyseVideo.isPending;

  return (
    <div className="space-y-6">
      {error && <ErrorNotice message={error} />}

      <Card title="Analyse footage">
        <div
          onDragOver={(event) => {
            event.preventDefault();
            setIsDragging(true);
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={onDrop}
          className={`rounded-xl border-2 border-dashed p-10 text-center transition-colors ${
            isDragging ? 'border-sky-500 bg-sky-500/5' : 'border-slate-700'
          }`}
        >
          {busy ? (
            <div className="flex flex-col items-center gap-2 text-slate-300">
              <Loader2 className="animate-spin" size={28} />
              <p className="text-sm">
                {analyseVideo.isPending
                  ? 'Tracking vehicles across frames…'
                  : 'Running detection…'}
              </p>
            </div>
          ) : (
            <>
              <p className="text-sm text-slate-300">
                Drop an intersection photo or a video clip here
              </p>
              <p className="mt-1 text-xs text-slate-500">
                JPEG, PNG, WebP · MP4, MOV, AVI, WebM
              </p>
              <div className="mt-4 flex justify-center gap-3">
                <button
                  type="button"
                  className="btn-primary"
                  onClick={() => imageInputRef.current?.click()}
                >
                  <ImageUp size={15} /> Choose image
                </button>
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => videoInputRef.current?.click()}
                >
                  <Film size={15} /> Choose video
                </button>
              </div>
            </>
          )}

          <input
            ref={imageInputRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) analyseImage.mutate(file);
              event.target.value = '';
            }}
          />
          <input
            ref={videoInputRef}
            type="file"
            accept="video/*"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) analyseVideo.mutate(file);
              event.target.value = '';
            }}
          />
        </div>
      </Card>

      {imageResult && (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <StatTile label="Vehicles" value={imageResult.total_vehicles} />
            <StatTile label="Pedestrians" value={imageResult.pedestrian_count} />
            <StatTile
              label="Capacity units"
              value={imageResult.total_passenger_car_units.toFixed(1)}
              unit="PCU"
              hint="Weighted by vehicle size"
            />
            <StatTile label="Busiest" value={imageResult.busiest_lane ?? '—'} />
            <StatTile
              label="Inference"
              value={(imageResult.processing_time * 1000).toFixed(0)}
              unit="ms"
            />
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card title="Annotated frame">
              {annotatedImageUrl(imageResult.annotated_image_path) ? (
                <img
                  src={annotatedImageUrl(imageResult.annotated_image_path) ?? ''}
                  alt={`Detection output showing ${imageResult.total_vehicles} vehicles`}
                  className="w-full rounded-lg border border-slate-800"
                />
              ) : (
                <EmptyState message="No annotated image was produced for this run." />
              )}
            </Card>

            <Card title="Vehicles per approach">
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={laneChartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                    <XAxis dataKey="lane" stroke="#64748b" fontSize={12} />
                    <YAxis stroke="#64748b" fontSize={12} allowDecimals={false} />
                    <Tooltip
                      contentStyle={{
                        background: '#0f172a',
                        border: '1px solid #1e293b',
                        borderRadius: 8,
                      }}
                    />
                    <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                      {laneChartData.map((entry, index) => (
                        <Cell
                          key={entry.lane}
                          fill={LANE_COLOURS[index % LANE_COLOURS.length] ?? '#38bdf8'}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
          </div>

          <Card title={`Detections (${imageResult.detected_vehicles.length})`}>
            <div className="max-h-80 overflow-auto">
              <table className="w-full text-left text-sm">
                <thead className="sticky top-0 bg-slate-900 text-xs text-slate-500 uppercase">
                  <tr>
                    <th className="py-2 pr-4 font-medium">Type</th>
                    <th className="py-2 pr-4 font-medium">Approach</th>
                    <th className="py-2 pr-4 font-medium">Confidence</th>
                    <th className="py-2 pr-4 font-medium">PCU</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {imageResult.detected_vehicles.map((vehicle, index) => (
                    <tr key={`${vehicle.vehicle_type}-${index}`}>
                      <td className="py-1.5 pr-4 capitalize">{vehicle.vehicle_type}</td>
                      <td className="py-1.5 pr-4 text-slate-400 capitalize">{vehicle.lane}</td>
                      <td className="py-1.5 pr-4 text-slate-400 tabular-nums">
                        {(vehicle.confidence * 100).toFixed(0)}%
                      </td>
                      <td className="py-1.5 pr-4 text-slate-400 tabular-nums">
                        {vehicle.passenger_car_units.toFixed(1)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}

      {videoResult && (
        <Card title="Video analysis">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile
              label="Unique vehicles"
              value={videoResult.unique_vehicles}
              hint="Tracked identities, not per-frame boxes"
            />
            <StatTile label="Frames analysed" value={videoResult.frames_analysed} />
            <StatTile
              label="Flow rate"
              value={videoResult.flow_rate_vehicles_per_hour?.toFixed(0) ?? '—'}
              unit={videoResult.flow_rate_vehicles_per_hour !== null ? 'veh/h' : undefined}
              hint={videoResult.flow_rate_vehicles_per_hour === null ? 'Clip too short' : undefined}
            />
            <StatTile
              label="Mean speed"
              value={videoResult.average_speed_kph?.toFixed(1) ?? '—'}
              unit={videoResult.average_speed_kph ? 'km/h' : undefined}
              hint={videoResult.average_speed_kph ? undefined : 'Needs metres_per_pixel'}
            />
          </div>

          <div className="mt-4 flex flex-wrap gap-2">
            {Object.entries(videoResult.vehicle_type_breakdown).map(([type, count]) => (
              <span key={type} className="badge bg-slate-800 text-slate-300">
                {type}: {count}
              </span>
            ))}
          </div>

          {videoResult.sampling_note && (
            <p className="mt-3 text-xs text-amber-400/90">{videoResult.sampling_note}</p>
          )}
        </Card>
      )}
    </div>
  );
}
