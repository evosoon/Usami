# Usami — Design Decisions Record

> 每一个架构决策都有对应的「死因预防」编号（F1-F9），
> 来自项目启动前的 Pre-mortem 分析。
>
> v2 重构新增决策编号为 D10+。

---

## D1: LangGraph 作为 Agent Runtime，但加薄抽象层

**决策**: 选择 LangGraph，同时在业务逻辑和 LangGraph 之间加一层 `protocols.py`。

**原因**: LangGraph 的 Checkpoint + interrupt/resume 原生解决了我们的第一痛点（协作连贯性），
但直接耦合会导致供应商锁定（F1）。

**替代方案**: CrewAI（上手快但状态管理弱）、自建 Runtime（工程量超标）。

**代价**: 多写约 130 行抽象层代码。
**收益**: 未来可替换为 OpenAI Agents SDK 或其他 Runtime，迁移成本从「重写」降到「实现接口」。

---

## D2: Boss Persona 是 LLM Agent，但输出必须经过 Plan Validator

**决策**: Boss 用 LLM 做任务分解（灵活），但生成的 Plan 必须通过确定性代码校验（可靠）。

**原因**: LLM 推理是非确定性的，Boss 会自信地犯错（F2）。

**校验项**:
1. DAG 无循环依赖
2. 目标 Persona 存在
3. 任务 ID 唯一
4. 依赖引用合法
5. 复杂度过高时强制 HiTL 预览

**原则**: LLM 做创造性决策，确定性代码做正确性验证。

---

## D3: 结构化消息传递（信封模式）

**决策**: Agent 间传递 `TaskOutput{summary, full_result}`，下游默认只读 summary。

**原因**: 全局共享全部信息会导致上下文污染（F3）——后续 Agent 的有效注意力被稀释。

**机制**:
- 上游 → 下游: 只传 summary (≤ 500 tokens)
- 需要详情: Agent 主动请求 full_result
- Boss 汇总: 读取所有 summary + 选择性读取 full_result

---

## D4: Model Router 静态规则 + 日志埋点

**决策**: MVP 用 YAML 静态规则路由，但每次路由决策记录完整日志。

**原因**: 智能路由需要数据训练（F4），MVP 没有数据。先用静态规则上线，
日志 schema Day 1 定好，积累到足够数据后训练轻量路由模型。

**日志字段**: task_type, model_used, tokens, latency, cost, success

---

## D5: 配置驱动 Persona，不写单独文件

**决策**: 所有 Persona 定义在 `personas.yaml`，由 `PersonaFactory` 动态创建。

**原因**: 一人项目维护 15 个模块会复杂度爆炸（F5）。
配置驱动将模块数从 15 砍到 10，每个文件 < 400 行。

**好处**: 新增 Persona 只需加 YAML 配置，不需要写 Python 代码。

---

## D6: Tool Registry 多源加载

**决策**: Tool Registry 支持三种来源 — 内置工具、MCP 动态发现、Skill 插件。

**原因**: 这是支撑 MCP/Skill/Sandbox/OpenClaw 等所有扩展路径的关键设计。
MVP 只用内置工具，但接口 Day 1 就支持多源。

---

## D7: HiTL 事件全量记录

**决策**: 每次 HiTL 交互记录完整上下文（触发条件、用户决定、响应时间）。

**原因**: 这些记录是未来 Progressive Trust 的训练数据。
MVP 阶段「只记不用」，但数据管道 Day 1 埋好。

---

## D8: MVP 锚定「技术调研 + 知识凝练」

**决策**: MVP 不追求通用 OS，围绕一个具体场景 build。

**原因**: 「OS」隐喻会导致追求完备性（F7），一个人做不完。
锚定具体场景的验收标准: 「我每天用它调研，比自己做快 3 倍」。

---

## D9: 探索引擎（灵魂B）架构预留

**决策**: Boss Persona 预留 `mode: autonomous` 字段，但 MVP 不实现。

**原因**: 探索引擎可以建立在执行引擎之上——执行引擎是内核，
探索引擎是跑在内核上的「长生命周期自主进程」。
先把内核做稳，再让它学会自己跑。

---

# v2 重构决策 (2026-03-19)

---

## D10: Worker-driven model — 进程分离

**决策**: API 进程只做 DB 写入 + pg_notify，图执行由独立 Worker 进程完成。

