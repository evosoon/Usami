# Usami — Architecture Overview

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      User / Interaction                          │
│   Chat UI ◄──► Dashboard ◄──► (Future: Workflow Canvas)         │
│              Next.js 16 + React 19 + SSE + REST API              │
└──────────────────────────┬──────────────────────────────────────┘
                           │ REST API + SSE
┌──────────────────────────▼──────────────────────────────────────┐
│                    Control Plane                                 │
│                                                                  │
│  User Intent ──→ Boss Persona ──→ TaskPlan (DAG)                │
│                      │                 │                         │
│                      │          Plan Validator (F2)              │
│                      │                 │                         │
│                      │    ┌────────────▼──────────┐             │
│                      │    │  HiTL Gateway         │             │
│                      │    │  (if complex/unsure)  │             │
│                      │    └────────────┬──────────┘             │
│                      │                 │                         │
│                      ▼                 ▼                         │
│              Task DAG Execution (dependency order)               │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                  Execution Layer                                 │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  Researcher   │  │   Writer     │  │   Analyst    │  ...     │
│  │  (SubGraph)   │  │  (SubGraph)  │  │  (SubGraph)  │          │
│  │               │  │              │  │              │          │
│  │  tools:       │  │  tools:      │  │  tools:      │          │
│  │  - web_search │  │  - file_write│  │  - kb_search │          │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘          │
│         │                  │                  │                   │
│         └──────────────────┴──────────────────┘                  │
│                            │                                     │
│                  TaskOutput (Envelope Pattern)                   │
│                  { summary ≤500tok, full_result, confidence }    │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                Infrastructure Layer                              │
│                                                                  │
│  ┌───────────┐ ┌──────────┐ ┌──────────┐ ┌───────┐ ┌────────┐ │
│  │ LiteLLM   │ │ Postgres │ │  Redis   │ │ Tool  │ │Scheduler│ │
│  │ (Router)  │ │ (State)  │ │ (WM+Bus) │ │Registry│ │ (Cron) │ │
│  └───────────┘ └──────────┘ └──────────┘ └───────┘ └────────┘ │
│                                                                  │
│  Tool Registry (Multi-source):                                  │
│  ├── Builtin Tools                                              │
│  ├── MCP Servers (dynamic discovery)                            │
│  ├── Skill Plugins (future)                                     │
│  └── Sandbox (L3, future)                                       │
└─────────────────────────────────────────────────────────────────┘

                    ┌───────────────────────┐
                    │  Future: 灵魂B         │
                    │  Exploration Engine    │
                    │  (Autonomous Loop)     │
                    └───────────────────────┘
```

## Data Flow: End-to-End Task Execution

```
1. User → "帮我调研 Agent 框架"
   │
2. Boss Persona (LLM: strong tier)
   ├── 意图理解
   ├── 查询可用 Persona 列表
   └── 输出 TaskPlan JSON (Structured Output)
   │
3. Plan Validator (确定性代码)
   ├── DAG 无循环 ✓
   ├── Persona 存在 ✓
   ├── 复杂度评估 → 是否需要 HiTL 预览
   └── 验证通过 → 进入执行
   │
4. Execution Loop (按 DAG 拓扑序)
   │
   ├── T1: Researcher (LLM: medium tier)
   │   ├── 调用 web_search tool
   │   ├── 输出 TaskOutput{summary, full_result}
   │   └── HiTL Gateway 评估 → confidence OK → 继续
   │
   ├── T2: Researcher (依赖 T1)
   │   ├── 读取 T1.summary（信封模式）
   │   ├── 对比分析
   │   └── 输出 TaskOutput
   │
   ├── T3: Analyst (依赖 T2)
   │   ├── 读取 T2.summary
   │   ├── 提炼知识关联
   │   └── 输出 TaskOutput
   │
   └── T4: Writer (依赖 T2 + T3)
       ├── 读取 T2.summary + T3.summary
       ├── 撰写报告
       └── 输出 TaskOutput
   │
5. Boss Aggregation (LLM: strong tier)
   ├── 读取所有 TaskOutput.summary
   ├── 选择性读取关键 full_result
   └── 生成最终报告
   │
6. → User (通过 SSE 实时推送)
```

## Memory Architecture

```
Working Memory (Redis)
├── 当前任务的 State (LangGraph Checkpoint)
├── Agent 间共享上下文
└── TTL: 任务完成后可清理

Episodic Memory (PostgreSQL)
├── task_logs: 每个任务的执行记录
├── hitl_events: HiTL 交互日志 (Progressive Trust 数据管道)
└── routing_logs: Model Router 路由记录

Semantic Memory (PostgreSQL + pgvector, Future)
├── 用户偏好 Profile
├── 知识库 (RAG)
└── 认知体系图谱
```
