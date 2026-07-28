import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { IntersectionDiagram } from './IntersectionDiagram';
import type { IntersectionStatus, LaneDirection, SignalState } from '../api/types';

function buildStatus(overrides: Partial<IntersectionStatus> = {}): IntersectionStatus {
  const signal = (direction: LaneDirection, state: SignalState) => ({
    signal_id: `main_${direction}`,
    direction,
    current_state: state,
    remaining_time: 20,
    next_state: null,
    cycle_duration: 30,
    last_updated: '2026-01-01T00:00:00Z',
  });

  return {
    intersection_id: 'main_intersection',
    name: 'Main Intersection',
    current_phase: 'north_south_green',
    phase_elapsed_seconds: 5,
    traffic_signals: {
      north: signal('north', 'green'),
      south: signal('south', 'green'),
      east: signal('east', 'red'),
      west: signal('west', 'red'),
    },
    vehicle_counts: { north: 6, south: 2, east: 1, west: 0 },
    lane_statistics: {},
    total_vehicles: 9,
    average_wait_time: 12.5,
    cycles_completed: 3,
    emergency_mode_active: false,
    pedestrian_phase_active: false,
    pending_pedestrian_requests: 0,
    adaptive_mode: true,
    system_status: 'operational',
    last_detection_time: null,
    last_updated: '2026-01-01T00:00:00Z',
    green_direction: ['north', 'south'],
    congestion_level: 'moderate',
    ...overrides,
  };
}

describe('IntersectionDiagram', () => {
  it('prompts for data when no status has arrived', () => {
    render(<IntersectionDiagram status={null} />);
    expect(screen.getByText(/waiting for the first status update/i)).toBeInTheDocument();
  });

  it('renders every approach with an accessible state description', () => {
    render(<IntersectionDiagram status={buildStatus()} />);

    // Signal colour alone is not accessible, so each head carries a text label.
    expect(
      screen.getByLabelText(/north approach: green, 20 seconds remaining, 6 vehicles queued/i),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/east approach: red/i)).toBeInTheDocument();
  });

  it('summarises queue, wait and cycle counters', () => {
    render(<IntersectionDiagram status={buildStatus()} />);

    expect(screen.getByText('north south green')).toBeInTheDocument();
    expect(screen.getByText('9')).toBeInTheDocument();
    expect(screen.getByText('12.5s')).toBeInTheDocument();
  });

  it('shows the pre-emption banner only while an emergency is active', () => {
    const { rerender } = render(<IntersectionDiagram status={buildStatus()} />);
    expect(screen.queryByText(/emergency pre-emption active/i)).not.toBeInTheDocument();

    rerender(<IntersectionDiagram status={buildStatus({ emergency_mode_active: true })} />);
    expect(screen.getByText(/emergency pre-emption active/i)).toBeInTheDocument();
  });

  it('shows the pedestrian banner, and lets emergency take precedence', () => {
    const { rerender } = render(
      <IntersectionDiagram status={buildStatus({ pedestrian_phase_active: true })} />,
    );
    expect(screen.getByText(/pedestrian crossing phase/i)).toBeInTheDocument();

    rerender(
      <IntersectionDiagram
        status={buildStatus({ pedestrian_phase_active: true, emergency_mode_active: true })}
      />,
    );
    expect(screen.queryByText(/pedestrian crossing phase/i)).not.toBeInTheDocument();
    expect(screen.getByText(/emergency pre-emption active/i)).toBeInTheDocument();
  });
});
