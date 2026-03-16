// Client API base URL (through Next.js rewrite)
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "";

// WebSocket direct connection to backend (bypasses Next.js).
// Runtime detection: derive from window.location so Docker rebuild is not needed
// when hostname changes. Override via NEXT_PUBLIC_WS_URL for custom deployments.
function resolveWsUrl(): string {
  if (typeof window === "undefined") {
    return process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:42001/ws";
  }
  if (process.env.NEXT_PUBLIC_WS_URL) {
    return process.env.NEXT_PUBLIC_WS_URL;
  }
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const port = process.env.NEXT_PUBLIC_BACKEND_PORT || "42001";
  return `${proto}//${window.location.hostname}:${port}/ws`;
}
export const WS_URL = resolveWsUrl();

// Server-side API (Server Component direct connection, Docker internal)
export const BACKEND_INTERNAL_URL = process.env.BACKEND_INTERNAL_URL || "http://localhost:42001";
