import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError, api, websocketUrl } from './client';

function mockFetch(response: Partial<Response> & { json?: () => Promise<unknown> }) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    statusText: 'OK',
    json: async () => ({}),
    ...response,
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe('api client', () => {
  it('requests the versioned path for intersection status', async () => {
    const fetchMock = mockFetch({ json: async () => ({ intersection_id: 'main' }) });

    await api.intersectionStatus('main');

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/intersections/main');
  });

  it('percent-encodes intersection ids so they cannot alter the path', async () => {
    const fetchMock = mockFetch({});

    await api.intersectionStatus('a/../b');

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/intersections/a%2F..%2Fb');
  });

  it('surfaces the server detail and request id on failure', async () => {
    mockFetch({
      ok: false,
      status: 503,
      statusText: 'Service Unavailable',
      json: async () => ({ detail: 'Detector still loading', request_id: 'abc123' }),
    });

    await expect(api.health()).rejects.toMatchObject({
      name: 'ApiError',
      status: 503,
      message: 'Detector still loading',
      requestId: 'abc123',
    });
  });

  it('joins FastAPI validation issues into one message', async () => {
    mockFetch({
      ok: false,
      status: 422,
      statusText: 'Unprocessable Entity',
      json: async () => ({ detail: [{ msg: 'field required' }, { msg: 'must be positive' }] }),
    });

    await expect(api.health()).rejects.toThrow('field required; must be positive');
  });

  it('falls back to the status line when the error body is not JSON', async () => {
    mockFetch({
      ok: false,
      status: 502,
      statusText: 'Bad Gateway',
      json: async () => {
        throw new Error('not json');
      },
    });

    await expect(api.health()).rejects.toBeInstanceOf(ApiError);
    await expect(api.health()).rejects.toThrow('502 Bad Gateway');
  });

  it('omits empty query parameters', async () => {
    const fetchMock = mockFetch({});

    await api.coordinationPlan();
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/intersections/coordination');

    await api.coordinationPlan(60);
    expect(fetchMock.mock.calls[1]?.[0]).toBe(
      '/api/v1/intersections/coordination?design_speed_kph=60',
    );
  });
});

describe('websocketUrl', () => {
  it('upgrades http to ws against the current origin', () => {
    expect(websocketUrl()).toMatch(/^ws:\/\/localhost(:\d+)?\/ws\/traffic-updates$/);
  });
});
