# Usami 前端 MVP 实施方案 (v3)

> 本文件用于跨会话恢复实施进度。下次启动 Claude Code 时，告诉它"按照 docs/frontend-plan.md 继续实施前端"即可。

## 当前进度

- [x] **计划批准**
- [x] Phase 1: 脚手架 + 基础设施 (types, lib, stores, layout shell)
- [x] Phase 2: 对话界面核心
- [x] Phase 3: 任务 DAG 可视化
- [x] Phase 4: HiTL 审批交互
- [x] Phase 5: 系统管理页 + 首页/介绍页
- [x] Phase 6: 会话分享页
- [x] Phase 7: 认证 + 用户管理
- [x] Phase 8: Docker 集成 + 打磨

---

## 设计决策记录

### Next.js 15 而非 Vite

Usami 有三类页面需要服务端渲染能力，SPA 无法满足：

| 页面 | 渲染方式 | 为什么需要 SSR/SSG |
|------|---------|-------------------|
| 首页 | SSG (静态生成) | SEO + 零 JS 首屏 |
| 介绍页 | SSG | SEO + 纯静态内容 |
| 会话分享页 `/share/[threadId]` | SSR (动态) | **Open Graph meta tags** — 社交平台爬虫无法执行 JS，SPA 做不到 |
| 对话界面 `/chat` | Client Component | WebSocket + Zustand 实时交互 |
| Admin 页面 | Server Component | 服务端直接 fetch，无 loading 闪烁 |

`"use client"` 边界清晰：约 80% 的交互组件需要标记，但这只是一行声明，不影响代码写法。

### streamdown 而非 react-markdown

Vercel 出品的 AI 流式 Markdown 渲染器，对 Usami 的具体收益：

| 特性 | 价值 |
|------|------|
| 不完整 Markdown 容错 | Boss 产出的 summary 是 `result_content[:500] + "..."`，会截断 Markdown |
| 内置 Shiki 代码高亮 | 技术报告常含代码块，比 rehype-highlight 更好的主题和行号 |
| CJK 标点优化 | 中文用户，中文报告 |
| 内置 rehype-harden | 渲染 LLM 输出必须防 XSS |
| 逐词动画 | 结果展现时的打字机效果 |
| Mermaid 插件 | 知识分析报告可能含流程图 |

### 状态架构改进 (v1 → v3)

v1 原方案问题及修复：

| 问题 | v1 | v3 |
|------|-----|-----|
| Server/Client state 混合 | 全部 Zustand | **TanStack Query** 管理 REST 数据 + **Zustand** 管理 WS/线程 |
| 单线程模型 | 一个 `activeThreadId` | `Map<threadId, Thread>` 支持多任务并发切换 |
| Phase 手动管理 | 独立字段手动设置 | **事件溯源**：从 WS 事件日志推导 phase，永远不会不同步 |
| 消息存储 | 手动 push messages[] | **消息推导**：`deriveMessages(thread)` 从事件流推导 |
| HiTL WS 缺口 | 未发现 | 发现 boss.py 3 处缺少 emit，设计轮询 fallback |

---

## 技术栈

| 层 | 选择 | 理由 |
|----|------|------|
| 框架 | **Next.js 15** (App Router, `output: "standalone"`) | 首页 SSG + 分享页 SSR + middleware 路由守卫 |
| UI 组件 | **shadcn/ui** (Tailwind CSS 4 + Radix) | 可定制，质量高，streamdown 原生兼容 |
| 服务端状态 | **TanStack Query 5** | 缓存、去重、后台刷新；Admin 页面 + 分享页数据获取 |
| 客户端状态 | **Zustand** | WS 连接管理 + 线程事件溯源 |
| WebSocket | **原生 WebSocket + 自定义封装** | 自动重连，事件分发 |
| Markdown | **streamdown + @streamdown/code + @streamdown/cjk** | AI 场景优化，流式容错，CJK，内置安全加固 |
| DAG 可视化 | **@xyflow/react + @dagrejs/dagre** | dagre 用维护中的 fork |
| 语言 | **TypeScript 5.x** (strict) | 类型安全 |
| 包管理 | **pnpm** | 快，磁盘高效，严格依赖解析 |

---

## 后端 API 契约 (已实现)

### REST

| Method | Path | 说明 | 请求体 | 响应体 |
|--------|------|------|--------|--------|
| POST | `/api/v1/tasks` | 创建任务 (fire-and-forget) | `{ intent: string, config?: {} }` | `{ thread_id, status: "running" }` |
| GET | `/api/v1/tasks/{thread_id}` | 获取任务状态 | - | `{ thread_id, status, task_plan, result, hitl_pending, error? }` |
| POST | `/api/v1/tasks/{thread_id}/hitl` | 回应 HiTL | `{ request_id, decision, feedback? }` | `{ status: "resumed", request_id }` |
| GET | `/api/v1/personas` | 列出 Persona | - | `{ [name]: { description, tools, role, ... } }` |
| GET | `/api/v1/tools` | 列出工具 | - | `[{ name, description, source, permission_level }]` |
| GET | `/api/v1/scheduler/jobs` | 列出定时任务 | - | `[{ id, name, next_run_time }]` |
| GET | `/health` | 健康检查 | - | `{ service, status, litellm?, circuit_breaker?, redis? }` |

