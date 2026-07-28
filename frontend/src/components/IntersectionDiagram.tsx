import clsx from 'clsx';
import type { IntersectionStatus, LaneDirection, SignalState } from '../api/types';

const APPROACHES: LaneDirection[] = ['north', 'south', 'east', 'west'];

const LAMP_COLOURS: Record<SignalState, string> = {
  red: 'bg-red-500 shadow-red-500/50',
  yellow: 'bg-amber-400 shadow-amber-400/50',
  green: 'bg-green-500 shadow-green-500/50',
  flashing_red: 'bg-red-500 shadow-red-500/50 animate-pulse',
  flashing_yellow: 'bg-amber-400 shadow-amber-400/50 animate-pulse',
  off: 'bg-slate-700',
};

/** Where each approach's signal head sits around the junction. */
const HEAD_POSITION: Record<LaneDirection, string> = {
  north: 'top-2 left-1/2 -translate-x-1/2',
  south: 'bottom-2 left-1/2 -translate-x-1/2',
  east: 'right-2 top-1/2 -translate-y-1/2',
  west: 'left-2 top-1/2 -translate-y-1/2',
  unknown: 'hidden',
};

interface SignalHeadProps {
  direction: LaneDirection;
  state: SignalState;
  remainingSeconds: number;
  vehicleCount: number;
}

function SignalHead({ direction, state, remainingSeconds, vehicleCount }: SignalHeadProps) {
  const horizontal = direction === 'east' || direction === 'west';

  return (
    <div
      className={clsx('absolute flex items-center gap-2', HEAD_POSITION[direction])}
      // The lamp colours alone would exclude colour-blind users, so state is
      // also announced in text.
      aria-label={`${direction} approach: ${state.replace('_', ' ')}, ${remainingSeconds} seconds remaining, ${vehicleCount} vehicles queued`}
    >
      <div
        className={clsx(
          'flex gap-1 rounded-md border border-slate-700 bg-slate-950 p-1.5',
          horizontal ? 'flex-row' : 'flex-col',
        )}
      >
        {(['red', 'yellow', 'green'] as const).map((lamp) => {
          const lit = state === lamp || state === `flashing_${lamp}`;
          return (
            <span
              key={lamp}
              className={clsx(
                'h-3 w-3 rounded-full transition-all',
                lit ? `${LAMP_COLOURS[state]} shadow-md` : 'bg-slate-800',
              )}
            />
          );
        })}
      </div>
      <div className="text-xs leading-tight">
        <div className="font-semibold text-slate-200 capitalize">{direction}</div>
        <div className="text-slate-400 tabular-nums">
          {remainingSeconds}s · {vehicleCount} veh
        </div>
      </div>
    </div>
  );
}

interface IntersectionDiagramProps {
  status: IntersectionStatus | null;
}

/**
 * Schematic plan view of one intersection: four signal heads, live aspects,
 * queue lengths, and a banner when a pre-emption or pedestrian phase is active.
 */
export function IntersectionDiagram({ status }: IntersectionDiagramProps) {
  if (!status) {
    return (
      <div className="flex h-80 items-center justify-center rounded-xl border border-dashed border-slate-700 text-sm text-slate-500">
        Waiting for the first status update…
      </div>
    );
  }

  return (
    <div>
      <div className="relative h-80 overflow-hidden rounded-xl border border-slate-800 bg-slate-950">
        {/* Carriageways */}
        <div className="absolute top-0 left-1/2 h-full w-24 -translate-x-1/2 bg-slate-800/70" />
        <div className="absolute top-1/2 left-0 h-24 w-full -translate-y-1/2 bg-slate-800/70" />

        {/* Lane markings */}
        <div className="absolute top-0 left-1/2 h-full w-px -translate-x-1/2 border-l-2 border-dashed border-slate-600/60" />
        <div className="absolute top-1/2 left-0 h-px w-full -translate-y-1/2 border-t-2 border-dashed border-slate-600/60" />

        {/* Junction box */}
        <div className="absolute top-1/2 left-1/2 h-24 w-24 -translate-x-1/2 -translate-y-1/2 rounded-sm bg-slate-700/70" />

        {APPROACHES.map((direction) => {
          const signal = status.traffic_signals[direction];
          return (
            <SignalHead
              key={direction}
              direction={direction}
              state={signal?.current_state ?? 'off'}
              remainingSeconds={signal?.remaining_time ?? 0}
              vehicleCount={status.vehicle_counts[direction] ?? 0}
            />
          );
        })}

        {status.emergency_mode_active && (
          <div className="absolute inset-x-0 top-0 bg-red-600/90 py-1.5 text-center text-xs font-semibold tracking-wide text-white uppercase">
            Emergency pre-emption active
          </div>
        )}

        {status.pedestrian_phase_active && !status.emergency_mode_active && (
          <div className="absolute inset-x-0 top-0 bg-sky-600/90 py-1.5 text-center text-xs font-semibold tracking-wide text-white uppercase">
            Pedestrian crossing phase
          </div>
        )}
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-xs text-slate-500">Phase</dt>
          <dd className="font-medium text-slate-200">{status.current_phase.replaceAll('_', ' ')}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Queued</dt>
          <dd className="font-medium text-slate-200 tabular-nums">{status.total_vehicles}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Avg wait</dt>
          <dd className="font-medium text-slate-200 tabular-nums">
            {status.average_wait_time.toFixed(1)}s
          </dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Cycles</dt>
          <dd className="font-medium text-slate-200 tabular-nums">{status.cycles_completed}</dd>
        </div>
      </dl>
    </div>
  );
}
