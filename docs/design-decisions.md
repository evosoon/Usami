# AgenticOS — Design Decisions Record

> 每一个架构决策都有对应的「死因预防」编号（F1-F9），
> 来自项目启动前的 Pre-mortem 分析。

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
