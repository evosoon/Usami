// Mirror of backend core/state.py + api/routes.py Pydantic models

export type TaskStatus = "pending" | "running" | "completed" | "failed" | "blocked" | "hitl_waiting";

export interface Task {
  task_id: string;
  title: string;
  description: string;
  assigned_persona: string;
  task_type: string;
  dependencies: string[];
  status: TaskStatus;
  priority: number;
}

export interface TaskPlan {
  plan_id: string;
  user_intent: string;
  tasks: Task[];
}

export type HiTLType = "clarification" | "approval" | "conflict" | "error" | "plan_review";

export interface HiTLRequest {
  request_id: string;
  hitl_type: HiTLType;
  title: string;
  description: string;
  context?: Record<string, unknown>;
  options?: string[];
  task_id?: string | null;
  persona?: string | null;
}

// API request/response models (mirror api/routes.py)

export interface TaskRequest {
  intent: string;
  config?: Record<string, unknown>;
}

export interface TaskResponse {
  thread_id: string;
  status: string;
  result: string | null;
  task_plan: TaskPlan | null;
  hitl_pending: HiTLRequest[];
  error?: string;
}

export interface HiTLResolveRequest {
  request_id: string;
  decision: string;
  feedback?: string;
}

// Mirror persona_factory / tool_registry

export interface PersonaInfo {
  name: string;
  description: string;
  tools: string[];
  role: string;
  model: string;
  system_prompt: string;
}

export type PersonasMap = Record<string, PersonaInfo>;

export interface ToolInfo {
  name: string;
  description: string;
  source: string;
  permission_level: string;
}

export interface SchedulerJob {
  id: string;
  name: string;
  next_run_time: string;
}

export interface HealthStatus {
  service: string;
  status: "ok" | "degraded";
  litellm?: string;
  circuit_breaker?: string;
  redis?: string;
}
