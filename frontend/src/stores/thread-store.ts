"use client";

import { create } from "zustand";
import { api } from "@/lib/api-client";
import type { PersistedEventDto } from "@/lib/api-client";
import type { SseEvent } from "@/types/sse";
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
  result: string | null;
  error: string | null;
  streamingResult: string;
  streamingPlanning: string;
  lastHeartbeat: number | null;
  /** Pending user intent for follow-up (before task.created event arrives) */
  pendingIntent: string | null;
}

interface ThreadStore {
  threads: Map<string, Thread>;
  activeThreadId: string | null;
  setActiveThread: (threadId: string | null) => void;
  createThread: (threadId: string, intent: string) => void;
  prepareFollowUp: (threadId: string, intent: string) => void;
  appendEvent: (threadId: string, event: SseEvent) => void;
  updateFromRest: (threadId: string, data: Partial<Pick<Thread, "taskPlan" | "pendingHitl" | "result">>) => void;
  getActiveThread: () => Thread | undefined;
  loadThreads: () => Promise<void>;
  loadThreadEvents: (threadId: string) => Promise<void>;
  removeThread: (threadId: string) => Thread | undefined;
  restoreThread: (thread: Thread) => void;
}

const EVENT_TO_PHASE: Record<string, Phase> = {
  "task.created": "created",
  "task.planning": "planning",
  "task.plan_ready": "planned",
  "task.executing": "executing",
  "task.progress": "executing",
  "task.aggregating": "aggregating",
  "task.completed": "completed",
  "task.failed": "failed",
  "hitl.request": "hitl_waiting",
};

function persistedToSseEvent(dto: PersistedEventDto): SseEvent {
  const p = dto.payload;
  const base = { thread_id: dto.thread_id, seq: dto.seq };
  switch (dto.event_type) {
    case "task.created":
      return { type: "task.created", ...base, intent: (p.intent as string) ?? "" };
    case "task.planning":
      return { type: "task.planning", ...base };
    case "task.planning_chunk":
      return { type: "task.planning_chunk", ...base, chunk: (p.chunk as string) ?? "" };
    case "task.plan_ready":
      return { type: "task.plan_ready", ...base, plan_id: (p.plan_id as string) ?? "", task_count: (p.task_count as number) ?? 0 };
    case "task.executing":
      return { type: "task.executing", ...base, task_id: (p.task_id as string) ?? "", persona: (p.persona as string) ?? "" };
    case "task.progress":
      return { type: "task.progress", ...base, task_id: (p.task_id as string) ?? "", status: (p.status as string) ?? "", persona: (p.persona as string) ?? "" };
    case "task.aggregating":
      return { type: "task.aggregating", ...base };
    case "task.result_chunk":
      return { type: "task.result_chunk", ...base, chunk: (p.chunk as string) ?? "" };
    case "task.completed":
      return { type: "task.completed", ...base, result: (p.result as string) ?? undefined };
    case "task.failed":
      return { type: "task.failed", ...base, task_id: (p.task_id as string) ?? "", error: (p.error as string) ?? "" };
    case "task.heartbeat":
      return { type: "task.heartbeat", ...base, phase: (p.phase as string) ?? "", elapsed_s: (p.elapsed_s as number) ?? 0 };
    case "hitl.request":
      return { type: "hitl.request", ...base, request: p.request as HiTLRequest };
    default:
      // Fallback for unknown event types — treat as heartbeat to avoid losing data
      return { type: "task.heartbeat", ...base, phase: "unknown", elapsed_s: 0 };
  }
}

