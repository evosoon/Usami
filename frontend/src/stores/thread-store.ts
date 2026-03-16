"use client";

import { create } from "zustand";
import type { WsServerEvent } from "@/types/ws";
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
  events: WsServerEvent[];
  phase: Phase;
  taskPlan: TaskPlan | null;
  pendingHitl: HiTLRequest[];
  result: string | null;
  error: string | null;
  streamingResult: string;
  lastHeartbeat: number | null;
}

interface ThreadStore {
  threads: Map<string, Thread>;
  activeThreadId: string | null;
  setActiveThread: (threadId: string | null) => void;
  createThread: (threadId: string, intent: string) => void;
  appendEvent: (threadId: string, event: WsServerEvent) => void;
  updateFromRest: (threadId: string, data: Partial<Pick<Thread, "taskPlan" | "pendingHitl" | "result">>) => void;
  getActiveThread: () => Thread | undefined;
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
        lastHeartbeat: null,
      });
      return { threads, activeThreadId: threadId };
    }),

  appendEvent: (threadId, event) =>
    set((state) => {
      const threads = new Map(state.threads);
      const thread = threads.get(threadId);
      if (!thread) {
        // Auto-create thread from WS event if missing (WS arrived before REST response)
        const intent = "type" in event && event.type === "task.created" ? event.intent : "";
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
          lastHeartbeat: null,
        });
        // If no active thread, activate this one so user sees messages
        const activeThreadId = event.type === "task.created" && !state.activeThreadId
          ? threadId
          : state.activeThreadId;
        return { threads, activeThreadId };
      }

      // Heartbeat: update timestamp only, don't append to events (avoid pollution)
      if (event.type === "task.heartbeat") {
        threads.set(threadId, { ...thread, lastHeartbeat: Date.now() });
        return { threads };
      }

      // Streaming chunk: accumulate without appending to events array
      if (event.type === "task.result_chunk") {
        threads.set(threadId, {
          ...thread,
          streamingResult: thread.streamingResult + event.chunk,
        });
        return { threads };
      }

      const events = [...thread.events, event];
      const phase = EVENT_TO_PHASE[event.type] ?? thread.phase;
      const error = event.type === "task.failed" ? event.error : thread.error;
      const result = event.type === "task.completed" && event.result ? event.result : thread.result;

      // Reset streaming state on aggregation start; clear on completion
      const streamingResult = event.type === "task.aggregating" ? ""
        : event.type === "task.completed" ? ""
        : thread.streamingResult;

      // Handle HiTL request from WS — append to pendingHitl
      const pendingHitl = event.type === "hitl.request"
        ? [...thread.pendingHitl, event.request]
        : thread.pendingHitl;

      threads.set(threadId, { ...thread, events, phase, error, result, pendingHitl, streamingResult });
      return { threads };
    }),

  updateFromRest: (threadId, data) =>
    set((state) => {
      const threads = new Map(state.threads);
      const thread = threads.get(threadId);
      if (!thread) return state;

      const updated = { ...thread, ...data };

      // Update phase based on REST response data
      if (data.pendingHitl && data.pendingHitl.length > 0) {
        updated.phase = "hitl_waiting";
      } else if (data.result && thread.phase !== "completed") {
        // REST returned a result but WS event was missed — sync phase
        updated.phase = "completed";
      }

      threads.set(threadId, updated);
      return { threads };
    }),

  getActiveThread: () => {
    const { threads, activeThreadId } = get();
    return activeThreadId ? threads.get(activeThreadId) : undefined;
  },
}));