> 注意：`GET /personas` 返回的是 dict（key=persona name），不是 array。参见 `persona_factory.list_personas()` 实现。

### WebSocket: `WS /ws/{client_id}`

**Server → Client 事件** (boss.py `emit()` 回调通过 `ws_manager.broadcast()` 发送)：

| 事件 | 载荷 | Boss 状态机触发点 |
|------|------|------------------|
| `task.created` | `{ type, thread_id, intent }` | `routes.py` create_task 后 broadcast |
| `task.planning` | `{ type, thread_id }` | `boss.py` planning_node 入口 |
| `task.plan_ready` | `{ type, thread_id, plan_id, task_count }` | `boss.py` planning_node 完成后 |
| `task.executing` | `{ type, thread_id, task_id, persona }` | `boss.py` execute_node 每个任务开始 |
| `task.progress` | `{ type, thread_id, task_id, status, persona }` | `boss.py` execute_node 每个任务完成 |
| `task.completed` | `{ type, thread_id }` | `boss.py` aggregate_node 完成后 |
| `task.failed` | `{ type, thread_id, task_id, error }` | `boss.py` execute_node 任务失败 |

**Client → Server 事件**（`websocket.py` 处理）：

| 事件 | 载荷 | 说明 |
|------|------|------|
| `hitl.response` | `{ type, thread_id, request_id, decision, feedback }` | 用户响应 HiTL 请求 |
| `task.cancel` | `{ type, thread_id }` | 取消任务（cancel asyncio.Task）|

**⚠️ 已知缺口**：`hitl.request` 事件当前未通过 WebSocket 推送（boss.py 在 validate_node/execute_node 中只更新 state，不 emit）。Phase 4 实施时需后端补充。前端通过 **轮询 GET /tasks/{id} 的 hitl_pending** 作为 fallback。

CORS 已允许 `http://localhost:3000`。

---

## 核心架构设计

### 1. Server/Client 边界划分

```
Server Components (无 "use client"):          Client Components ("use client"):
├── app/page.tsx           (首页, SSG)         ├── components/chat/* (全部)
├── app/about/page.tsx     (介绍, SSG)         ├── components/hitl/*
├── app/share/[id]/page.tsx(分享, SSR)         ├── components/task/*
├── app/admin/*/page.tsx   (管理, SC fetch)    ├── stores/*
├── app/layout.tsx         (thin shell)        ├── hooks/*
└── app/chat/layout.tsx    (SC outer shell)    └── components/layout/providers.tsx
```

原则：**页面壳用 Server Component，交互部分用 Client Component**。

### 2. 事件溯源的线程模型

每个任务线程维护原始 WebSocket 事件日志，UI 状态从事件推导：

```typescript
interface Thread {
  threadId: string;
  intent: string;
  createdAt: number;
  events: WsServerEvent[];    // 原始事件日志（只增不改）

  // 以下字段从 events 推导，或从 REST API 补充：
  phase: Phase;               // 最后一个事件 → phase 映射
  taskPlan: TaskPlan | null;  // task.plan_ready 后通过 GET /tasks/:id 获取
  pendingHitl: HiTLRequest[]; // GET /tasks/:id 的 hitl_pending
  result: string | null;      // task.completed 后通过 GET /tasks/:id 获取
  error: string | null;       // task.failed 事件的 error
}
```

**Phase 推导规则**（从最后一个事件的 `type` 映射）：

```
task.created   → "created"
task.planning  → "planning"
task.plan_ready → "planned"
task.executing → "executing"
task.progress  → "executing"
task.completed → "completed"
task.failed    → "failed"
(hitl_pending.length > 0) → "hitl_waiting"
```

### 3. 双层状态分离

```
┌─────────────────────────────────────────┐
│  TanStack Query (服务端状态)              │
│  - GET /tasks/:id      → queryKey: ["task", threadId]
│  - GET /personas       → queryKey: ["personas"]
│  - GET /tools          → queryKey: ["tools"]
│  - GET /scheduler/jobs → queryKey: ["jobs"]
│  - GET /health         → queryKey: ["health"]
│  自动缓存 + 去重 + 后台刷新 + loading/error
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│  Zustand (客户端状态)                     │
│  thread-store:                           │
│    threads: Map<threadId, Thread>        │
│    activeThreadId: string | null         │
│    createThread(threadId, intent)        │
│    appendEvent(threadId, event)          │
│    setActiveThread(threadId)             │
│                                          │
│  ws-store:                               │
│    status: "connecting"|"connected"|"disconnected"
│    clientId: string                      │
│    connect() / disconnect() / send()     │
│    → 收到事件时调用 threadStore.appendEvent()
└─────────────────────────────────────────┘
```

### 4. WebSocket 架构

```
┌──────────┐    connect     ┌───────────────────┐
│ ws-store │ ──────────────→│ WS /ws/{clientId} │
│          │← server events │                   │
└────┬─────┘                └───────────────────┘
     │ event.thread_id
     ▼
┌──────────────┐
│ thread-store │  appendEvent(threadId, event)
│              │  → 推导 phase
│              │  → 触发 TanStack Query refetch (plan_ready/completed 时)
└──────────────┘
```

