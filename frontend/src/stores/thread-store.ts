"use client";

import { create } from "zustand";
import { api } from "@/lib/api-client";
import type { PersistedEventDto } from "@/lib/api-client";
import type { SseEvent, InterruptValue } from "@/types/sse";
import type { TaskPlan, HiTLRequest } from "@/types/api";

export type Phase =
  | "created"
  | "planning"
  | "planned"
  | "executing"
  | "hitl_waiting"
  | "aggregating"
  | "completed"
  | "failed";

export interface Thread {
  threadId: string;
  intent: string;
  createdAt: number;
  events: SseEvent[];
  phase: Phase;
  taskPlan: TaskPlan | null;
  pendingHitl: HiTLRequest[];
  pendingInterrupt: InterruptValue | null;
  result: string | null;
  error: string | null;
  streamingPlan: string;
  streamingAggregate: string;
  activeNode: string;
  streamingResult: string;
  streamingPlanning: string;
  lastHeartbeat: number | null;
  pendingIntent: string | null;
  progress: { completed: number; total: number } | null;
  /** Highest seq number seen — used for deduplication */
  lastSeq: number;
}

interface ThreadStore {
  threads: Map<string, Thread>;
  activeThreadId: string | null;
  /** Deleted thread IDs - ignore SSE events for these */
  deletedThreadIds: Set<string>;
  setActiveThread: (threadId: string | null) => void;
  createThread: (threadId: string, intent: string) => void;
  prepareFollowUp: (threadId: string, intent: string) => void;
  appendEvent: (threadId: string, event: SseEvent) => void;
  updateFromRest: (threadId: string, data: Partial<Pick<Thread, "taskPlan" | "pendingHitl" | "pendingInterrupt" | "result">>) => void;
  getActiveThread: () => Thread | undefined;
  loadThreads: () => Promise<void>;
  loadThreadEvents: (threadId: string) => Promise<void>;
  removeThread: (threadId: string) => Thread | undefined;
  restoreThread: (thread: Thread) => void;
  /** Check if a thread was deleted (for SSE filtering) */
  isDeleted: (threadId: string) => boolean;
}

function createEmptyThread(threadId: string, intent: string = ""): Thread {
  return {
    threadId,
    intent,
    createdAt: Date.now(),
    events: [],
    phase: "created",
    taskPlan: null,
    pendingHitl: [],
    pendingInterrupt: null,
    result: null,
    error: null,
    streamingPlan: "",
    streamingAggregate: "",
    activeNode: "",
    streamingResult: "",
    streamingPlanning: "",
    lastHeartbeat: null,
    pendingIntent: null,
    progress: null,
    lastSeq: 0,
  };
}

/**
 * Convert persisted event DTO to SseEvent
 * Backend format: { event_type, payload: { type, data: {...} } }
 */
