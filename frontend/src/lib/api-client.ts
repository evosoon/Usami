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

// Singleton refresh promise to dedup concurrent 401 retries
let refreshPromise: Promise<{ id: string; email: string; display_name: string; role: string } | null> | null = null;

async function refreshAuth(): Promise<{ id: string; email: string; display_name: string; role: string } | null> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/auth/refresh`, {
      method: "POST",
      credentials: "include",
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data.user ?? null;
  } catch {
    return null;
  }
}

async function request<T>(path: string, options?: RequestInit, _retried = false): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    // Auto-refresh on 401 (once per request chain)
    if (res.status === 401 && !_retried && typeof window !== "undefined") {
      if (!refreshPromise) {
        refreshPromise = refreshAuth().finally(() => { refreshPromise = null; });
      }
      const user = await refreshPromise;
      if (user) {
        // Update auth store with refreshed user profile
        const { useAuthStore } = await import("@/stores/auth-store");
        useAuthStore.getState().setUser(user);
        return request<T>(path, options, true);
      }
      // Refresh failed — redirect to login with return URL
      const returnUrl = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.href = `/login?returnUrl=${returnUrl}`;
    }
    const body = await res.text();
    throw new ApiError(res.status, body);
  }
  return res.json();
}

// Thread summary from list_user_threads
export interface ThreadSummary {
  thread_id: string;
  intent: string;
  status: string;  // Backend returns 'status' as the phase
  latest_phase?: string;  // May not be present in API response
  result: string | null;
  created_at: string;
  updated_at: string;
}

// Persisted event from event_store
export interface PersistedEventDto {
  id: string;
  thread_id: string;
  user_id: string;
  seq: number;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export const api = {
  createTask: (intent: string, config = {}, threadId?: string) =>
    request<{ thread_id: string; status: string }>("/api/v1/tasks", {
      method: "POST",
      body: JSON.stringify({ intent, config, thread_id: threadId }),
    }),

  getTask: (threadId: string) =>
    request<TaskResponse>(`/api/v1/tasks/${encodeURIComponent(threadId)}`),

  cancelTask: (threadId: string) =>
    request<{ status: string }>(`/api/v1/tasks/${encodeURIComponent(threadId)}/cancel`, {
      method: "POST",
    }),

  resolveHitl: (threadId: string, data: HiTLResolveRequest) =>
    request<{ status: string; request_id: string }>(
      `/api/v1/tasks/${encodeURIComponent(threadId)}/hitl`,
      {
        method: "POST",
        body: JSON.stringify(data),
      },
    ),

  // Thread history
  getThreads: () =>
    request<ThreadSummary[]>("/api/v1/threads"),

  getThreadEvents: (threadId: string, afterSeq = 0) =>
    request<PersistedEventDto[]>(
      `/api/v1/threads/${encodeURIComponent(threadId)}/events?after_seq=${afterSeq}`,
    ),

  deleteThread: (threadId: string) =>
    request<{ status: string }>(`/api/v1/threads/${encodeURIComponent(threadId)}`, {
      method: "DELETE",
    }),

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
