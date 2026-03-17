import type { HiTLRequest } from "./api";

// Server -> Client events (boss.py emit() via sse_manager.send_to_user())
// Each event carries seq for ordering and replay support.
export type SseEvent =
  | { type: "task.created"; thread_id: string; seq: number; intent: string }
  | { type: "task.planning"; thread_id: string; seq: number }
  | { type: "task.planning_chunk"; thread_id: string; seq: number; chunk: string }
  | { type: "task.plan_ready"; thread_id: string; seq: number; plan_id: string; task_count: number }
  | { type: "task.executing"; thread_id: string; seq: number; task_id: string; persona: string }
  | { type: "task.progress"; thread_id: string; seq: number; task_id: string; status: string; persona: string }
  | { type: "task.aggregating"; thread_id: string; seq: number }
  | { type: "task.result_chunk"; thread_id: string; seq: number; chunk: string }
  | { type: "task.completed"; thread_id: string; seq: number; result?: string }
  | { type: "task.failed"; thread_id: string; seq: number; task_id: string; error: string }
  | { type: "task.heartbeat"; thread_id: string; seq: number; phase: string; elapsed_s: number }
  | { type: "hitl.request"; thread_id: string; seq: number; request: HiTLRequest };

// All known SSE event type strings
export const SSE_EVENT_TYPES = [
  "task.created",
  "task.planning",
  "task.planning_chunk",
  "task.plan_ready",
  "task.executing",
  "task.progress",
  "task.aggregating",
  "task.result_chunk",
  "task.completed",
  "task.failed",
  "task.heartbeat",
  "hitl.request",
] as const;