export const useThreadStore = create<ThreadStore>((set, get) => ({
  threads: new Map(),
  activeThreadId: null,

  setActiveThread: (threadId) => set({ activeThreadId: threadId }),

  createThread: (threadId, intent) =>
    set((state) => {
      const threads = new Map(state.threads);
      threads.set(threadId, {
        threadId,
        intent,
        createdAt: Date.now(),
        events: [],
        phase: "created",
        taskPlan: null,
        pendingHitl: [],
        result: null,
        error: null,
        streamingResult: "",
        streamingPlanning: "",
        lastHeartbeat: null,
        pendingIntent: null,
      });
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
        pendingHitl: [],
        pendingIntent: intent,
      });
      return { threads };
    }),

  appendEvent: (threadId, event) =>
    set((state) => {
      const threads = new Map(state.threads);
      const thread = threads.get(threadId);
      if (!thread) {
        // Auto-create thread from SSE event if missing
        const intent = event.type === "task.created" ? event.intent : "";
        threads.set(threadId, {
          threadId,
          intent,
          createdAt: Date.now(),
          events: [event],
          phase: EVENT_TO_PHASE[event.type] ?? "created",
          taskPlan: null,
          pendingHitl: [],
          result: null,
          error: event.type === "task.failed" ? event.error : null,
          streamingResult: "",
          streamingPlanning: "",
          lastHeartbeat: null,
          pendingIntent: null,
        });
        const activeThreadId = event.type === "task.created" && !state.activeThreadId
          ? threadId
          : state.activeThreadId;
        return { threads, activeThreadId };
      }

      // Heartbeat: update timestamp only
      if (event.type === "task.heartbeat") {
        threads.set(threadId, { ...thread, lastHeartbeat: Date.now() });
        return { threads };
      }

      // Streaming result chunk: accumulate without appending to events array
      if (event.type === "task.result_chunk") {
        threads.set(threadId, {
          ...thread,
          streamingResult: thread.streamingResult + event.chunk,
        });
        return { threads };
      }

      // Planning chunk: accumulate streaming planning text
      if (event.type === "task.planning_chunk") {
        threads.set(threadId, {
          ...thread,
          streamingPlanning: thread.streamingPlanning + event.chunk,
        });
        return { threads };
      }

      const events = [...thread.events, event];
      const phase = EVENT_TO_PHASE[event.type] ?? thread.phase;
      const error = event.type === "task.failed" ? event.error : thread.error;
      const result = event.type === "task.completed" && event.result ? event.result : thread.result;

      // Reset streaming states on phase transitions
      const streamingResult = event.type === "task.aggregating" ? ""
        : event.type === "task.completed" ? ""
        : thread.streamingResult;

      const streamingPlanning = event.type === "task.plan_ready" ? ""
        : event.type === "task.completed" ? ""
        : thread.streamingPlanning;

      // Handle HiTL request — append to pendingHitl
      const pendingHitl = event.type === "hitl.request"
        ? [...thread.pendingHitl, event.request]
        : thread.pendingHitl;

      // Clear pendingIntent when task.created arrives (follow-up intent now confirmed)
      const pendingIntent = event.type === "task.created" ? null : thread.pendingIntent;

      threads.set(threadId, { ...thread, events, phase, error, result, pendingHitl, streamingResult, streamingPlanning, pendingIntent });
      return { threads };
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
          // Don't overwrite threads that already have live events
          if (threads.has(s.thread_id)) continue;
          threads.set(s.thread_id, {
            threadId: s.thread_id,
            intent: s.intent ?? "",
            createdAt: new Date(s.created_at).getTime(),
            events: [],
            phase: (s.latest_phase as Phase) ?? "created",
            taskPlan: null,
            pendingHitl: [],
            result: s.result ?? null,
            error: null,
            streamingResult: "",
            streamingPlanning: "",
            lastHeartbeat: null,
            pendingIntent: null,
          });
        }
        return { threads };
      });
    } catch {
      // Non-fatal: history loading failure shouldn't break the app
    }
  },

  loadThreadEvents: async (threadId: string) => {
    try {
      const dtos = await api.getThreadEvents(threadId);
      set((state) => {
        const threads = new Map(state.threads);
        const existing = threads.get(threadId);

        // Replay persisted events into thread state (instant, no animation)
        let phase: Phase = "created";
        let intent = existing?.intent ?? "";
        let result: string | null = null;
        let error: string | null = null;
        const pendingHitl: HiTLRequest[] = [];
        const events: SseEvent[] = [];

        for (const dto of dtos) {
          const event = persistedToSseEvent(dto);
          // Skip streaming chunks from history — they're transient
          if (event.type === "task.result_chunk" || event.type === "task.planning_chunk" || event.type === "task.heartbeat") {
            continue;
          }
          events.push(event);
          phase = EVENT_TO_PHASE[event.type] ?? phase;
          // Only use the FIRST task.created intent (follow-ups have their own task.created events)
          if (event.type === "task.created" && !intent) intent = event.intent;
          if (event.type === "task.completed") result = event.result ?? null;
          if (event.type === "task.failed") error = event.error;
          if (event.type === "hitl.request") pendingHitl.push(event.request);
        }

        threads.set(threadId, {
          threadId,
          intent,
          createdAt: existing?.createdAt ?? (dtos[0] ? new Date(dtos[0].created_at).getTime() : Date.now()),
          events,
          phase,
          taskPlan: existing?.taskPlan ?? null,
          pendingHitl,
          result,
          error,
          streamingResult: "",
          streamingPlanning: "",
          lastHeartbeat: null,
          pendingIntent: null,
        });
        return { threads };
      });
    } catch {
      // Non-fatal
    }
  },

  removeThread: (threadId) => {
    const thread = get().threads.get(threadId);
    set((state) => {
      const threads = new Map(state.threads);
      threads.delete(threadId);
      const activeThreadId = state.activeThreadId === threadId ? null : state.activeThreadId;
      return { threads, activeThreadId };
    });
    return thread;
  },

  restoreThread: (thread) =>
    set((state) => {
      const threads = new Map(state.threads);
      threads.set(thread.threadId, thread);
      return { threads };
    }),
}));
