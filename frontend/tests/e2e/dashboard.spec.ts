import { expect, test } from '@playwright/test';

/**
 * End-to-end coverage of the operator dashboard.
 *
 * These specs stub the backend at the network layer so they exercise the real
 * UI without needing a model, a GPU or a database. Run them against a live
 * backend instead by setting `E2E_BASE_URL`.
 */

const INTERSECTION_STATUS = {
  intersection_id: 'main_intersection',
  name: 'Main Intersection',
  current_phase: 'north_south_green',
  phase_elapsed_seconds: 4,
  traffic_signals: {
    north: {
      signal_id: 'main_north',
      direction: 'north',
      current_state: 'green',
      remaining_time: 22,
      next_state: null,
      cycle_duration: 30,
      last_updated: '2026-01-01T00:00:00Z',
    },
    south: {
      signal_id: 'main_south',
      direction: 'south',
      current_state: 'green',
      remaining_time: 22,
      next_state: null,
      cycle_duration: 30,
      last_updated: '2026-01-01T00:00:00Z',
    },
    east: {
      signal_id: 'main_east',
      direction: 'east',
      current_state: 'red',
      remaining_time: 22,
      next_state: null,
      cycle_duration: 30,
      last_updated: '2026-01-01T00:00:00Z',
    },
    west: {
      signal_id: 'main_west',
      direction: 'west',
      current_state: 'red',
      remaining_time: 22,
      next_state: null,
      cycle_duration: 30,
      last_updated: '2026-01-01T00:00:00Z',
    },
  },
  vehicle_counts: { north: 7, south: 2, east: 3, west: 1 },
  lane_statistics: {
    north: {
      lane: 'north',
      vehicle_count: 7,
      passenger_car_units: 8.5,
      average_speed_kph: null,
      emergency_vehicles: 0,
      pedestrians_waiting: 0,
      congestion_level: 'moderate',
    },
  },
  total_vehicles: 13,
  average_wait_time: 18.4,
  cycles_completed: 5,
  emergency_mode_active: false,
  pedestrian_phase_active: false,
  pending_pedestrian_requests: 0,
  adaptive_mode: true,
  system_status: 'operational',
  last_detection_time: null,
  last_updated: '2026-01-01T00:00:00Z',
  green_direction: ['north', 'south'],
  congestion_level: 'moderate',
};

test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/intersections/main_intersection', (route) =>
    route.fulfill({ json: INTERSECTION_STATUS }),
  );
  await page.route('**/api/v1/intersections', (route) =>
    route.fulfill({
      json: [
        {
          intersection_id: 'main_intersection',
          name: 'Main Intersection',
          current_phase: 'north_south_green',
          total_vehicles: 13,
          congestion_level: 'moderate',
          emergency_mode_active: false,
          last_updated: '2026-01-01T00:00:00Z',
        },
      ],
    }),
  );
  await page.route('**/api/v1/emergency/active', (route) => route.fulfill({ json: [] }));
  await page.route('**/health', (route) =>
    route.fulfill({
      json: {
        status: 'healthy',
        version: '3.0.0',
        environment: 'testing',
        timestamp: '2026-01-01T00:00:00Z',
        uptime_seconds: 120,
        health_score: 1,
        services: [{ name: 'vehicle_detector', ready: true, detail: null }],
        system: {},
        websocket_connections: 1,
      },
    }),
  );
});

test.describe('Operator dashboard', () => {
  test('renders the live control screen', async ({ page }) => {
    await page.goto('/');

    await expect(page.getByRole('heading', { name: /ai traffic management/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /live control/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /submit counts/i })).toBeVisible();
  });

  test('navigates between every section', async ({ page }) => {
    await page.goto('/');

    // Scoped to the nav landmark: section names also appear on page content
    // ("Corridor" the tab vs "Add to corridor" the button).
    const nav = page.getByRole('navigation', { name: /sections/i });

    for (const section of ['Detection', 'Insights', 'Corridor', 'System']) {
      const tab = nav.getByRole('button', { name: section, exact: true });
      await tab.click();
      await expect(tab).toHaveAttribute('aria-current', 'page');
    }
  });

  test('offers upload controls on the detection screen', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: /detection/i }).click();

    await expect(page.getByText(/drop an intersection photo/i)).toBeVisible();
    await expect(page.getByRole('button', { name: /choose image/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /choose video/i })).toBeVisible();
  });

  test('submits manual counts to the API', async ({ page }) => {
    let submitted: unknown = null;
    await page.route('**/api/v1/intersections/main_intersection/counts', async (route) => {
      submitted = route.request().postDataJSON();
      await route.fulfill({ json: INTERSECTION_STATUS });
    });

    await page.goto('/');
    await page.getByLabel('north', { exact: true }).fill('9');
    await page.getByRole('button', { name: /submit counts/i }).click();

    await expect.poll(() => submitted).not.toBeNull();
    expect(submitted).toMatchObject({ counts: { north: 9 } });
  });

  test('sends an emergency pre-emption request', async ({ page }) => {
    let body: unknown = null;
    await page.route('**/api/v1/emergency/override', async (route) => {
      body = route.request().postDataJSON();
      await route.fulfill({
        json: {
          alert_id: 'emg_test',
          emergency_type: 'ambulance',
          detected_lane: 'north',
          priority_level: 5,
          override_duration: 45,
          intersection_id: 'main_intersection',
          is_active: true,
          created_at: '2026-01-01T00:00:00Z',
          resolved_at: null,
        },
      });
    });

    await page.goto('/');
    await page.getByRole('button', { name: /trigger pre-emption/i }).click();

    await expect.poll(() => body).not.toBeNull();
    expect(body).toMatchObject({ emergency_type: 'ambulance', detected_lane: 'north' });
  });

  test('surfaces API failures without breaking the page', async ({ page }) => {
    await page.route('**/api/v1/intersections/main_intersection/counts', (route) =>
      route.fulfill({
        status: 503,
        json: { detail: 'Traffic controller unavailable', request_id: 'req_123' },
      }),
    );

    await page.goto('/');
    await page.getByRole('button', { name: /submit counts/i }).click();

    await expect(page.getByRole('alert')).toContainText('Traffic controller unavailable');
    await expect(page.getByRole('alert')).toContainText('req_123');
    // The dashboard must stay usable after a failed action.
    await expect(page.getByRole('button', { name: /submit counts/i })).toBeEnabled();
  });

  test('is usable at a mobile viewport', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto('/');

    await expect(page.getByRole('heading', { name: /ai traffic management/i })).toBeVisible();

    // The page must not scroll sideways on a phone.
    const overflows = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    );
    expect(overflows).toBe(false);
  });
});