- 单 WebSocket 连接，通过 `thread_id` 多路复用
- clientId 存储于 `sessionStorage`（tab 级隔离）
- 自动重连：指数退避 1s → 2s → 4s → ... → 30s 上限
- 重连后通过 GET /tasks/:id 补偿断线期间丢失的状态

### 5. 聊天消息推导

不维护独立的 `messages[]`，而是从事件流 + REST 数据实时推导：

```typescript
function deriveMessages(thread: Thread): ChatMessage[] {
  const messages: ChatMessage[] = [];

  // 用户意图（总是第一条）
  messages.push({ role: "user", content: thread.intent });

  // 从事件流推导系统消息
  for (const event of thread.events) {
    switch (event.type) {
      case "task.planning":
        messages.push({ role: "system", variant: "progress", content: "正在分析意图，规划任务..." });
        break;
      case "task.plan_ready":
        messages.push({ role: "system", variant: "plan", content: `计划就绪：${event.task_count} 个子任务`, plan: thread.taskPlan });
        break;
      case "task.executing":
        messages.push({ role: "system", variant: "progress", content: `[${event.persona}] 正在执行...` });
        break;
      case "task.progress":
        messages.push({ role: "system", variant: "status", content: `[${event.persona}] ${event.status}` });
        break;
      case "task.completed":
        messages.push({ role: "system", variant: "result", content: thread.result ?? "任务完成" });
        break;
      case "task.failed":
        messages.push({ role: "system", variant: "error", content: `任务失败: ${event.error}` });
        break;
    }
  }

  return messages;
}
```

优势：单一数据源（events），无 messages 与 events 不同步的问题。

---

## 项目结构

```
frontend/
├── next.config.ts              # output: "standalone", rewrites /api→backend
├── package.json
├── pnpm-lock.yaml
├── components.json             # shadcn/ui
├── Dockerfile                  # multi-stage standalone build
├── tailwind.config.ts
├── tsconfig.json
├── public/
│   ├── og-default.png          # 默认 Open Graph 图片
│   └── favicon.ico
├── src/
│   ├── app/
│   │   ├── layout.tsx              # Root layout (html/body + providers)
│   │   ├── globals.css             # Tailwind base + shadcn theme + streamdown @source
│   │   │
│   │   ├── page.tsx                # 首页 (SSG) — 产品介绍 + CTA
│   │   ├── about/
│   │   │   └── page.tsx            # 介绍页 (SSG) — 架构说明、Persona 展示
│   │   │
│   │   ├── (app)/                  # Route Group: 应用主体 (带 sidebar layout)
│   │   │   ├── layout.tsx          # App layout: sidebar + header + content
│   │   │   ├── chat/
│   │   │   │   └── page.tsx        # 对话界面 (Client Component 核心)
│   │   │   ├── tasks/
│   │   │   │   └── [threadId]/
│   │   │   │       └── page.tsx    # 任务详情 + DAG (Phase 3)
│   │   │   └── admin/
│   │   │       ├── layout.tsx      # Admin sub-layout
│   │   │       ├── personas/
│   │   │       │   └── page.tsx    # Persona 管理 (Server Component)
│   │   │       ├── tools/
│   │   │       │   └── page.tsx    # 工具列表 (Server Component)
│   │   │       ├── scheduler/
│   │   │       │   └── page.tsx    # 定时任务 (Server Component)
│   │   │       ├── users/
│   │   │       │   └── page.tsx    # 用户管理 (Phase 7)
│   │   │       └── health/
│   │   │           └── page.tsx    # 健康检查 (Server Component)
│   │   │
│   │   ├── share/
│   │   │   └── [threadId]/
│   │   │       └── page.tsx        # 会话分享 (SSR + generateMetadata)
│   │   │
│   │   └── login/
│   │       └── page.tsx            # 登录页 (Phase 7)
│   │
│   ├── components/
│   │   ├── ui/                     # shadcn auto-generated
│   │   ├── chat/
│   │   │   ├── chat-input.tsx          # "use client" — Textarea + Send
│   │   │   ├── message-bubble.tsx      # "use client" — 5 种消息变体 + streamdown
│   │   │   ├── message-list.tsx        # "use client" — ScrollArea + auto-scroll
│   │   │   ├── thread-list.tsx         # "use client" — 左侧线程历史列表
│   │   │   └── phase-banner.tsx        # "use client" — 当前阶段横幅
│   │   ├── task/
│   │   │   ├── task-dag.tsx            # "use client" — @xyflow/react DAG
│   │   │   ├── task-node.tsx           # "use client" — 自定义节点
│   │   │   └── plan-card.tsx           # "use client" — 聊天内计划预览卡片
│   │   ├── hitl/
│   │   │   └── hitl-dialog.tsx         # "use client" — 全局 HiTL 审批弹窗
│   │   ├── landing/
│   │   │   ├── hero.tsx                # 首页 hero 区
│   │   │   ├── feature-grid.tsx        # 特性展示网格
│   │   │   └── cta-section.tsx         # Call to action
│   │   ├── share/
│   │   │   ├── share-message-list.tsx  # 只读消息列表（分享页用, Server Component）
│   │   │   └── share-dag.tsx           # 只读 DAG 缩略图
│   │   ├── layout/
│   │   │   ├── app-sidebar.tsx         # "use client" — 导航侧栏
│   │   │   ├── header.tsx              # "use client" — 顶栏 (health dot + 用户)
│   │   │   └── providers.tsx           # "use client" — QueryClient + WS + Toaster
│   │   └── admin/
│   │       ├── persona-card.tsx        # Server Component OK
│   │       ├── tool-table.tsx
│   │       ├── job-table.tsx
│   │       ├── user-table.tsx
│   │       └── health-panel.tsx
│   │
│   ├── lib/
│   │   ├── api-client.ts          # REST fetch wrapper (客户端用)
│   │   ├── api-server.ts          # 服务端 fetch (Server Component 用, 直连 backend)
│   │   ├── ws.ts                  # "use client" — UsamiWebSocket class
│   │   ├── constants.ts           # URL 常量, PHASE_LABELS
│   │   └── utils.ts               # cn() helper
│   │
│   ├── stores/
│   │   ├── thread-store.ts        # "use client" — 线程事件溯源
│   │   └── ws-store.ts            # "use client" — WS 连接生命周期
│   │
│   ├── hooks/
│   │   ├── use-task-detail.ts     # TanStack Query: GET /tasks/:id
│   │   ├── use-create-task.ts     # TanStack Query mutation: POST /tasks
│   │   ├── use-resolve-hitl.ts    # TanStack Query mutation: POST /tasks/:id/hitl
│   │   ├── use-personas.ts        # TanStack Query: GET /personas
│   │   ├── use-tools.ts           # TanStack Query: GET /tools
│   │   ├── use-jobs.ts            # TanStack Query: GET /scheduler/jobs
│   │   ├── use-health.ts          # TanStack Query: GET /health (refetch 30s)
│   │   └── use-derived-messages.ts # 从 thread events 推导 ChatMessage[]
│   │
│   ├── types/
│   │   ├── api.ts                 # 镜像后端 Pydantic models
│   │   └── ws.ts                  # WS 事件 discriminated union
│   │
│   └── middleware.ts              # Route protection (Phase 7)
```

