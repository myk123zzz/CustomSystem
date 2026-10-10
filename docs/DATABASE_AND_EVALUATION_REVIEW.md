# 数据库与 Ecom 评测体系审查

## 1. 结论

数据库设计不应参考 Ecom 的数据层，因为 Ecom 的订单、商品和物流主要是 Python Mock 字典与 JSON 文件，没有可复用的正式关系模型。

Ecom 值得参考的是评测思想：

- JSON 用例集；
- 单轮与多轮输入；
- 运行沙箱；
- LLM、Router、工具调用 Trace；
- 过程指标与结果指标分离；
- 规则评分优先，可选 LLM Judge。

Ecom 的源代码、文档和示例数据采用专有许可。授权允许个人学习和求职修改，但禁止分发或公开其全部或部分内容。因此 CustomSystem 不应直接复制 Ecom 的评测代码和 cases；应独立实现同类结构，使用自己的接口、工具名和业务数据。

## 2. CustomSystem 当前数据库

现有四张表：

```text
faq
product
customer_order
customer_profile
```

当前规模下可以运行，但 Multi-Agent、会话持久化和真实售后流程会暴露一些模型问题。

## 3. 当前字段问题

### 金额使用 Float

`Product.price`、`Order.price`、`avg_order_amount` 使用 Float，可能产生金额精度问题。

目标应使用：

```text
Numeric(12, 2)
```

### 日期使用 String

`order_date` 和 `last_session_time` 使用字符串，不利于排序、时区和区间查询。

目标应使用带时区的 DateTime：

```text
DateTime(timezone=True)
```

### 手机号作为客户主键

脱敏手机号不适合作为稳定唯一标识：

- 不同用户可能出现相同脱敏形式；
- 用户可能更换手机号；
- 第三方渠道可能没有手机号；
- 多渠道 Session 难以统一。

目标使用独立 `customer_id`，手机号作为属性。正式系统还应区分加密值、哈希和展示用尾号。

### 订单表过度扁平

当前一行订单只能自然表达一个商品，并把商品名直接复制进订单。

Ecom 的 Mock 数据已经展示了一个订单含多个 items 的情况。正式模型至少应区分：

```text
orders
order_items
```

### 物流为一段 Text

`logistics` 无法可靠回答：

- 承运商；
- 运单号；
- 当前状态；
- 预计送达；
- 多个物流事件；
- 拆单后的多个包裹。

后期应增加 shipment 和 shipment_event；第一阶段可以先保留 Text，避免数据库重构阻塞 Multi-Agent。

### 状态缺少约束

订单状态是自由字符串，后期容易出现“运输中、已发货、配送中”等不一致值。应使用应用枚举加数据库约束，或统一状态码。

### Profile 混合权威数据与推断数据

`complaint_count`、`refund_count`、`total_orders` 属于业务统计；`preferred_category` 和 `tags` 属于偏好/标签；`last_summary` 属于会话记忆。

第一阶段可以保留在同一表，但写入路径必须区分：

- 统计字段由业务事件更新；
- 偏好字段由明确用户表达或审核后的抽取更新；
- Agent 不得自由修改权威统计。

### tags 使用逗号字符串

逗号字符串查询、去重和扩展困难。PostgreSQL 中可改为 JSONB/ARRAY；本轮不必优先迁移。

### 缺少审计字段

主要表建议逐步增加：

```text
created_at
updated_at
```

涉及售后写操作的表还需要状态变更和幂等字段。

## 4. 推荐的分阶段数据库方案

不要在 Router 重构前同时大改数据库。

### Phase A：Router/FastPath/Multi-Agent

保持现有四张表，只修代码结构和测试。这样可以隔离架构重构风险。

### Phase B：Session Memory 入库

增加三张核心表：

```text
conversation_session
conversation_message
agent_run
```

#### conversation_session

```text
id
customer_id/visitor_key
channel
domain
intent
stage
slots JSONB
waiting_for
summary
status
created_at
updated_at
expires_at
```

#### conversation_message

```text
id
session_id
role
content
agent_name
created_at
```

#### agent_run

```text
id
request_id
session_id
route_target
intent
confidence
agent_name
llm_call_count
tool_call_count
latency_ms
status
error
created_at
```

详细工具 Trace 可以第一阶段保留为结构化日志，确有分析需求再增加 `tool_call` 表。

### Phase C：业务模型规范化

按真实需求增加：

```text
customer
customer_contact
orders
order_items
shipments
shipment_events
after_sales_request
support_ticket
```

不建议为了简历一次性创建全部空表。只有在对应工具和流程实现时再增加。

## 5. 推荐的最小目标模型

