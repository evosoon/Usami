import { API_BASE_URL } from "./constants";
import type {
  TaskResponse,
  HiTLResolveRequest,
  PersonasMap,
  ToolInfo,
  SchedulerJob,
  HealthStatus,
} from "@/types/api";

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    // Redirect to login on 401
    if (res.status === 401 && typeof window !== "undefined") {
      window.location.href = "/login";
    }
    const body = await res.text();
    throw new ApiError(res.status, body);
  }
  return res.json();
}

export const api = {
  createTask: (intent: string, config = {}) =>
    request<{ thread_id: string; status: string }>("/api/v1/tasks", {
      method: "POST",
      body: JSON.stringify({ intent, config }),
    }),

  getTask: (threadId: string) =>
    request<TaskResponse>(`/api/v1/tasks/${encodeURIComponent(threadId)}`),

  resolveHitl: (threadId: string, data: HiTLResolveRequest) =>
    request<{ status: string; request_id: string }>(
      `/api/v1/tasks/${encodeURIComponent(threadId)}/hitl`,
      {
        method: "POST",
        body: JSON.stringify(data),
      },
    ),

  getPersonas: () => request<PersonasMap>("/api/v1/personas"),
  getTools: () => request<ToolInfo[]>("/api/v1/tools"),
  getJobs: () => request<SchedulerJob[]>("/api/v1/scheduler/jobs"),
  getHealth: () => request<HealthStatus>("/health"),
};

export { ApiError };