### 关键目录说明

- **`app/(app)/`** — Route Group（括号不参与 URL），包裹需要侧边栏的应用页面。`/chat`, `/tasks/xxx`, `/admin/*` 共享 sidebar layout
- **`app/page.tsx`** + **`app/about/`** — 首页和介绍页在 Route Group 外，不带 sidebar，有独立 landing 风格
- **`app/share/[threadId]/`** — 分享页独立于 Route Group，SSR 生成带 OG meta 的只读视图
- **`lib/api-server.ts`** — Server Component 专用 fetch，直连 `http://backend:8000`（Docker 内网），不经过 Next.js rewrite

---

## Phase 1: 脚手架 + 基础设施

> 目标: 项目可运行，types/lib/stores 就绪，空白 layout 渲染

### Step 1.1: 创建 Next.js 项目

```bash
cd /Users/wangzhanfeng/dev/project/Usami
npx create-next-app@latest frontend \
  --typescript --tailwind --eslint --app --src-dir \
  --no-import-alias --use-pnpm --turbopack
cd frontend
```

### Step 1.2: 配置 Next.js

`next.config.ts`:
```typescript
import type { NextConfig } from "next";

const config: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      { source: "/api/:path*", destination: "http://localhost:8000/api/:path*" },
      { source: "/health", destination: "http://localhost:8000/health" },
    ];
  },
  // WebSocket 不经过 rewrite，客户端直连后端
  // 开发时 WS URL = ws://localhost:8000/ws
  // 生产时通过 nginx 或环境变量配置
};

export default config;
```

### Step 1.3: 初始化 shadcn/ui

```bash
npx shadcn@latest init
# New York style, Slate 色, CSS variables: yes
npx shadcn@latest add button card input textarea scroll-area badge toast \
  dialog separator skeleton avatar sheet sidebar dropdown-menu tooltip
```

### Step 1.4: 安装核心依赖

```bash
# 状态 + 数据获取
pnpm add zustand @tanstack/react-query

# Markdown (streamdown 替代 react-markdown)
pnpm add streamdown @streamdown/code @streamdown/cjk

# globals.css 中需加: @source "../node_modules/streamdown/dist/*.js";
```

### Step 1.5: 类型定义

`src/types/api.ts` — 严格镜像后端 `core/state.py` + `api/routes.py`:

```typescript
// === 镜像 core/state.py ===

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
  context: Record<string, unknown>;
  options: string[];
  task_id: string | null;
  persona: string | null;
}

// === 镜像 api/routes.py ===

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

// === 镜像 persona_factory / tool_registry ===

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
```

`src/types/ws.ts`:

```typescript
import type { HiTLRequest } from "./api";

// Server → Client
export type WsServerEvent =
  | { type: "task.created"; thread_id: string; intent: string }
  | { type: "task.planning"; thread_id: string }
  | { type: "task.plan_ready"; thread_id: string; plan_id: string; task_count: number }
  | { type: "task.executing"; thread_id: string; task_id: string; persona: string }
  | { type: "task.progress"; thread_id: string; task_id: string; status: string; persona: string }
  | { type: "task.completed"; thread_id: string }
  | { type: "task.failed"; thread_id: string; task_id: string; error: string }
  | { type: "hitl.request"; thread_id: string; request: HiTLRequest };

// Client → Server
export type WsClientEvent =
  | { type: "hitl.response"; thread_id: string; request_id: string; decision: string; feedback: string }
  | { type: "task.cancel"; thread_id: string };
```

