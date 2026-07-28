import '@testing-library/jest-dom/vitest';
import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// jsdom implements neither of these, and Recharts' ResponsiveContainer and the
// live-feed hook both reach for them during render.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
};

if (!('WebSocket' in globalThis)) {
  globalThis.WebSocket = class {
    static readonly OPEN = 1;
    readonly readyState = 1;
    onopen: (() => void) | null = null;
    onclose: (() => void) | null = null;
    onerror: (() => void) | null = null;
    onmessage: ((event: { data: string }) => void) | null = null;
    close() {}
    send() {}
  } as unknown as typeof WebSocket;
}
