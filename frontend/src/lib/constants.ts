// Client API base URL (through Next.js rewrite)
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "";

// WebSocket direct connection to backend (bypasses Next.js).
// Runtime detection: derive from window.location so Docker rebuild is not needed
// when hostname changes. Override via NEXT_PUBLIC_WS_URL for custom deployments.
function resolveWsUrl(): string {
  if (typeof window === "undefined") {
    return process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000/ws";
  }
  if (process.env.NEXT_PUBLIC_WS_URL) {
    return process.env.NEXT_PUBLIC_WS_URL;
  }
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.hostname}:8000/ws`;
}
export const WS_URL = resolveWsUrl();

// Server-side API (Server Component direct connection, Docker internal)
export const BACKEND_INTERNAL_URL = process.env.BACKEND_INTERNAL_URL || "http://localhost:8000";

export const PHASE_LABELS: Record<string, string> = {
  created: "已创建",
  planning: "规划中",
  planned: "计划就绪",
  executing: "执行中",
  hitl_waiting: "等待确认",
  completed: "已完成",
  failed: "失败",
};
