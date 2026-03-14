import { BACKEND_INTERNAL_URL } from "./constants";
import type {
  TaskResponse,
  PersonasMap,
  ToolInfo,
  SchedulerJob,
  HealthStatus,
} from "@/types/api";

// Server Component only: direct connection to backend internal network.
// Not routed through Next.js rewrite — used for SSR pages and Server Components.

async function serverFetch<T>(
  path: string,
  options?: RequestInit & { next?: { revalidate?: number } },
): Promise<T> {
  const res = await fetch(`${BACKEND_INTERNAL_URL}${path}`, {
    ...options,
    next: { revalidate: options?.next?.revalidate ?? 0 },
  } as RequestInit);
  if (!res.ok) throw new Error(`Backend ${path}: ${res.status}`);
  return res.json();
}

export const serverApi = {
  getTask: (threadId: string) =>
    serverFetch<TaskResponse>(`/api/v1/tasks/${encodeURIComponent(threadId)}`),

  getPersonas: () =>
    serverFetch<PersonasMap>("/api/v1/personas", { next: { revalidate: 300 } }),

  getTools: () =>
    serverFetch<ToolInfo[]>("/api/v1/tools", { next: { revalidate: 300 } }),

  getJobs: () => serverFetch<SchedulerJob[]>("/api/v1/scheduler/jobs"),

  getHealth: () => serverFetch<HealthStatus>("/health"),
};