### Step 1.6: lib 层

**`src/lib/constants.ts`**:
```typescript
// 客户端 API (经过 Next.js rewrite)
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "";

// WebSocket 直连后端 (不经过 Next.js)
export const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000/ws";

// 服务端 API (Server Component 直连, Docker 内网)
export const BACKEND_INTERNAL_URL = process.env.BACKEND_INTERNAL_URL || "http://localhost:8000";

export const PHASE_LABELS: Record<string, string> = {
  created: "已创建",
  planning: "规划中",
  planned: "计划就绪",
  executing: "执行中",
  hitl_waiting: "等待确认",
  completed: "已完成",
  failed: "失败",
};
```

**`src/lib/api-client.ts`** — 客户端 fetch（经过 Next.js rewrite）:
```typescript
import { API_BASE_URL } from "./constants";

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
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
    request<TaskResponse>(`/api/v1/tasks/${threadId}`),

  resolveHitl: (threadId: string, data: HiTLResolveRequest) =>
    request<{ status: string; request_id: string }>(`/api/v1/tasks/${threadId}/hitl`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  getPersonas: () => request<PersonasMap>("/api/v1/personas"),
  getTools: () => request<ToolInfo[]>("/api/v1/tools"),
  getJobs: () => request<SchedulerJob[]>("/api/v1/scheduler/jobs"),
  getHealth: () => request<HealthStatus>("/health"),
};

import type { TaskResponse, HiTLResolveRequest, PersonasMap, ToolInfo, SchedulerJob, HealthStatus } from "@/types/api";
```

**`src/lib/api-server.ts`** — Server Component 专用（直连后端内网）:
```typescript
import { BACKEND_INTERNAL_URL } from "./constants";
import type { TaskResponse, PersonasMap, ToolInfo, SchedulerJob, HealthStatus } from "@/types/api";

// Server Component 专用: 直连后端内网，不经过 Next.js rewrite
// 用于 SSR 页面和 Server Component 的数据获取

async function serverFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BACKEND_INTERNAL_URL}${path}`, {
    ...options,
    // Next.js fetch cache 配置
    next: { revalidate: options?.next?.revalidate ?? 0 },
  } as RequestInit);
  if (!res.ok) throw new Error(`Backend ${path}: ${res.status}`);
  return res.json();
}

export const serverApi = {
  getTask: (threadId: string) =>
    serverFetch<TaskResponse>(`/api/v1/tasks/${threadId}`),

  getPersonas: () =>
    serverFetch<PersonasMap>("/api/v1/personas", { next: { revalidate: 300 } }),

  getTools: () =>
    serverFetch<ToolInfo[]>("/api/v1/tools", { next: { revalidate: 300 } }),

  getJobs: () =>
    serverFetch<SchedulerJob[]>("/api/v1/scheduler/jobs"),

  getHealth: () =>
    serverFetch<HealthStatus>("/health"),
};
```

**`src/lib/ws.ts`** — WebSocket 封装:
```typescript
import type { WsServerEvent, WsClientEvent } from "@/types/ws";

type EventHandler = (event: WsServerEvent) => void;

export class UsamiWebSocket {
  private ws: WebSocket | null = null;
  private clientId: string;
  private url: string;
  private handlers = new Set<EventHandler>();
  private reconnectDelay = 1000;
  private maxReconnectDelay = 30000;
  private shouldReconnect = true;

  constructor(url: string) {
    let id = sessionStorage.getItem("usami_client_id");
    if (!id) {
      id = `client_${crypto.randomUUID().slice(0, 12)}`;
      sessionStorage.setItem("usami_client_id", id);
    }
    this.clientId = id;
    this.url = `${url}/${this.clientId}`;
  }

  connect(): void { /* WebSocket connect + onmessage → dispatch to handlers */ }
  disconnect(): void { /* close + stop reconnect */ }
  send(event: WsClientEvent): void { /* ws.send(JSON.stringify(event)) */ }
  onEvent(handler: EventHandler): () => void { /* subscribe, return unsubscribe fn */ }
  private scheduleReconnect(): void { /* exponential backoff: delay *= 2, cap at max */ }
}
```

### Step 1.7: Stores

**`src/stores/thread-store.ts`** — 事件溯源核心:
```typescript
import { create } from "zustand";
import type { WsServerEvent } from "@/types/ws";
import type { TaskPlan, HiTLRequest } from "@/types/api";

export type Phase = "created" | "planning" | "planned" | "executing" | "hitl_waiting" | "completed" | "failed";

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
}

interface ThreadStore {
  threads: Map<string, Thread>;
  activeThreadId: string | null;
  setActiveThread: (threadId: string | null) => void;
  createThread: (threadId: string, intent: string) => void;
  appendEvent: (threadId: string, event: WsServerEvent) => void;
  updateFromRest: (threadId: string, data: Partial<Thread>) => void;
  getActiveThread: () => Thread | undefined;
}

function eventToPhase(eventType: string): Phase | null {
  const map: Record<string, Phase> = {
    "task.created": "created",
    "task.planning": "planning",
    "task.plan_ready": "planned",
    "task.executing": "executing",
    "task.progress": "executing",
    "task.completed": "completed",
    "task.failed": "failed",
  };
  return map[eventType] ?? null;
}

