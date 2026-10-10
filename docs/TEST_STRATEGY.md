# CustomSystem 测试与总体验收方案

## 1. 目标

最终测试覆盖范围参考 Ecom 的 Router、ReAct、RAG、Memory、Multi-Agent、MCP 和 Evaluation，但增加 CustomSystem 特有的 FastPath 与零 LLM 调用验证。

测试分四层：

```text
单元测试
  -> 组件集成测试
  -> API 端到端测试
  -> 离线评测集
```

## 2. 测试环境

- Conda Python 3.11。
- pytest + pytest-asyncio。
- 单元测试默认使用 Fake Provider、Fake Tool、Fake KB 和内存 SessionStore。
- 默认测试禁止访问真实外部 LLM。
- PostgreSQL、Qdrant、真实模型放入可选 integration 标记。

建议标记：

```text
unit
integration
e2e
external
```

CI 默认执行 `unit + integration`，本地完整环境再执行 `e2e + external`。

## 3. 单元测试

### Router

- 寒暄 -> fast_path。
- 明确 FAQ -> fast_path。
- 完整订单号 -> fast_path/order_query。
- 订单号紧邻中文仍能提取。
- 手机号不能误识别为订单号。
- 完整物流查询 -> fast_path/logistics。
- 缺少订单号的物流异常 -> in_sales。
- 商品推荐 -> presales。
- 退款申请 -> aftersales。
- 明确投诉/人工 -> human。
- 规则未命中 -> Fake LLM 分类。
- LLM 输出非法标签 -> 稳定降级。
- 活跃 Session -> 原 Agent，不重新自由路由。

### FastPath

- 每个 intent 只调用预期工具。
- FastPath 不调用 Provider。
- 缺少必要实体不会执行工具。
- FAQ SQL 未命中后调用 RAG。
- 工具错误不被当作成功答案。
- 有副作用动作不由 FastPath 自动执行。

### Agent Runtime

- LLM 无工具调用时直接结束。
- 单次工具调用后继续生成最终回复。
- 多个只读工具可以并行。
- 有副作用工具必须串行。
- 工具参数缺失时返回可修正错误。
- LLM 超时、Provider error、空回复、最大迭代都有降级。
- 工具结果长度限制和历史裁剪有效。

### Agent 权限

- 售前 Agent 看不到订单写操作。
- 售中 Agent 看不到退款写操作。
- 售后 Agent 只看到允许的工具。
- 未授权工具调用被拒绝。

### Session 与画像

- 等待订单号时下一轮回到原 Agent。
- 收到所需信息后更新 slots。
- 流程结束后恢复 normal。
- Session TTL/恢复行为正确。
- 画像计数只在确定性事件后更新。
- 摘要失败有降级结果。

## 4. 组件集成测试

### 路由 + FastPath

输入真实 RouteDecision，通过 Fake ToolRegistry 验证：

- 回复内容；
- 工具名和参数；
- LLM 调用次数为 0；
- Trace target 为 fast_path。

### 路由 + Agent

使用脚本化 Fake Provider：

```text
第一次返回 tool_call
第二次返回 final answer
```

验证：

- 选择正确 Agent；
- Agent 只能看到白名单工具；
- 工具结果被送回 Provider；
- Session 保存最终消息；
- Trace 记录完整调用链。

### 多轮流程

示例退款：

```text
我要退订单88001
  -> aftersales
  -> 等待 refund_reason

充不上电
  -> 继续 aftersales
  -> 填充 refund_reason
  -> 查询政策/转人工或提交申请
```

## 5. API 端到端测试

通过 FastAPI ASGI Client 测试 `/api/chat`：

- 安全校验；
- FastPath 回复；
- 三个 Agent 请求；
- 多轮 Session；
- 人工接管；
- 管理统计；
- 服务依赖失败降级。

为了使 API 可测试，后续需要支持依赖注入，避免导入 `server.py` 时强制初始化真实 Qdrant、模型和数据库。

## 6. 离线总评测集

建议建立 JSON 用例集，每条包含：

```json
{
  "id": "route_001",
  "turns": ["订单88001到哪了"],
  "expected": {
    "target": "fast_path",
    "intent": "logistics",
    "tools": ["order_query"],
    "max_llm_calls": 0,
    "reply_keywords": ["88001", "物流"]
  }
}
```

具体字段、与 Ecom 的许可边界及第一批用例清单见 `DATABASE_AND_EVALUATION_REVIEW.md`。

覆盖类别：

- 寒暄与 FAQ；
- 商品查询、推荐和比较；
- 订单、物流和履约异常；
- 退款、换货和售后补参；
- 一般投诉与高风险投诉；
- 多意图与模糊表达；
- 外部服务错误；
- Prompt Injection 与超长输入。

## 7. 过程与结果双层评价

### 过程指标

- target 是否正确；
- intent 是否正确；
- 工具是否正确；
- 工具参数是否正确；
- 是否误用 LLM；
- 是否进入正确 Agent；
- 是否正确更新 Session；
- 是否错误执行高风险写操作。

### 结果指标

- 回复包含必要事实；
- 不包含工具结果以外的订单事实；
- 是否解决问题或正确转人工；
- 是否提出必要追问；
- 可选 LLM Judge 评价清晰度和忠实度。

规则指标优先，LLM Judge 只用于难以机械判断的回答质量。

## 8. 与 Ecom 的区别

Ecom 的测试重点是 Agent 能否完成工具调用、MCP、RAG、Memory 和多 Agent 路由。

本系统除上述能力外，必须额外验证：

- 简单请求是否正确走 FastPath；
- FastPath 是否真正做到零 LLM 调用；
- FastPath 与 Agent 对相同业务事实的回答是否一致；
- Session 活跃任务是否覆盖新一轮表面意图；
- Router 失败是否安全降级而不是默认误路由。

## 9. 最终发布门槛

- 所有单元测试通过。
- 所有无外部依赖集成测试通过。
- Router target accuracy 达到预设阈值，建议至少 95%。
- FastPath precision 达到预设阈值，建议至少 98%，宁可少命中也不能错误直达。
- 关键高风险用例人工接管召回率 100%。
- 简单查询 LLM 调用次数为 0。
- 无未经工具支持的订单、物流、退款事实。
- Conda 新环境能够按照文档完成安装和测试。