function persistedToSseEvent(dto: PersistedEventDto): SseEvent {
  const eventType = dto.event_type;
  const payload = dto.payload || {};
  const data = (payload.data as Record<string, unknown>) || {};
  const base = { thread_id: dto.thread_id, seq: dto.seq };

  switch (eventType) {
    case "task.created":
      return {
        type: "task.created",
        ...base,
        intent: (data.intent as string) || "",
      };

    case "phase.change":
      return {
        type: "phase.change",
        ...base,
        phase: (data.phase as string) || "unknown",
        plan_id: data.plan_id as string | undefined,
        task_count: data.task_count as number | undefined,
        tasks: data.tasks as unknown[] | undefined,
        total_completed: data.total_completed as number | undefined,
        total_tasks: data.total_tasks as number | undefined,
        round: data.round as number | undefined,
      };

    case "task.completed":
      return {
        type: "task.completed",
        ...base,
        result: (data.result as string) || undefined,
      };

    case "task.failed":
      return {
        type: "task.failed",
        ...base,
        error: (data.error as string) || undefined,
      };

    case "task.completed_single":
      return {
        type: "task.completed_single",
        ...base,
        task_id: (data.task_id as string) || "",
        persona: (data.persona as string) || "",
        summary: data.summary as string | undefined,
      };

    case "task.failed_single":
      return {
        type: "task.failed_single",
        ...base,
        task_id: (data.task_id as string) || "",
        error: (data.error as string) || "",
      };

    case "node.completed":
      return {
        type: "node.completed",
        ...base,
        node: (data.node as string) || "",
      };

    case "interrupt":
      return {
        type: "interrupt",
        ...base,
        value: (data.value as InterruptValue) || { type: "unknown", message: "", options: [] },
      };

    // Legacy events
    case "task.planning":
      return { type: "task.planning", ...base };
    case "task.plan_ready":
      return {
        type: "task.plan_ready",
        ...base,
        plan_id: (payload.plan_id as string) || "",
        task_count: (payload.task_count as number) || 0,
      };
    case "task.executing":
      return {
        type: "task.executing",
        ...base,
        task_id: (data.task_id as string) || (payload.task_id as string) || "",
        persona: (data.persona as string) || (payload.persona as string) || "",
      };
    case "task.aggregating":
      return { type: "task.aggregating", ...base };
    case "hitl.request":
      return {
        type: "hitl.request",
        ...base,
        request: (payload.request as HiTLRequest) || { request_id: "", hitl_type: "approval", title: "", description: "" },
      };

    default:
      // Fallback - return as task.heartbeat to avoid type errors
      return { type: "task.heartbeat", ...base, phase: "unknown", elapsed_s: 0 };
  }
}