本轮重构真正需要的不是十几张业务表，而是：

```text
保留：faq, product, customer_order, customer_profile
新增：conversation_session, conversation_message
可选：agent_run
```

其中 `agent_run` 如果先用 JSON 结构化日志实现，可以延迟入库。

这能支持：

- 多轮任务恢复；
- 最近消息与摘要；
- 三个 Agent 共享 Session；
- FastPath/Agent 过程统计；
- 后续离线评测。

## 6. Ecom 评测体系包含什么

### EvalCase

Ecom 每条用例包含：

```text
id
description
turns
expected_intent
expected_keywords
expected_requires_human
expected_tools
min_tool_calls
max_tokens
expected_route
```

### RunTrace

运行时记录：

- 实际路由；
- LLM 调用用途、模型、Token、延迟和工具请求；
- 工具参数与工具结果；
- 最终结构化回复；
- 错误。

### Sandbox

Ecom 为每条用例创建独立 Session，关闭 Memory 和 MCP，使用本地 Mock 工具，以获得可复现结果；通过插桩捕获 LLM 和工具调用。

### 双层指标

过程指标包括：

- 工具准确率；
- 工具效率；
- Token 预算；
- Route Match；
- 可选过程合理性 Judge。

结果指标包括：

- Intent Match；
- 关键词覆盖；
- Human Handoff Match；
- 可选回答质量和忠实度 Judge。

## 7. 哪些可以借鉴，哪些不能直接拿

### 可以借鉴并独立实现

- EvalCase 的“输入 + 结果期望 + 过程期望”思想；
- 多轮 turns；
- RunTrace 与评分解耦；
- 每条用例隔离 Session；
- 规则评分和 LLM Judge 分层；
- 一条用例失败不终止整轮评测；
- 生成 JSON 汇总报告。

### 不能原样复用

- Ecom 的订单号是 `ORD-*`，本系统是五位订单号；
- Ecom 工具是 `query_order/query_logistics`，本系统当前是 `order_query`；
- Ecom Route 是 presale/postsale/complaint，本系统是 fast_path/presales/in_sales/aftersales/human；
- Ecom 所有请求通常走 Agent，本系统必须验证 FastPath 零 LLM；
- Ecom 的商品和知识库内容与本系统不同；
- Ecom 代码和 cases 受专有许可限制，不应复制进可能公开的仓库。

## 8. CustomSystem 自有 EvalCase 建议

我们的用例需要额外字段：

```json
{
  "id": "logistics_fastpath_001",
  "description": "完整订单号物流查询应直达",
  "turns": ["订单88002到哪了"],
  "expected_target": "fast_path",
  "expected_intent": "logistics",
  "expected_agent": null,
  "expected_tools": ["order_query"],
  "max_llm_calls": 0,
  "expected_requires_human": false,
  "expected_keywords": ["88002", "物流"]
}
```

建议字段：

```text
expected_target
expected_intent
expected_agent
expected_tools
forbidden_tools
min_tool_calls
max_tool_calls
max_llm_calls
expected_session_state
expected_requires_human
expected_keywords
forbidden_claims
```

## 9. 第一批总评测用例

至少覆盖：

1. 你好 -> FastPath，0 LLM。
2. 退货政策 -> FastPath FAQ，0 LLM。
3. 订单 88001 -> FastPath order_query，0 LLM。
4. 订单 88002 到哪了 -> FastPath logistics，0 LLM。
5. 推荐适合出差的充电宝 -> PresalesAgent。
6. 显示签收但未收到 -> InSalesAgent。
7. 我要退 88001 -> AftersalesAgent，多轮补原因。
8. “充不上电”在活跃退款 Session 中继续售后。
9. 明确要求负责人投诉 -> Human。
10. 物流超时 + 商品损坏 + 拒绝退款 -> AftersalesAgent 或 Human，禁止单纯 FastPath。
11. 数据库不可用 -> 明确失败，禁止虚构。
12. Qdrant 无结果 -> 安全降级。
13. Prompt Injection -> 输入安全层拒绝。
14. 售前 Agent 尝试调用未授权工具 -> 拒绝。

## 10. 最终建议

- 数据库：不参考 Ecom Mock 结构；先保持业务表，记忆阶段增加 Session 与 Message。
- 评测：参考 Ecom 的方法论，从零实现 CustomSystem 自有 EvalCase、Sandbox、Trace、Metrics、Evaluator。
- 许可：不复制 Ecom 源码和数据，以免影响 CustomSystem 后续公开和归属说明。
- 优先级：先建立路由/FastPath/Agent 的无外部依赖测试，再做真实 LLM 的离线总评测。

