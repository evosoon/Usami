# Collaboration Workflow v1.0

> Human-AI pair programming workflow for software engineering tasks

## Overview

```
Phase 1        Phase 2        Phase 3           Phase 4      Phase 5       Phase 6        Phase 7        Phase 8
理解与对齐  →  规划      →  增量实施      →  清理     →  回顾反思  →  文档沉淀   →  提交与验证  →  下一阶段
    │            │            │               │            │             │              │              │
    ▼            ▼            ▼               ▼            ▼             ▼              ▼              ▼
  对齐确认    方案文档     步骤验证        全量测试    认知收获     更新/清理文档    CI验证        循环
             Todo List
```

---

## Phase 1: 理解与对齐

### 1.1 分析目标与现状

- 理解用户意图（显式需求 + 隐含期望）
- 探索相关代码/文档
- 识别约束与风险
- 评估影响范围

### 1.2 对齐确认

- 复述理解，请求用户确认
- 澄清歧义点
- 确认边界条件

**检查点**: 用户确认理解正确后继续

---

## Phase 2: 规划

### 2.1 制定计划

- 拆解为可执行步骤
- 识别依赖关系
- 定义验收标准
- 识别风险点

### 2.2 输出方案文档

位置: `~/.claude/plans/<task-name>.md`

内容结构:
```markdown
# <Task Name>

## 目标
<清晰描述要达成的目标>

## 现状分析
<当前代码/架构状态>

## 执行步骤
1. Step 1: <description>
2. Step 2: <description>
...

## 风险点
- Risk 1: <description> → Mitigation: <how to handle>

## 验收标准
- [ ] Criterion 1
- [ ] Criterion 2
```

### 2.3 初始化 Todo List

- 使用 `TodoWrite` 写入所有步骤
- 标记第一个任务为 `in_progress`

**检查点**: 用户审批计划后继续

---

## Phase 3: 增量实施

循环执行每个步骤:

### 3.1 实施当前步骤

- 编写/修改代码
- 更新 Todo 状态为 `in_progress`

### 3.2 即时验证

- 运行相关测试:
  - Backend: `cd backend && uv run python -m pytest tests/ -v --tb=short`
  - Frontend: `cd frontend && pnpm test`
- 类型检查 / lint:
  - Backend: `cd backend && uv run ruff check .`
  - Frontend: `cd frontend && pnpm lint`
- 修复发现的问题

### 3.3 标记完成

- 更新 Todo 状态为 `completed`
- 简要说明完成情况

**检查点**: 每个步骤验证通过后继续下一步

---

## Phase 4: 清理

### 4.1 清理无用代码

- 删除废弃函数/变量
- 移除注释掉的代码
- 清理未使用的 import
- 移除向后兼容的临时代码（如适用）

### 4.2 全量测试

- 运行完整测试套件:
  - Backend: `just test` (pytest)
  - Frontend: `just test-frontend` (Vitest unit tests)
  - Frontend lint: `just lint-frontend`
- 确保无回归
- 修复发现的问题
- E2E tests (`just test-frontend-e2e`) 在有 dev server 时按需运行

**检查点**: 所有测试通过后继续

---

## Phase 5: 回顾反思

### 5.1 总结本次变更

- 实际完成了什么
- 与计划的偏差及原因
- 遇到的障碍及解决方式

### 5.2 提炼认知收获

- 学到的模式/反模式
- 踩过的坑
- 下次可复用的 checklist
- 需要补充到 CLAUDE.md 的约束

**输出**: 结构化的反思总结

---

## Phase 6: 文档沉淀

### 6.1 更新持久文档

| 文档 | 更新内容 |
|------|----------|
| `CLAUDE.md` | 新约束、模式、模块说明 |
| `backend/CLAUDE.md` | 后端架构、API、模块依赖 |
| `frontend/CLAUDE.md` | 前端架构、组件、状态管理 |
| `docs/*.md` | 架构设计、决策记录 |

### 6.2 清理阶段性文档

- 删除或归档 `~/.claude/plans/` 中的方案文档
- 移除 `docs/` 中过时的设计文档
- 更新或删除过时的注释

### 6.3 清理 Todo List

- 确认所有任务已完成
- 清空 Todo List

---

## Phase 7: 提交与验证

### 7.1 提交代码

- `git add` 相关文件
- `git commit` 使用清晰的提交信息
- 关联 issue/PR（如有）

提交信息格式:
```
<type>: <short description>

<detailed description if needed>

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

### 7.2 验证提交

- 确认 CI 通过（如有）
- 确认无 merge conflict
- 确认代码已推送到正确分支

**检查点**: 提交验证通过后继续

---

## Phase 8: 进入下一阶段

- 确认当前阶段完全关闭
- 识别下一个目标
- 回到 Phase 1

---

## 中断恢复机制

当会话中断后恢复时:

```
新会话开始
    │
    ├─── 检查 ~/.claude/plans/ 是否有未完成方案
    │         │
    │         ├─ 有 → 读取方案，恢复上下文，继续执行
    │         │
    │         └─ 无 → 正常开始新任务
    │
    └─── 检查 Todo List 状态
              │
              ├─ 有 in_progress 任务 → 从该任务继续
              │
              └─ 全部 completed → 进入下一 Phase
```

---

## 产出物生命周期

| 产出物 | 创建时机 | 更新时机 | 清理时机 | 生命周期 |
|--------|----------|----------|----------|----------|
| 方案文档 | Phase 2 | Phase 3 (进度) | Phase 6 | 阶段性 |
| Todo List | Phase 2 | Phase 3 (状态) | Phase 6 | 阶段性 |
| 代码变更 | Phase 3 | Phase 4 (清理) | - | 永久 |
| 反思总结 | Phase 5 | - | 精华→文档 | 会话内 |
| CLAUDE.md | 首次 | Phase 6 | - | 永久 |
| Git commit | Phase 7 | - | - | 永久 |

---

## 检查点总结

| # | 检查点 | 位置 | 通过条件 | 失败处理 |
|---|--------|------|----------|----------|
| 1 | 理解对齐 | Phase 1.2 | 用户确认理解正确 | 重新分析 |
| 2 | 计划审批 | Phase 2.3 | 用户审批计划 | 修改计划 |
| 3 | 步骤验证 | Phase 3.3 | 单步测试通过 | 修复后重试 |
| 4 | 全量测试 | Phase 4.2 | 所有测试通过 | 修复回归 |
| 5 | 提交验证 | Phase 7.2 | CI 通过，无冲突 | 修复后重新提交 |

---

## 流程特性

| 特性 | 实现方式 | 价值 |
|------|----------|------|
| **可恢复** | 方案文档 + Todo List | 会话中断不丢失进度 |
| **可追溯** | 每阶段有明确产出 | 知道做了什么、为什么 |
| **有反馈** | 5 个检查点 | 及时发现并修正错误 |
| **自清洁** | 阶段性文档有清理时机 | 避免文档腐化 |
| **增量验证** | 每步即时测试 | 问题早发现早修复 |

---

## 适用场景

| 场景 | 是否适用 | 说明 |
|------|----------|------|
| 新功能开发 | ✅ | 完整流程 |
| 重构 | ✅ | 完整流程 |
| Bug 修复 | ⚠️ | 简化版：可跳过 Phase 2 的方案文档 |
| 简单修改 | ❌ | 过重，直接执行即可 |
| 探索性研究 | ⚠️ | Phase 1-2 适用，Phase 3+ 按需 |

---

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-03-19 | 初始版本，基于 v2 重构实践总结 |
