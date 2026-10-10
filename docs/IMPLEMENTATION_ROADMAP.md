# Multi-Agent 重构实施路线

## 总原则

- 每个阶段结束都必须通过该阶段测试才能继续。
- 保持 `/api/chat` 接口兼容。
- 不同时重构 Router、数据库、前端和 MCP。
- 不复制 ReAct Loop。
- 第一阶段不实现 Agent 相互调用。
- 第一阶段不更换 Qdrant。
- 使用 Conda 创建独立 Python 3.11 环境。

## Phase 0：环境与行为基线

### Conda 环境

计划命令（执行阶段使用）：

```powershell
conda create -n customsystem python=3.11 -y
conda activate customsystem
python -m pip install -r requirements.txt
python -m pip install pytest pytest-asyncio httpx
```

建议后续增加 `requirements-dev.txt` 或 `pyproject.toml`，但文档阶段不修改依赖文件。

### 基线任务

- 固定当前 Router 的典型输入输出。
- 为订单号边界、关键词优先级和 Session 等待状态补测试。
- 为 ToolRegistry 和 AgentLoop 上下文治理补测试。
- 记录现有接口响应格式。

### 完成条件

- 测试不连接真实 LLM、PostgreSQL 或 Qdrant。
- 当前代码在基线测试中通过。
- 明确哪些旧行为将被保留，哪些会有意改变。

## Phase 1：RouteDecision 与新 Router

### 数据模型

```python
RouteDecision(
    target="fast_path|presales|in_sales|aftersales|human",
    intent="...",
    entities={},
    confidence=1.0,
)
```

### 任务

- 保留正则和关键词分类逻辑。
- 将七个旧意图映射到新 target。
- 活跃 Session 优先返回原 Agent。
- 规则不确定时使用轻量 LLM 分类。
- Router 只返回决策，不调用工具。

### 映射基线

| 意图 | 简单情况 | 复杂/缺参情况 |
|---|---|---|
| greeting | fast_path | presales |
| faq | fast_path | 对应 domain agent |
| product | fast_path | presales |
| order_query | fast_path | in_sales |
| logistics | fast_path | in_sales |
| after_sales | - | aftersales |
| complaint | human 或 aftersales | aftersales/human |
| complex | 不再作为最终意图 | LLM 决定 Agent/human |

### 完成条件

- Router 不执行 ToolRegistry。
- 所有基线路由用例都有明确 target。
- 低置信度不会静默进入错误 Agent。

## Phase 2：FastPathExecutor

### 任务

- 将 greeting、FAQ、简单商品、订单、物流从旧 Router 移出。
- FastPath 根据 intent 调固定工具链。
- 输出统一 FastPathResult。
- 工具失败时返回可诊断错误或人工接管建议。

### 完成条件

- FastPath 测试可证明没有调用 LLM。
- 相同订单查询不会同时在 Router 和 FastPath 执行。
- FAQ SQL -> RAG 降级行为保持。

## Phase 3：三个专业 ReAct Agent

### 任务

- 将现有 AgentLoop 抽象为可配置 Runtime，或者为每个 Agent 注入独立 ContextBuilder/ToolRegistry View。
- 增加三个 Agent 定义：售前、售中、售后。
- 每个 Agent 使用独立 Prompt 和工具白名单。
- Dispatcher 根据 RouteDecision 选择一个 Agent。

### 第一阶段工具权限

| Agent | 工具 |
|---|---|
| Presales | faq_lookup, rag_search |
| InSales | order_query, faq_lookup, rag_search |
| Aftersales | order_query, faq_lookup, rag_search, request_human |

在添加真实写操作工具前，不宣称系统可以自动完成退款。

### 完成条件

- 三个 Agent 共用一套 ReAct 实现。
- 未授权工具不出现在 Agent tools Schema 中。
- 一次请求默认只运行一个 Agent。
- Agent 工具结果与最终回答可测试。

## Phase 4：Session Memory 与 Customer Memory

### Session Memory

- State：domain、intent、stage、slots、waiting_for。
- Messages：完整用户与 Assistant 历史。
- Summary：超过阈值或转人工时生成。

### Customer Memory

- 第一阶段仅保留结构化 Profile。
- Profile 的权威统计由业务事件更新。
- Flexible Facts 延后，不进入本轮核心重构。

### 完成条件

- 多轮补参继续进入原 Agent。
- Session 完成后恢复 normal。
- Agent 不直接修改订单数、退款数等权威字段。

## Phase 5：Trace 与离线评测

### Trace 字段

- request_id/session_id；
- route target/intent/confidence；
- FastPath 或 Agent；
- agent_name；
- tool_calls、结果状态、延迟；
- LLM 调用次数；
- 总延迟和错误。

### 离线指标

- Router target accuracy；
- Intent accuracy；
- FastPath precision；
- Tool selection accuracy；
- Agent completion rate；
- Human handoff recall；
- 平均 LLM 调用次数；
- 平均响应时间。

## Phase 6：MCP

仅在本地工具链与总测试稳定后进行：

- 定义 Tool Adapter 接口。
- 保留 LocalToolAdapter。
- 增加 MCPToolAdapter。
- 优先迁移只读订单、物流或知识库服务。
- 增加超时、重试、熔断和错误降级测试。

## 每阶段交付格式

每个阶段结束记录：

1. 改动文件；
2. 行为变化；
3. 新增测试；
4. 测试结果；
5. 已知限制；
6. 是否满足进入下一阶段的条件。

