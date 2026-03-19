import type { HiTLRequest } from "./api";

// ============================================
// v2 SSE Event Types
// ============================================

// Server -> Client events
// Two channels:
//   - Persistent (has seq/id): phase.change, interrupt, task.completed, etc.
//   - Transient (no id): llm.token, heartbeat

export type SseEvent =
  // v2 事件类型
  | { type: "phase.change"; thread_id: string; seq?: number; phase: string; plan_id?: string; task_count?: number; tasks?: unknown[]; total_completed?: number; total_tasks?: number; round?: number }
  | { type: "llm.token"; thread_id: string; content: string; node: string }
  | { type: "interrupt"; thread_id: string; seq: number; value: InterruptValue }
  | { type: "task.completed_single"; thread_id: string; seq?: number; task_id: string; persona: string; summary?: string }
  | { type: "task.failed_single"; thread_id: string; seq?: number; task_id: string; error: string }
  | { type: "task.executing"; thread_id: string; seq?: number; task_id: string; persona: string }
  | { type: "task.completed"; thread_id: string; seq: number; result?: string }
  | { type: "task.failed"; thread_id: string; seq: number; error?: string }
  | { type: "node.completed"; thread_id: string; seq?: number; node: string }
  // Legacy 事件类型 (向后兼容)
  | { type: "task.created"; thread_id: string; seq: number; intent: string }
  | { type: "task.planning"; thread_id: string; seq: number }
  | { type: "task.planning_chunk"; thread_id: string; seq: number; chunk: string }
  | { type: "task.plan_ready"; thread_id: string; seq: number; plan_id: string; task_count: number }
  | { type: "task.progress"; thread_id: string; seq: number; task_id: string; status: string; persona: string }
  | { type: "task.aggregating"; thread_id: string; seq: number }
  | { type: "task.result_chunk"; thread_id: string; seq: number; chunk: string }
  | { type: "task.heartbeat"; thread_id: string; seq: number; phase: string; elapsed_s: number }
  | { type: "hitl.request"; thread_id: string; seq: number; request: HiTLRequest };

// v2 interrupt payload
export interface InterruptValue {
  type: string;
  message: string;
  options: string[];
  raw_output?: string;
  errors?: string[];
  plan?: unknown;
  failed_tasks?: string[];
  failed_details?: Record<string, string>;
}

// All known SSE event type strings
export const SSE_EVENT_TYPES = [
  // v2 事件
  "phase.change",
  "llm.token",
  "interrupt",
  "task.completed_single",
  "task.failed_single",
  "task.executing",
  "task.completed",
  "task.failed",
  "node.completed",
  // Legacy 事件 (向后兼容)
  "task.created",
  "task.planning",
  "task.planning_chunk",
  "task.plan_ready",
  "task.progress",
  "task.aggregating",
  "task.result_chunk",
  "task.heartbeat",
  "hitl.request",
] as const;