export const useThreadStore = create<ThreadStore>((set, get) => ({
  threads: new Map(),
  activeThreadId: null,
  // ... implementations: appendEvent updates phase via eventToPhase()
}));
```

**`src/stores/ws-store.ts`** — WS 连接管理:
```typescript
import { create } from "zustand";
import { UsamiWebSocket } from "@/lib/ws";
import { WS_URL } from "@/lib/constants";
import { useThreadStore } from "./thread-store";
import type { WsClientEvent } from "@/types/ws";

type WsStatus = "disconnected" | "connecting" | "connected";

interface WsStore {
  status: WsStatus;
  ws: UsamiWebSocket | null;
  connect: () => void;
  disconnect: () => void;
  send: (event: WsClientEvent) => void;
}

export const useWsStore = create<WsStore>((set, get) => ({
  status: "disconnected",
  ws: null,
  connect: () => {
    const ws = new UsamiWebSocket(WS_URL);
    ws.onEvent((event) => {
      if ("thread_id" in event) {
        useThreadStore.getState().appendEvent(event.thread_id, event);
      }
    });
    ws.connect();
    set({ ws, status: "connecting" });
  },
  disconnect: () => { get().ws?.disconnect(); set({ ws: null, status: "disconnected" }); },
  send: (event) => get().ws?.send(event),
}));
```

### Step 1.8: Layout + Providers

**`src/app/layout.tsx`** (Root — Server Component, thin shell):
```tsx
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
```

**`src/components/layout/providers.tsx`** (`"use client"`):
```tsx
"use client";
// QueryClientProvider + WS 初始化 (useEffect connect) + Toaster + HiTL Dialog
```

**`src/app/(app)/layout.tsx`** (App shell — sidebar + header):
```tsx
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen">
      <AppSidebar />
      <div className="flex-1 flex flex-col">
        <Header />
        <main className="flex-1 overflow-hidden">{children}</main>
      </div>
    </div>
  );
}
```

### Step 1.9: globals.css streamdown 集成

在 `globals.css` 中追加:
```css
@source "../node_modules/streamdown/dist/*.js";
```

### Step 1.10: 验证

```bash
pnpm dev
# 确认:
# - http://localhost:3000 渲染空白 layout
# - /chat 路由加载 (空白 placeholder)
# - rewrite 工作: fetch("/health") 返回后端数据
# - shadcn 组件正常渲染
```

---

## Phase 2: 对话界面核心

> 目标: 用户输入意图 → 实时看到任务执行进度 → 最终查看 Markdown 结果

### Step 2.1: ChatInput 组件

- `"use client"` — shadcn Textarea + Button
- Enter 发送，Shift+Enter 换行
- 发送流程:
  1. `useCreateTask` mutation → POST /api/v1/tasks
  2. 拿到 `thread_id` → `threadStore.createThread(threadId, intent)`
  3. `threadStore.setActiveThread(threadId)`
  4. WS 事件自动流入 (ws-store 按 thread_id 分发)
- 发送中禁用输入框

### Step 2.2: MessageBubble 组件

`"use client"` — 5 种消息变体:

| variant | 样式 | Markdown |
|---------|------|----------|
| `user` | 右对齐，蓝色背景 | 否 |
| `progress` | 左对齐，灰色，脉冲动画点 | 否 |
| `plan` | 左对齐，卡片，任务列表 | 否 |
| `result` | 左对齐，白色，streamdown 渲染 | **是 — `<Streamdown animated plugins={{ code, cjk }}>`** |
| `error` | 左对齐，红色边框 | 否 |

### Step 2.3: MessageList 组件

- `"use client"` — shadcn ScrollArea
- Auto-scroll to bottom (新消息时)
- 用户手动上滚 → 暂停 auto-scroll → 出现"回到底部"按钮
- 数据来源: `useDerivedMessages(activeThread)` hook

### Step 2.4: PhaseBanner 组件

- `"use client"` — 顶部横幅 (非线性 stepper，因 hitl_waiting 可在任何阶段出现)
- 显示当前 phase 中文标签 + 颜色
- planning/executing 阶段脉冲动画
- completed 绿色勾, failed 红色叉

### Step 2.5: ThreadList 组件

- `"use client"` — 左侧面板
- 每个条目: intent 截断 + phase badge + 相对时间
- 点击切换 `activeThreadId`
- "新对话" 按钮 → `setActiveThread(null)`

### Step 2.6: Chat 页面组装

`src/app/(app)/chat/page.tsx`:
```
┌──────────────────────────────────────────────────┐
│ Header (health dot + 用户)                        │
├──────────┬───────────────────────────────────────┤
│          │ PhaseBanner                            │
│ Thread   ├───────────────────────────────────────┤
│ List     │                                        │
│          │ MessageList (streamdown for results)    │
│          │                                        │
│          ├───────────────────────────────────────┤
│          │ ChatInput                              │
└──────────┴───────────────────────────────────────┘
```

### Step 2.7: 端到端验证

1. `uv run uvicorn backend.main:app --port 8000 --reload`
2. `pnpm dev`
3. 输入测试意图 → 确认 WS 事件实时推送到 MessageList
4. task.completed → GET /tasks/:id 获取 result → streamdown 渲染 Markdown

---

## Phase 3: 任务 DAG 可视化

> 目标: 聊天中展示计划缩略图，可进入全屏 DAG 详情页

### Step 3.1: 安装

```bash
pnpm add @xyflow/react @dagrejs/dagre
```

### Step 3.2: TaskNode 自定义节点

- `"use client"` — Persona 首字母头像 + 任务标题
- 状态颜色: pending=灰, running=蓝脉冲, completed=绿, failed=红
- 点击展开 summary

### Step 3.3: TaskDag 组件

- `"use client"` — `@xyflow/react` + `@dagrejs/dagre` 自动布局 (top-to-bottom)
- 输入: TaskPlan + 实时状态 (WS progress 事件)
- 边着色: 已完成依赖 → 绿, 未完成 → 灰

### Step 3.4: PlanCard 嵌入聊天

task.plan_ready 事件 → MessageBubble variant="plan" 渲染 PlanCard:
- 迷你 DAG 缩略图 (只读)
- "查看详情" → 导航到 `/tasks/:threadId`

### Step 3.5: TaskDetail 页面

`src/app/(app)/tasks/[threadId]/page.tsx`:
- 全屏 DAG (拖拽/缩放)
- 右侧: 选中节点详情 (description, persona, status, output summary)
- 数据: TanStack Query + thread-store 事件流

---

## Phase 4: HiTL 审批交互

> 目标: HiTL 请求弹窗 + 用户决策 → 恢复执行

### Step 4.1: 后端补充 (必须先做)

`boss.py` 3 处补充 `await emit("hitl.request", ...)`:

1. **validate_node** (~L173): 计划验证失败
```python
await emit("hitl.request", {
    "thread_id": state.get("thread_id", ""),
    "request": hitl_req.model_dump(),
})
```
2. **execute_node** (~L286): 置信度/成本触发
3. **execute_node** (~L314): 重试耗尽触发

### Step 4.2: HiTL Dialog 组件

`"use client"` — shadcn Dialog:
- 显示 title + description + context
- options 渲染为按钮组
- 可选 feedback textarea
- 提交: POST /tasks/:id/hitl 或 WS hitl.response

### Step 4.3: 全局监听

providers.tsx 中监听 thread-store `pendingHitl` 变化 → 自动弹出 Dialog。

### Step 4.4: 轮询 Fallback

后端未补 emit 前的临时方案:
- phase 为 executing/planned 时，每 3s 轮询 GET /tasks/:id
- 检查 hitl_pending 新条目 → 弹 Dialog

---

## Phase 5: 系统管理页 + 首页/介绍页

> 目标: Admin 只读页面 + 产品首页 + 介绍页

### Step 5.1: Admin — Personas (Server Component)

`src/app/(app)/admin/personas/page.tsx`:
```tsx
import { serverApi } from "@/lib/api-server";
import { PersonaCard } from "@/components/admin/persona-card";

