/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the backend API. Empty means same-origin (dev proxy). */
  readonly VITE_API_URL?: string;
  /** Absolute WebSocket URL. Derived from VITE_API_URL when unset. */
  readonly VITE_WS_URL?: string;
  /** Shared API key, sent as `X-API-Key` when the backend requires one. */
  readonly VITE_API_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
