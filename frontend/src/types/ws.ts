import type { HiTLRequest } from "./api";

// Server -> Client events (boss.py emit() via ws_manager.broadcast())
export type WsServerEvent =
  | { type: "task.created"; thread_id: string; intent: string }
  | { type: "task.planning"; thread_id: string }
  | { type: "task.plan_ready"; thread_id: string; plan_id: string; task_count: number }
  | { type: "task.executing"; thread_id: string; task_id: string; persona: string }
  | { type: "task.progress"; thread_id: string; task_id: string; status: string; persona: string }
  | { type: "task.completed"; thread_id: string; result?: string }
  | { type: "task.failed"; thread_id: string; task_id: string; error: string }
  | { type: "hitl.request"; thread_id: string; request: HiTLRequest };

// Client -> Server events (websocket.py handles)
export type WsClientEvent =
  | { type: "hitl.response"; thread_id: string; request_id: string; decision: string; feedback: string }
  | { type: "task.cancel"; thread_id: string };
