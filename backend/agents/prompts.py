"""
Usami — Prompt Templates & Message Constants
Centralized prompt templates for Boss orchestration and task execution.
"""

from __future__ import annotations

# ============================================
# Boss Planning Prompts
# ============================================

PLANNING_SYSTEM_MESSAGE = (
    "You are a precise task planner. Always output valid JSON."
)

BOSS_PLANNING_PROMPT = """You are the task orchestrator (Boss) of Usami.

User intent: {user_intent}

Available Personas:
{persona_list}

Decompose the user intent into executable sub-tasks. Output strict JSON format:

```json
{{
  "plan_id": "plan_<uuid>",
  "user_intent": "<original user intent>",
  "tasks": [
    {{
      "task_id": "t1",
      "title": "<task title>",
      "description": "<what to do specifically>",
      "assigned_persona": "<persona name>",
      "task_type": "<planning|research|writing|analysis|summarize>",
      "dependencies": [],
      "priority": 0
    }}
  ]
}}
```

Rules:
1. Each task must be assigned to an available Persona
2. dependencies lists the task_ids this task depends on
3. Ensure dependencies form a Directed Acyclic Graph (DAG)
4. task_type must be one of: planning, research, writing, analysis, summarize
5. If you are unsure about the user intent, add a task with task_type "clarification"
6. **CRITICAL — MINIMIZE task count.** Default is 1 task. Only add more if genuinely needed:
   - 1 task: questions, advice, explanations, learning requests, simple research, how-to guides
   - 2 tasks: needs BOTH web search AND deep analysis on different aspects
   - 3 tasks: complex multi-domain research requiring parallel investigation
   - NEVER exceed 3 tasks. "I want to learn X" = 1 task (researcher). Do NOT split into research + analysis + writing.
7. NEVER chain tasks sequentially (t1→t2→t3). Each extra task DOUBLES response time.
   - If tasks depend on each other, merge them into ONE task with a richer description
   - Only use dependencies when absolutely unavoidable (e.g., translation needs original text first)
   - Prefer flat DAGs: independent tasks run in parallel
"""


# ============================================
# Boss Aggregation Prompts
# ============================================

AGGREGATION_SYSTEM_MESSAGE = (
    "You are a professional content synthesizer. "
    "Output a well-structured final report."
)

BOSS_AGGREGATION_PROMPT = """You are the task orchestrator (Boss) of Usami.

All sub-tasks are complete. Synthesize the following results into a final deliverable.

Original user intent: {user_intent}

Task result summaries:
{task_summaries}

Please generate:
1. Final report/answer (content delivered directly to the user)
2. Key findings summary
3. If any information is uncertain or conflicting, mark it clearly
"""


# ============================================
# Task Execution Templates
# ============================================

# Persona list line used in planning prompt
PERSONA_LIST_LINE = "- {name}: {description} (tools: {tools})"

# Upstream per-persona result block (envelope pattern)
UPSTREAM_RESULT_BLOCK = "\n--- Result from {persona} ---\n{summary}\n"

# Upstream context section header
UPSTREAM_CONTEXT_HEADER = "Upstream task results:{upstream_context}"

# HumanMessage template for persona task execution
TASK_EXECUTION_TEMPLATE = """Task: {title}
Description: {description}

{upstream_section}

Please execute this task and output the result."""

# Fallback task title when plan parsing fails
FALLBACK_TASK_TITLE = "Direct answer"

# Final aggregation summary
FINAL_REPORT_SUMMARY = "Final report generated"

# Error summary for failed task execution
TASK_EXECUTION_FAILED_SUMMARY = "Execution failed: {error}"

# Previous conversation result (appended to planning prompt for follow-ups)
# Variables: previous_result
FOLLOW_UP_CONTEXT = """

Previous conversation result:
---
{previous_result}
---

The user is asking a follow-up question based on the above result.
"""


# ============================================
# User-facing HiTL Strings (Chinese per language rules)
# ============================================

HITL_PLAN_VALIDATION_TITLE = "任务计划验证失败"
HITL_PLAN_VALIDATION_DESC = "Boss 生成的计划存在问题: {errors}"
HITL_PLAN_VALIDATION_OPTIONS = ["让 Boss 重新规划", "手动修改", "取消"]