export const useThreadStore = create<ThreadStore>((set, get) => ({
  threads: new Map(),
  activeThreadId: null,
  deletedThreadIds: new Set(),

  setActiveThread: (threadId) => set({ activeThreadId: threadId }),

  createThread: (threadId, intent) =>
    set((state) => {
      const threads = new Map(state.threads);
      threads.set(threadId, createEmptyThread(threadId, intent));
      return { threads, activeThreadId: threadId };
    }),

  prepareFollowUp: (threadId, intent) =>
    set((state) => {
      const threads = new Map(state.threads);
      const thread = threads.get(threadId);
      if (!thread) return state;
      threads.set(threadId, {
        ...thread,
        phase: "created",
        error: null,
        streamingResult: "",
        streamingPlanning: "",
        streamingPlan: "",
        streamingAggregate: "",
        pendingHitl: [],
        pendingInterrupt: null,
        pendingIntent: intent,
        progress: null,
      });
      return { threads };
    }),

  appendEvent: (threadId, event) =>
    set((state) => {
      // Ignore events for deleted threads
      if (state.deletedThreadIds.has(threadId)) {
        return state;
      }

      const threads = new Map(state.threads);
      let thread = threads.get(threadId);

      // Auto-create thread if missing
      if (!thread) {
        const intent = event.type === "task.created" ? event.intent : "";
        thread = createEmptyThread(threadId, intent);
      }

      // Seq-based deduplication: skip events we've already seen.
      // Transient events (llm.token, heartbeat) have no seq and bypass this check.
      const eventSeq = "seq" in event ? (event.seq as number | undefined) : undefined;
      if (eventSeq !== undefined && eventSeq > 0 && eventSeq <= thread.lastSeq) {
        return state; // duplicate — no-op
      }

      // Update high-water mark
      const lastSeq = eventSeq !== undefined && eventSeq > thread.lastSeq
        ? eventSeq
        : thread.lastSeq;

      // Process event based on type
      const updates: Partial<Thread> = {};

      switch (event.type) {
        case "task.created":
          updates.intent = event.intent || thread.intent;
          updates.pendingIntent = null;
          updates.events = [...thread.events, event];
          break;

        case "phase.change": {
          const phase = event.phase as Phase;
          updates.phase = phase;
          updates.events = [...thread.events, event];

          // Extract task plan from planned phase
          if (phase === "planned" && event.tasks) {
            updates.taskPlan = { tasks: event.tasks } as TaskPlan;
          }
          // Extract progress from executing phase
          if (phase === "executing" && event.total_tasks !== undefined) {
            updates.progress = {
              completed: event.total_completed ?? 0,
              total: event.total_tasks,
            };
          }
          // Reset streaming on phase change
          if (phase === "aggregating") {
            updates.streamingAggregate = "";
            updates.streamingResult = "";
          } else if (phase === "planning") {
            updates.streamingPlan = "";
            updates.streamingPlanning = "";
          }
          break;
        }

        case "task.completed":
          updates.phase = "completed";
          updates.result = event.result || null;
          updates.events = [...thread.events, event];
          // Clear streaming
          updates.streamingResult = "";
          updates.streamingAggregate = "";
          break;

        case "task.failed":
          updates.phase = "failed";
          updates.error = event.error || null;
          updates.events = [...thread.events, event];
          break;

        case "task.completed_single":
        case "task.failed_single":
        case "node.completed":
          // Just append to events, don't change phase
          updates.events = [...thread.events, event];
          break;

        case "interrupt":
          updates.phase = "hitl_waiting";
          updates.pendingInterrupt = event.value;
          updates.events = [...thread.events, event];
          break;

        case "llm.token":
          // Transient - don't append to events, just update streaming
          updates.activeNode = event.node;
          if (event.node === "plan") {
            updates.streamingPlan = thread.streamingPlan + event.content;
            updates.streamingPlanning = thread.streamingPlanning + event.content;
          } else if (event.node === "aggregate") {
            updates.streamingAggregate = thread.streamingAggregate + event.content;
            updates.streamingResult = thread.streamingResult + event.content;
          }
          break;

        case "task.heartbeat":
          updates.lastHeartbeat = Date.now();
          break;

        // Legacy events
        case "task.planning":
          updates.phase = "planning";
          updates.events = [...thread.events, event];
          break;

        case "task.plan_ready":
          updates.phase = "planned";
          updates.events = [...thread.events, event];
          break;

        case "task.executing":
          updates.phase = "executing";
          updates.events = [...thread.events, event];
          break;

        case "task.aggregating":
          updates.phase = "aggregating";
          updates.streamingResult = "";
          updates.events = [...thread.events, event];
          break;

        case "task.result_chunk":
          updates.streamingResult = thread.streamingResult + event.chunk;
          updates.streamingAggregate = thread.streamingAggregate + event.chunk;
          break;

        case "task.planning_chunk":
          updates.streamingPlanning = thread.streamingPlanning + event.chunk;
          updates.streamingPlan = thread.streamingPlan + event.chunk;
          break;

        case "hitl.request":
          updates.phase = "hitl_waiting";
          updates.pendingHitl = [...thread.pendingHitl, event.request];
          updates.events = [...thread.events, event];
          break;

        default:
          // Unknown event - just append
          updates.events = [...thread.events, event];
      }

      threads.set(threadId, { ...thread, ...updates, lastSeq });

      // Auto-set active thread on task.created
      const activeThreadId = event.type === "task.created" && !state.activeThreadId
        ? threadId
        : state.activeThreadId;

      return { threads, activeThreadId };
    }),

  updateFromRest: (threadId, data) =>
    set((state) => {
      const threads = new Map(state.threads);
      const thread = threads.get(threadId);
      if (!thread) return state;

      const updated = { ...thread, ...data };

      if (data.pendingHitl && data.pendingHitl.length > 0) {
        updated.phase = "hitl_waiting";
      } else if (data.result && thread.phase !== "completed") {
        updated.phase = "completed";
      }

      threads.set(threadId, updated);
      return { threads };
    }),

  getActiveThread: () => {
    const { threads, activeThreadId } = get();
    return activeThreadId ? threads.get(activeThreadId) : undefined;
  },

  loadThreads: async () => {
    try {
      const summaries = await api.getThreads();
      set((state) => {
        const threads = new Map(state.threads);
        for (const s of summaries) {
          if (threads.has(s.thread_id)) continue;
          const thread = createEmptyThread(s.thread_id, s.intent ?? "");
          thread.createdAt = new Date(s.created_at).getTime();
          thread.phase = (s.latest_phase as Phase) ?? (s.status as Phase) ?? "created";
          thread.result = s.result ?? null;
          threads.set(s.thread_id, thread);
        }
        return { threads };
      });
    } catch (err) {
      console.error("[thread-store] Failed to load threads:", err);
    }
  },

  loadThreadEvents: async (threadId: string) => {
    try {
      const dtos = await api.getThreadEvents(threadId);
      set((state) => {
        const threads = new Map(state.threads);
        const existing = threads.get(threadId);

        // Replay events
        let phase: Phase = "created";
        let intent = existing?.intent ?? "";
        let result: string | null = null;
        let error: string | null = null;
        let taskPlan: TaskPlan | null = null;
        const pendingHitl: HiTLRequest[] = [];
        let pendingInterrupt: InterruptValue | null = null;
        const events: SseEvent[] = [];

        for (const dto of dtos) {
          const event = persistedToSseEvent(dto);

          // Skip transient events
          if (event.type === "task.result_chunk" ||
              event.type === "task.planning_chunk" ||
              event.type === "task.heartbeat" ||
              event.type === "llm.token") {
            continue;
          }

          events.push(event);

          // Update state based on event
          switch (event.type) {
            case "task.created":
              if (!intent) intent = event.intent;
              break;
            case "phase.change":
              phase = event.phase as Phase;
              if (event.tasks) {
                taskPlan = { tasks: event.tasks } as TaskPlan;
              }
              break;
            case "task.completed":
              phase = "completed";
              result = event.result ?? null;
              break;
            case "task.failed":
              phase = "failed";
              error = event.error ?? null;
              break;
            case "interrupt":
              phase = "hitl_waiting";
              pendingInterrupt = event.value;
              break;
            case "hitl.request":
              phase = "hitl_waiting";
              pendingHitl.push(event.request);
              break;
            // Legacy
            case "task.planning":
              phase = "planning";
              break;
            case "task.plan_ready":
              phase = "planned";
              break;
            case "task.executing":
              phase = "executing";
              break;
            case "task.aggregating":
              phase = "aggregating";
              break;
          }
        }

        const thread = createEmptyThread(threadId, intent);
        thread.createdAt = existing?.createdAt ?? (dtos[0] ? new Date(dtos[0].created_at).getTime() : Date.now());
        thread.events = events;
        thread.phase = phase;
        thread.taskPlan = taskPlan;
        thread.pendingHitl = pendingHitl;
        thread.pendingInterrupt = pendingInterrupt;
        thread.result = result;
        thread.error = error;

        threads.set(threadId, thread);
        return { threads };
      });
    } catch (err) {
      console.error("[thread-store] Failed to load thread events:", threadId, err);
    }
  },

  removeThread: (threadId) => {
    const thread = get().threads.get(threadId);
    set((state) => {
      const threads = new Map(state.threads);
      threads.delete(threadId);
      // Add to deleted set to ignore future SSE events
      const deletedThreadIds = new Set(state.deletedThreadIds);
      deletedThreadIds.add(threadId);
      const activeThreadId = state.activeThreadId === threadId ? null : state.activeThreadId;
      return { threads, activeThreadId, deletedThreadIds };
    });
    return thread;
  },

  restoreThread: (thread) =>
    set((state) => {
      const threads = new Map(state.threads);
      threads.set(thread.threadId, thread);
      // Remove from deleted set on restore
      const deletedThreadIds = new Set(state.deletedThreadIds);
      deletedThreadIds.delete(thread.threadId);
      return { threads, deletedThreadIds };
    }),

  isDeleted: (threadId) => get().deletedThreadIds.has(threadId),
}));
