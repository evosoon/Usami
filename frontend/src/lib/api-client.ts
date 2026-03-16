import { API_BASE_URL } from "./constants";
import type {
  TaskResponse,
  HiTLResolveRequest,
  PersonasMap,
  ToolInfo,
  SchedulerJob,
  HealthStatus,
} from "@/types/api";
import type { AdminUser, CreateUserData } from "@/hooks/use-admin-users";

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

  // Admin — user management
  getUsers: () => request<AdminUser[]>("/api/v1/admin/users"),
  createUser: (data: CreateUserData) =>
    request<AdminUser>("/api/v1/admin/users", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  updateUser: (userId: string, data: { display_name?: string; role?: string; is_active?: boolean }) =>
    request<AdminUser>(`/api/v1/admin/users/${encodeURIComponent(userId)}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),

  // Push notifications
  getVapidPublicKey: () =>
    request<{ vapid_public_key: string }>("/api/v1/notifications/vapid-public-key"),
  subscribePush: (data: { endpoint: string; p256dh: string; auth: string }) =>
    request<{ status: string }>("/api/v1/notifications/subscribe", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  unsubscribePush: (endpoint: string) =>
    request<{ status: string }>("/api/v1/notifications/subscribe", {
      method: "DELETE",
      body: JSON.stringify({ endpoint }),
    }),
};

export { ApiError };