export default async function PersonasPage() {
  const personas = await serverApi.getPersonas();
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 p-6">
      {Object.entries(personas).map(([key, persona]) => (
        <PersonaCard key={key} name={key} persona={persona} />
      ))}
    </div>
  );
}
```

零客户端 JS，零 loading state，数据直取。

### Step 5.2: Admin — Tools / Scheduler / Health

同模式: Server Component + `serverApi` 直取。Health 页面额外加 Client Component 实现 30s 自动刷新。

### Step 5.3: 首页 (SSG)

`src/app/page.tsx`:
```tsx
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Usami — Personal AI Operating System",
  description: "多 Agent 协作的个人 AI 操作系统，技术调研与知识凝练",
};

export default function HomePage() {
  return (
    <>
      <Hero />
      <FeatureGrid />
      <CtaSection />
    </>
  );
}
```

- 构建时静态生成，零运行时成本
- Hero: 大标题 + 副标题 + "开始使用" 按钮 → /chat
- FeatureGrid: 多 Agent 协作 / DAG 任务分解 / HiTL 审批 / 知识凝练
- CtaSection: 再次 CTA

### Step 5.4: 介绍页 (SSG)

`src/app/about/page.tsx`:
- 架构图 (Boss-Worker 状态机)
- Persona 展示 (fetch personas at build time)
- 技术栈介绍

---

## Phase 6: 会话分享页

> 目标: 用户可通过 URL 分享任务结果，社交平台显示富卡片预览

### Step 6.1: SSR 页面 + generateMetadata

`src/app/share/[threadId]/page.tsx`:

```tsx
import type { Metadata } from "next";
import { serverApi } from "@/lib/api-server";