**原因**: v1 使用 `asyncio.create_task()` 在 API 进程内执行图，存在三个问题：
1. 进程重启 = 所有进行中任务丢失（内存状态）
2. 孤儿任务无法追踪（没有 parent process）
3. 无法水平扩展（单进程瓶颈）

**收益**:
- PostgreSQL 成为唯一真相源，`kill -9` Worker 后可恢复
- Worker 可多实例部署，CAS 互斥
- API 进程无状态，随时可重启

---

## D11: Review 节点作为 interrupt 隔离层

**决策**: 5 节点拓扑 `plan → validate → execute → review → aggregate`，其中 `execute` 绝不调用 `interrupt()`。

**原因**: LangGraph `interrupt()` 的底层机制是抛出 `GraphInterrupt` 异常。如果在 `asyncio.gather()` 内部调用：
1. 异常中断 gather，取消所有并行协程
2. 已完成任务的结果被丢弃（尚未写入 state）
3. Resume 后节点从头执行，所有 LLM 调用重跑

**解决方案**: `execute` 只做纯并行执行，结果通过 reducer 写入 state。`review` 在 state 安全写入后检查是否需要 HiTL。

---

## D12: 双通道事件分发

**决策**: 持久化事件走 PostgreSQL + pg_notify，瞬态事件（llm.token）走 Redis pub/sub。

**原因**:
- pg_notify 有 8KB payload 限制，LLM token 流会轻易超过
- LLM token 丢失不影响正确性（断线重连后拿到最终结果即可）
- 持久化事件需要断线重连补发，必须入库

**实现**:
- pg_notify 只传引用（seq, thread_id, type < 100B）
- 完整事件数据在 events 表
- Redis pub/sub 用于高频瞬态事件

---

## D13: SSE 时序协议 — "先 LISTEN 后查询"

**决策**: SSE endpoint 必须先建立 pg LISTEN 监听，再查询历史事件。

**原因**: 如果先查询后监听，存在竞态窗口：

```
错误时序:
T0: SELECT events WHERE seq > 42    → 返回 [43,44,45]
T1: Worker 产生 event 46, pg_notify → 无人监听！
T2: LISTEN events:{user_id}         → 开始监听
T3: yield [43,44,45]                → 补发
T4: 等待下一个通知...              → event 46 永远丢失
```

正确时序确保 T1 的通知进入 queue，然后 last_sent_seq 去重防止重复。

---

## D14: BossState 使用 TypedDict + Annotated reducer

**决策**: State 定义使用 `TypedDict` 而非 plain dict，字段使用 `Annotated` 声明 reducer。

**原因**:
- TypedDict 提供类型检查，IDE 自动补全
- Annotated reducer（如 `operator.add`）支持并行节点安全写入
- 删除 `current_phase` — 图拓扑本身就是 phase
- 删除 `hitl_pending` — `interrupt()` payload 就是 HiTL 请求

**已知限制**: `operator.add` 是 append-only，`retry_failed` 无法从 `completed_task_ids` 移除项目。MVP 设计决策：降级为 `continue`。

---

## D15: 幂等性守卫 — execute 节点的已完成检查

**决策**: `execute_node` 在执行每个任务前检查 `existing_outputs`，跳过已有结果。

**原因**: `interrupt()` resume 后节点从头执行。如果 `review` 在部分任务完成后触发 interrupt：
1. Resume 后 `execute_node` 重跑
2. `asyncio.gather()` 重新启动所有任务
3. 已完成任务的 LLM 调用浪费成本

**解决方案**:
```python
if task.task_id in existing_outputs:
    return task.task_id, existing_outputs[task.task_id]  # 跳过
```

---

## D16: 协作流程沉淀

**决策**: 将人机协作的最佳实践沉淀为 `docs/collaboration-workflow.md`。

**原因**: 在 v2 重构过程中，形成了有效的协作模式：
1. 分析目标与现状 → 对齐确认
2. 制定计划 → 输出方案文档 + Todo List
3. 增量实施 + 即时测试
4. 清理 → 全量测试
5. 回顾反思 → 提炼认知收获
6. 文档沉淀 → 清理阶段性文档
7. 提交与验证
8. 进入下一阶段

**收益**:
- 会话中断可恢复（方案文档 + Todo List）
- 每阶段有明确产出（可追溯）
- 5 个检查点防止错误传播
- 阶段性文档有清理时机（自清洁）
