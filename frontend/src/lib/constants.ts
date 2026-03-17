// Client API base URL (through Next.js rewrite)
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "";

// SSE direct connection to backend (bypasses Next.js to avoid proxy buffering).
// Runtime detection: derive from window.location so Docker rebuild is not needed
// when hostname changes. Override via NEXT_PUBLIC_SSE_URL for custom deployments.
function resolveSseUrl(): string {
  if (typeof window === "undefined") {
    return process.env.NEXT_PUBLIC_SSE_URL || "http://localhost:42001/api/v1/events/stream";
  }
  if (process.env.NEXT_PUBLIC_SSE_URL) {
    return process.env.NEXT_PUBLIC_SSE_URL;
  }
  const proto = window.location.protocol;
  const port = process.env.NEXT_PUBLIC_BACKEND_PORT || "42001";
  return `${proto}//${window.location.hostname}:${port}/api/v1/events/stream`;
}
export const SSE_URL = resolveSseUrl();

// Server-side API (Server Component direct connection, Docker internal)
export const BACKEND_INTERNAL_URL = process.env.BACKEND_INTERNAL_URL || "http://localhost:42001";
