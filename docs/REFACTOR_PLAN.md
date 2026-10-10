# CustomSystem Multi-Agent 重构方案

## 1. 目标

在保留现有确定性客服能力的前提下，将系统重构为“统一路由 + FastPath + 三个专业 ReAct Agent + 人工接管”。简单请求不调用对话模型，复杂请求只进入一个职责明确的 Agent。

本次重构不追求 Agent 之间自由对话，也不一次性把所有工具 MCP 化。

## 2. 目标请求链路

```text
用户输入
  -> 安全校验与 Session 状态检查
  -> Router
       -> FastPathExecutor
       -> PresalesAgent
       -> InSalesAgent
       -> AftersalesAgent
       -> HumanHandoff
  -> 本地工具（后续可增加 MCP Adapter）
  -> 置信度与 Trace
  -> Session Memory / Customer Memory
```

Router 一次返回：

```json
{
  "target": "fast_path | presales | in_sales | aftersales | human",
  "intent": "具体意图",
  "entities": {},
  "confidence": 1.0
}
```

不单独建立 ExecutionPolicy 服务。FastPath 资格判断是 Router 内部的纯函数，Dispatcher 仅负责按 `target` 调用执行器。

## 3. 职责边界

### Router

- 优先恢复未完成的 Session 任务。
- 使用正则、关键词完成零 Token 分类。
- 规则无法判断时使用一次轻量 LLM 分类。
- 提取订单号、快递号、手机号尾号等实体。
- 决定执行目标，不执行实际业务工具。

### FastPath

- 寒暄。
- FAQ/政策的确定性查询。
- 实体完整的订单与物流查询。
- 简单商品检索。
- 明确要求人工或高风险投诉的直接接管。
- 查询失败时返回明确错误，不让 LLM 编造业务事实。

### 三个 ReAct Agent

- `presales`：复杂推荐、商品比较、需求澄清。
- `in_sales`：物流异常、拆单、多订单及履约问题。
- `aftersales`：退款、退换货、多轮资料收集和一般投诉。

三个 Agent 复用现有 `AgentLoop`，差异仅在 System Prompt 和工具白名单。第一阶段不实现 Agent-to-Agent 调用。

### Human Handoff

- 用户明确要求人工。
- 高风险投诉。
- 低置信度或关键业务服务不可用。
- 高风险写操作需要人工审批。

## 4. 记忆与可观测性

只保留两个记忆概念：

1. `Session Memory`：State、Messages、Summary。
2. `Customer Memory`：结构化 Profile；开放式 Facts 延后实现。

Agent、Router、工具、Token 和延迟进入 Trace，不作为记忆注入普通上下文。

第一阶段继续使用现有 SessionStore、ContextStore 和 ProfileManager，只整理接口，不进行数据库大迁移。

## 5. Qdrant 与 MCP

- Qdrant 保留，继续负责 FAQ 与商品 RAG。
- RAG 调用逐步收口到接口，避免业务层直接依赖具体客户端。
- 第一阶段使用本地 ToolRegistry。
- 第二阶段增加 MCP Tool Adapter；只将订单、物流、知识库等外部能力 MCP 化。

## 6. 当前代码审查结论

### 可复用

- `core/loop.py` 已包含 ReAct、工具调用、并行只读工具、超时和上下文治理。
- `tools/registry.py` 可继续作为统一工具入口。
- `core/intent_router.py` 已具备规则优先、LLM 兜底和实体提取基础。
- `ContextStore`、`SessionStore`、`ProfileManager` 已覆盖第一阶段记忆需求。
- Qdrant + BGE 检索链路已经可用。

### 需要调整

- Router 当前同时分类、调用工具和组织回复，职责过重。
- 七个业务处理器与 `complex` 兜底的层级不一致。
- `server.py` 同时负责装配、路由分支、上下文更新、画像和监控，耦合较高。
- 当前所有 Agent 请求共享全部工具，缺少专业 Agent 工具白名单。
- Session 更新依赖消息后的关键词扫描，容易和 Router 判断不一致。
- 没有正式自动化测试目录和固定测试入口。

### 已存在的用户改动

- `core/intent_router.py` 和 `server.py` 有订单号边界正则修复。
- `STARTUP.md` 与本地 Qdrant 数据未跟踪。
- 重构必须保留上述正则修复，不提交本地向量数据和 `.env`。

## 7. 实施阶段

### Phase 0：基线

- 增加 pytest 配置与无外部服务的测试夹具。
- 为现有路由实体提取、上下文状态和工具注册建立基线测试。

### Phase 1：新 Router 与 FastPath

- 新增 `RouteDecision` 和五类 target。
- 将 FastPath 从 Router 中抽出。
- 保持 `/api/chat` 行为兼容。
- 测试规则分类、实体完整性、Session 恢复、FastPath 降级。

### Phase 2：三个专业 ReAct Agent

- 抽取可配置 Agent Runtime。
- 定义三个 Prompt 和工具白名单。
- Dispatcher 根据 target 选择 Agent。
- 测试 Agent 选择、工具隔离、ReAct 工具往返和最大轮次。

### Phase 3：记忆与 Trace 整理

- 统一 Session State 更新入口。
- 保留最近消息并在阈值触发摘要。
- Profile 只接受确定性业务事件更新。
- 增加结构化 Trace；暂不实现用户 Facts 向量化。

### Phase 4：总体验收

- 单元测试：Router、FastPath、Session、工具、上下文治理。
- 集成测试：每个 Agent 的工具链和多轮状态恢复。
- 端到端测试：从 `/api/chat` 到回复、持久化和 Trace。
- 离线评测：路由准确率、FastPath 命中率、工具准确率、人工接管率。

MCP 在上述基线稳定后作为独立阶段接入。

## 8. 验收标准

- 简单寒暄、FAQ、完整订单和物流查询不进入 ReAct。
- 复杂推荐、物流异常和售后办理分别进入正确 Agent。
- 三个 Agent 无法看到未授权工具。
- 未完成任务的下一轮回复继续进入原 Agent。
- 订单与物流事实只来自工具结果。
- 外部依赖失败时有确定性降级，不产生虚构答案。
- 自动化测试不依赖真实 LLM、PostgreSQL 或 Qdrant。
- 可选端到端环境测试覆盖真实数据库、Qdrant 和模型 Provider。

## 9. 与 Ecom 测试体系的关系

最终测试覆盖面与 Ecom 类似，但评价指标适配本系统：

- Ecom 重点验证所有请求经过 Agent 后的 ReAct、MCP、Memory 和 Multi-Agent。
- CustomSystem 还必须验证 FastPath 是否正确跳过 LLM，以及 Agent 与 FastPath 的一致性。
- 最终测试集同时检查结果和过程：路由目标、工具序列、LLM 调用次数、状态变化、答案关键词和人工接管。

