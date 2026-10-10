# CustomSystem 当前代码审查

## 1. 审查结论

当前系统不是空壳，已经具备可复用的 Agent 核心、确定性路由、RAG、数据库工具、会话状态和客户画像。重构应采用渐进迁移，不应推倒重写。

当前最主要的问题不是功能不足，而是职责集中：`IntentRouter` 同时负责分类和业务执行，`server.py` 同时承担装配、编排、记忆更新、画像更新和监控。

## 2. 当前请求链路

```text
POST /api/chat
  -> 输入安全校验
  -> 加载手机号与 CustomerProfile
  -> 读取 ContextStore
  -> IntentRouter.route
       -> greeting
       -> faq
       -> product
       -> order_query
       -> logistics
       -> after_sales
       -> complaint
       -> complex
  -> Router 未完全处理时进入 AgentLoop
  -> ConfidenceEvaluator
  -> 会话日志
  -> _update_context
```

### 当前 Router 的实际职责

- 正则提取订单号、快递号、手机号尾号。
- 关键词意图分类。
- 规则无法识别时调用 LLM 分类。
- 调用 FAQ、订单和 RAG 工具。
- 组织 FastPath 回复。
- 为售后请求查询订单并生成 Agent 上下文。
- 直接处理投诉转人工。
- 维护路由统计、延迟和人工接管次数。

因此当前 Router 既是 Router，也是 FastPathExecutor 和部分 Workflow。

## 3. 可直接复用的模块

### `core/loop.py`

现有 `AgentLoop` 已实现：

- ReAct 循环；
- OpenAI Function Calling 格式工具调用；
- 只读工具并行执行；
- 有副作用工具串行执行；
- 工具结果截断与旧结果压缩；
- 历史消息裁剪；
- LLM 超时和错误降级；
- per-session 历史锁。

结论：保留一个 ReAct 引擎，通过不同 Prompt 和工具白名单构造三个专业 Agent，不复制三套 Loop。

### `tools/registry.py`

已有工具注册、Schema 缓存、参数必填校验和异常包装。可以扩展工具视图/白名单，不需要更换工具模型。

### `context/builder.py`

已区分稳定 System Prompt 与动态 Runtime Context。后续需要增加 Agent 专属 Prompt，但整体拼装思想可保留。

### 会话与画像

- `ContextStore`：当前会话键值状态，30 分钟 TTL。
- `SessionContext`：normal、collecting_info、handoff。
- `SessionStore`：消息与上下文文件持久化。
- `ProfileManager`：PostgreSQL 结构化客户画像。
- `MemoryConsolidator`：会话摘要。

这些模块足够支撑第一阶段，不需要立即引入新的记忆数据库。

### RAG

当前使用本地 BGE + 嵌入式 Qdrant，FAQ 和商品分 Collection，接口清晰。重构阶段保持不变。

## 4. 需要重构的部分

### Router 与 FastPath 混合

目标是：

```text
Router -> RouteDecision
Dispatcher -> FastPath / Agent / Human
```

Router 不再调用业务工具和组织最终回复。

### 单一 Agent 拥有全部工具

当前 `AgentLoop` 使用全局 `ToolRegistry`。三个专业 Agent 需要工具白名单：

- 售前：FAQ、RAG、商品；
- 售中：订单、物流、政策；
- 售后：订单、售后政策、退款/换货、人工接管。

第一阶段缺少退款写工具，因此售后 Agent 只能查询、收集资料或转人工，文档和实现必须如实表达。

### Session 更新滞后

当前 `_update_context` 在回复完成后重新扫描用户关键词。这可能与 Router 结果不一致。目标状态应由 RouteDecision 或 AgentResult 驱动更新。

### 历史持久化不完整

SessionStore 只保存 user/assistant，工具轨迹被过滤。短期可以维持；Trace 应独立保存或记录，不要把工具轨迹混入客户记忆。

### `server.py` 过重

后续应逐步把对象装配和请求编排拆出，但不能第一步就大规模改目录。优先抽出 Router/FastPath/Agent Runtime，最后精简 HTTP 层。

## 5. 当前功能缺口

- 没有正式 `tests/` 自动化测试体系。
- 没有稳定的离线路由数据集。
- 没有 Agent 工具白名单。
- 没有售前、售中、售后独立 Prompt。
- 没有统一 RouteDecision。
- 没有独立 Trace 数据模型。
- 没有真实退款、换货、创建投诉工单工具。
- MCP 尚未接入。

## 6. 已知技术风险

### 路由风险

- 关键词优先级可能错误覆盖复合意图。
- 单条消息可能包含多个业务域。
- 活跃 Session 与新意图之间可能冲突。
- LLM 分类失败时必须有稳定默认行为。

### Agent 风险

- 三个 Agent 若只换名字、不限制 Prompt 和工具，就不构成有意义的 Multi-Agent。
- 写操作工具必须有确认和幂等设计。
- 工具服务不可用时不能让 LLM 推断订单事实。

### 记忆风险

- ContextStore 是单进程内存状态，多实例不共享。
- JSONL 会话与 PostgreSQL 画像分散。
- `last_summary` 只有一份，可能覆盖早期重要信息。
- 当前画像更新仍有部分关键词推断，不能作为全部权威数据。

### 测试风险

- 导入 `server.py` 会初始化 Qdrant 和大量全局对象，不利于单元测试。
- 数据库、Embedding 和 LLM 都是外部依赖，必须通过 Fake/Mock 隔离。
- Windows/Conda 环境应固定 Python 和依赖版本。

## 7. 工作区状态

审查时存在以下未提交内容：

- `core/intent_router.py`：订单号和快递号边界正则修复。
- `server.py`：订单号识别边界正则修复。
- `STARTUP.md`：未跟踪文档。
- `workspace/qdrant_data/`：本地运行数据。

后续必须保留前两项代码修改，不应提交 `.env`、`pgdata` 或本地 Qdrant 数据。