interface Props {
  params: Promise<{ threadId: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { threadId } = await params;
  const task = await serverApi.getTask(threadId);

  const title = task.task_plan?.user_intent || "Usami 任务结果";
  const description = task.result?.slice(0, 200) || "查看 Usami 生成的任务报告";

  return {
    title,
    description,
    openGraph: {
      title,
      description,
      type: "article",
      images: ["/og-default.png"],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
    },
  };
}

export default async function SharePage({ params }: Props) {
  const { threadId } = await params;
  const task = await serverApi.getTask(threadId);

  return (
    <div className="max-w-4xl mx-auto p-8">
      <header>
        <h1>{task.task_plan?.user_intent}</h1>
        <span>状态: {task.status}</span>
      </header>

      {/* 只读 DAG 缩略图 */}
      {task.task_plan && <ShareDag plan={task.task_plan} />}

      {/* 结果展示 — streamdown 渲染 (Server Component 静态渲染) */}
      {task.result && (
        <Streamdown plugins={{ code, cjk }}>
          {task.result}
        </Streamdown>
      )}

      {/* CTA: 登录查看完整对话 */}
      <footer>
        <a href="/chat">在 Usami 中打开</a>
      </footer>
    </div>
  );
}
```

### Step 6.2: 后端补充 (如需)

当前 GET /tasks/:id 已返回 result + task_plan，足够分享页使用。若需要：
- 增加 `GET /api/v1/tasks/{thread_id}/public` 端点（不需要认证的只读版本）
- 或在 Phase 7 认证实现后，分享页使用 share token 机制

### Step 6.3: 社交卡片验证

```bash
# 测试 OG meta 是否正确注入
curl -s http://localhost:3000/share/thread_xxx | grep "og:"

# 使用 Facebook Sharing Debugger / Twitter Card Validator 验证
```

---

## Phase 7: 认证 + 用户管理

### 后端新增

| 文件 | 说明 |
|------|------|
| `core/auth.py` | bcrypt + JWT (HS256, 15min access + 7d refresh httpOnly cookie) + `get_current_user` Depends |
| `api/auth_routes.py` | POST /auth/login, /auth/refresh, /auth/logout |
| `api/admin_routes.py` | GET/POST /admin/users, PATCH /admin/users/{id} |
| `core/memory.py` | 新增 User 表 (id, email, display_name, hashed_password, role, is_active) |
| `core/state.py` | 新增 UserProfile model |
| `main.py` | 注册 auth/admin routers + seed admin |
| `api/routes.py` | 加 `Depends(get_current_user)` |
| `api/websocket.py` | WS 验证 `?token=xxx` |
| `pyproject.toml` | 加 `python-jose`, `passlib[bcrypt]` |

### 前端新增

| 文件 | 说明 |
|------|------|
| `stores/auth-store.ts` | user, token, login(), logout(), isAuthenticated |
| `lib/api-client.ts` | 加 auth interceptor (Authorization header), 401 → redirect /login |
| `app/login/page.tsx` | Email + Password 表单 |
| `app/(app)/admin/users/page.tsx` | 用户管理表格 |
| `middleware.ts` | Next.js middleware — 未登录 redirect /login (排除 /, /about, /share/*, /login) |

### middleware.ts 路由保护

```typescript
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // 公开路由: 首页, 介绍, 分享, 登录, API, 静态资源
  const publicPaths = ["/", "/about", "/share", "/login", "/api", "/_next", "/favicon.ico"];
  if (publicPaths.some((p) => pathname === p || pathname.startsWith(p + "/"))) {
    return NextResponse.next();
  }

  // 检查 token
  const token = request.cookies.get("access_token")?.value;
  if (!token) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
```

---

## Phase 8: Docker + 打磨

### Step 8.1: Dockerfile (standalone)

```dockerfile
FROM node:20-alpine AS base
RUN corepack enable && corepack prepare pnpm@latest --activate

FROM base AS deps
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
RUN addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000
ENV PORT=3000
CMD ["node", "server.js"]
```

### Step 8.2: docker-compose 集成

取消注释 docker-compose.yml 中 frontend service:
```yaml
frontend:
  build: ./frontend
  ports:
    - "${FRONTEND_PORT:-3000}:3000"
  environment:
    - BACKEND_INTERNAL_URL=http://backend:8000
    - NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws
  depends_on:
    - backend
```

### Step 8.3: 错误边界

- React ErrorBoundary 包裹路由级组件
- WS 断线提示条 (顶部黄色 banner: "连接已断开，正在重连...")
- API 请求失败 toast (shadcn Toaster)
- 空状态设计 (无任务时的引导页)

### Step 8.4: 加载态

- Admin 页面: Next.js `loading.tsx` 文件 + shadcn Skeleton
- DAG: 加载占位
- MessageList: 首次加载 spinner

### Step 8.5: .env.example

```env
# 客户端 (浏览器可见)
NEXT_PUBLIC_API_URL=         # 留空则使用 Next.js rewrite
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws

# 服务端 (Server Component / SSR 用)
BACKEND_INTERNAL_URL=http://localhost:8000   # Docker 内: http://backend:8000
```

---

## 代码风格约定

| 规则 | 说明 |
|------|------|
| **English** | 代码、注释、变量名、类型名、commit 消息 |
| **Chinese** | 用户可见文字（按钮、placeholder、toast、phase 标签、错误提示） |
| 文件名 | kebab-case (`chat-input.tsx`, `api-client.ts`) |
| 组件导出 | PascalCase (`export function ChatInput`) |
| Hook 导出 | camelCase + use 前缀 (`export function useHealth`) |
| Store 导出 | `use[Name]Store` (`useThreadStore`) |
| 类型导出 | PascalCase interface/type (`export interface Thread`) |
| "use client" | 仅在文件顶部标记，不在中间标记；能用 Server Component 的不标 |
| CSS | Tailwind utility classes only (除 globals.css 中的 shadcn/streamdown 主题) |
| 类型 import | `import type { Foo } from "..."` 用 type-only import |
| 无 barrel 文件 | 直接 import 具体文件，不用 `index.ts` re-export |
