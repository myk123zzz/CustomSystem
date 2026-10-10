# 重构实施状态

更新时间：2026-08-26

## 已完成

### Phase 0：环境与基线

- 创建 Conda 环境 `D:\anaconda3\envs\customsystem`（Python 3.11）。
- 增加 pytest、pytest-asyncio 和 httpx 测试环境。
- 增加 Router、Session、ToolRegistry、AgentLoop 基线测试。

### Phase 1：新 Router

- 新增 `RouteDecision`。
- 新增五个执行目标：fast_path、presales、in_sales、aftersales、human。
- 保留规则优先、LLM 兜底和活跃 Session 优先。
- Router 不再执行工具。
- 保留管理后台使用的旧统计字段，并增加 target/intent 统计。

### Phase 2：FastPath

- 寒暄、FAQ、简单商品、完整订单和物流查询使用固定工作流。
- FastPath 不依赖 Provider。
- FAQ/商品未解决时降级到对应 Agent。
- 订单服务异常时安全转人工，不允许 LLM 推测。

### Phase 3：专业 ReAct Agent

- 保留一个共享 AgentLoop。
- 增加售前、售中、售后三个 Agent 定义。
- 增加独立 System Prompt。
- 增加严格工具白名单。
- `/api/chat` 已切换到新 Router、FastPath 和三个 Agent。

### 工程修复

- Qdrant 路径支持通过 `QDRANT_PATH` 隔离。
- FastAPI lifespan 退出时释放 Qdrant 客户端。
- 保留原有订单号边界正则修复。

### Phase 4（第一部分）：Session Memory 与 Trace

- 新增 `SessionMemoryManager`，由 RouteDecision 驱动状态更新。
- Session 上下文统一为 domain、intent、phase、waiting_for 和 slots。
- 多轮售后补订单号时保留原 Agent，并从下一轮消息提取实体。
- 删除服务入口中重复的售后/订单关键词重分类逻辑。
- 新增 RequestTrace 与内存 TraceStore。
- Trace 记录最终 target、intent、工具、LLM 次数、延迟和状态。
- 新增 `/api/admin/traces` 管理接口。

### Phase 4（第二部分）：统一业务引擎与离线评测

- 新增 `CustomerServiceEngine`，FastAPI 与测试共用同一条真实编排链路。
- `server.py` 不再重复实现 Router、FastPath、Agent、Memory 和 Trace 分支。
- 新增独立的 EvalCase、EvaluationSandbox、Metrics 与版本化 JSON 数据集。
- 评测覆盖五个目标、工具约束、LLM 调用预算及多轮售后连续性。
- 新增 `scripts/run_eval.py`，可在配置好数据库和模型后执行真实全链路评测。
- 增加 HTTP 端到端测试，验证 `/api/chat` 的 FastPath 与 Trace 均来自统一引擎。
- 版本化案例已通过真实 Router、SessionMemory 和 CustomerServiceEngine 的总评测。
- 修复“商品坏了，想售后”未进入售后 Agent、后续订单号丢失业务上下文的问题。

### Phase 4（第三部分）：记忆一致性收口

- FastPath、Human 与 Agent 现在都会保存原始 user/assistant 对话历史。
- Agent 历史不再持久化内部运行时上下文，避免污染后续 Prompt 和摘要。
- Agent 每轮从统一 SessionStore 刷新，能够读取中间 FastPath 产生的消息。
- 仅有 `.meta.json` 的 Session 也可在服务重启时恢复。
- 跨业务域切换时清除不相关的订单、物流和售后动作槽位。
- 手机后四位可解析到已有客户画像主键，避免重复画像。
- 正常交互更新最近意图；退款事件按 Session 去重；明确结束语触发长期摘要。

### Phase 5：Ecom 风格总评测集

- EvalCase 从 9 条扩充至 30 条，按 fast_path、presales、in_sales、aftersales、memory、handoff 和 fallback 分层。
- 增加 description、category、工具次数、人工接管、Session phase、必需槽位与禁用槽位契约。
- 总报告增加路由、工具、LLM 预算、Session、人工接管和分类通过率。
- 新增完全离线的 `scripts/run_deterministic_eval.py`，生成 `workspace/eval_report.json`。
- 新增输入安全、Prompt Injection、长度限制和管理接口鉴权测试。
- 扩展测试发现并修复售后正常阶段缺失、售后模糊追问丢失业务域和退款动作被覆盖的问题。

## 当前验证

- pytest：69 passed。
- 离线总评测：30/30，所有指标与分类通过率均为 100%。
- 真实 HTTP 黑盒评测：30/30；真实 Router、FastPath、DeepSeek Agent、PostgreSQL、Qdrant、Trace 与 Session 指标均为 100%。
- 新增 `scripts/run_live_api_eval.py` 与 `workspace/live_eval_report.json`，多轮案例按完整 RunTrace 聚合。

### Phase 6：RAG 召回评测与数据扩充

- PostgreSQL 扩充至 34 个商品、24 个订单、36 条 FAQ、4 个客户画像。
- 新增 24 条检索金标案例：商品 12 条、FAQ 12 条，包含同义改写和相似条目干扰。
- 新增 Recall@1、Recall@3 与 MRR 指标及独立 JSON 报告。
- 当前金标集总体、商品、FAQ 的 Recall@1/3 与 MRR 均为 100%。
- 新增检索数据集结构和指标公式单元测试。
- Python compileall：通过。
- git diff --check：通过，仅有 Git 的 LF/CRLF 提示。
- `/api/chat` 问候冒烟测试：HTTP 200，命中 FastPath，零 LLM。

## 有意延后的生产化扩展

- Session/Message 尚未迁移 PostgreSQL。
- Trace 当前为内存结构化记录，尚未入库。
- MCP 尚未接入。
- 直接启动独立评测进程时，当前 shell 的 PostgreSQL 默认角色仍不可用；已通过运行中生产 API 完成等价且更真实的黑盒验收。
- README 仍主要描述旧版七管道，需要在架构稳定后统一更新。

## 下一阶段

1. 用真实 DeepSeek、PostgreSQL 与知识库运行并扩充 Eval 数据集。
2. 根据评测结果再决定 Session/Message 与 Trace 的数据库迁移。
3. 以工具适配层接入 MCP，保持 Router 与 Agent 不感知传输协议。
