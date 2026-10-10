# CustomSystem（小闪）

面向电商客服场景的可评测 Multi-Agent 系统。统一 Router 在确定性 FastPath、三个专业 ReAct Agent 和人工客服之间做一次执行决策。

## 架构

```text
POST /api/chat
  → 安全校验、客户画像加载
  → CustomerServiceEngine
      → Router（只分类和选择目标，不执行工具）
          ├─ FastPath（寒暄 / FAQ / 完整订单与物流，0 LLM）
          ├─ Presales Agent
          ├─ In-sales Agent
          ├─ Aftersales Agent
          └─ Human
      → SessionMemory + RequestTrace
  → Agent 结果置信度评估
  → HTTP 响应
```

三个专业 Agent 共享一个 ReAct 循环，使用独立 System Prompt 和严格工具白名单：

| 目标 | 典型请求 | 工具范围 |
|---|---|---|
| FastPath | 寒暄、FAQ、带完整编号的订单/物流 | 固定工具链 |
| Presales | 推荐、对比、选购 | FAQ、RAG |
| In-sales | 缺少信息的订单和物流问题 | 订单、FAQ、人工 |
| Aftersales | 退款、换货、质量问题 | 订单、FAQ、人工 |
| Human | 明确投诉、要求负责人或无法安全处理 | 人工接管 |

这里的 Multi-Agent 指多个有清晰业务边界的专业 Agent，而不是让 Agent 自由互相聊天。每次请求只执行一个目标，成本和轨迹更容易控制。

## 关键设计

- Router 与 Execution 合并为一个决策组件，但 Router 不调用业务工具。
- FastPath 和三个 Agent 同级，不是售前 Agent 的内部步骤。
- FastPath 未解决时只降级到指定专业 Agent 或人工，不生成猜测答案。
- ReAct 循环由三个 Agent 复用，工具注册表通过子集形成运行时白名单。
- Session Memory 保存业务域、意图、阶段、待补字段和槽位。
- Customer Profile 保存跨会话的结构化客户画像。
- RequestTrace 与记忆分离，记录 target、intent、工具、LLM 次数、延迟和状态。
- Qdrant 继续作为向量存储，并可通过 `QDRANT_PATH` 切换路径。
- MCP 预留在工具适配层，后续接入不改变 Router 或 AgentLoop。

项目没有依赖 LangChain。Router、ReAct、上下文、工具、记忆和评测均为项目自身实现。

## 技术栈

| 层次 | 技术 |
|---|---|
| API | FastAPI、Pydantic、Uvicorn |
| Agent | 自研 Router、FastPath、ReAct AgentLoop、ToolRegistry |
| LLM | DeepSeek Chat（OpenAI 兼容接口） |
| 数据库 | PostgreSQL、SQLAlchemy 2.0、asyncpg |
| RAG | sentence-transformers、本地 BGE、Qdrant |
| 记忆 | ContextStore、JSONL SessionStore、CustomerProfile |
| 评测 | pytest、自有 EvalCase、Sandbox、Metrics、Trace |

## 记忆模型

```text
Session Memory（会话内）
  domain / intent / phase / waiting_for / slots / messages / summary

Customer Memory（跨会话）
  phone / VIP / preferences / complaint_count / conversation summaries

Request Trace（可观测性，不属于记忆）
  route / tools / llm_calls / latency / status / error
```

当前 Session 历史使用 JSONL，Customer Profile 使用 PostgreSQL，Trace 使用内存环形存储。是否将 Session 与 Trace 迁入 PostgreSQL，应由真实查询需求和评测结果决定。

## 测试与评测

项目借鉴 Ecom 的“案例—沙箱—轨迹—指标—报告”方法，但数据集和实现完全独立。当前包含 30 条版本化业务 EvalCase，并另外覆盖安全校验与 HTTP 端到端测试。指标包括路由、工具、LLM 预算、Session 状态、人工接管和分类通过率。

运行确定性测试：

```powershell
D:\anaconda3\envs\customsystem\python.exe -m pytest -q
```

生成完全离线、可复现的 JSON 评测报告：

```powershell
D:\anaconda3\envs\customsystem\python.exe scripts\run_deterministic_eval.py
```

配置外部服务后运行真实全链路评测：

```powershell
D:\anaconda3\envs\customsystem\python.exe scripts\run_eval.py
```

对正在运行的生产装配执行 HTTP 黑盒评测：

```powershell
D:\anaconda3\envs\customsystem\python.exe scripts\run_live_api_eval.py
```

黑盒报告输出到 `workspace/live_eval_report.json`，并按完整多轮轨迹累计工具和 LLM 调用。

运行真实 Qdrant 检索评测：

```powershell
D:\anaconda3\envs\customsystem\python.exe scripts\run_retrieval_eval.py
```

检索集包含 12 条商品查询和 12 条 FAQ 查询，输出 Recall@1、Recall@3、MRR 到 `workspace/retrieval_eval_report.json`。

评测不全通过时脚本返回非零退出码，可接入 CI。

## 启动

```powershell
Copy-Item .env.example .env
# 在 .env 中填写真实配置后启动
python server.py
```

主要环境变量：

```dotenv
DEEPSEEK_API_KEY=...
DATABASE_URL=postgresql+asyncpg://...
QDRANT_PATH=workspace/qdrant_data
ADMIN_TOKEN=...
HOST=127.0.0.1
PORT=8765
```

- 聊天页面：`http://localhost:8765/`
- 管理页面：`http://localhost:8765/admin`
- 健康检查：`GET /api/health`
- 对话接口：`POST /api/chat`
- Trace：`GET /api/admin/traces`（需要管理令牌）

真实 `.env`、会话、日志、数据库目录、Qdrant 索引和本地模型均不提交 Git。完整发布边界和提交前检查见 [SECURITY.md](SECURITY.md)。

## 项目结构

```text
core/
  router.py             # 统一路由决策
  fast_path.py          # 确定性零 LLM 流程
  domain_agents.py      # 三个专业 Agent
  loop.py               # 共享 ReAct 循环
  service.py            # API 与测试共用的业务编排
  session_memory.py     # 会话任务状态
  trace.py              # 请求轨迹
evaluation/
  cases.json            # 版本化案例
  dataset.py            # EvalCase
  sandbox.py            # 多轮执行沙箱
  metrics.py            # 路由、工具、预算指标
scripts/run_eval.py     # 真实全链路评测入口
tests/                  # 单元、集成、评测与 HTTP 端到端测试
docs/                   # 重构、数据库和测试文档
```

## 当前边界

Multi-Agent 主链路、精简记忆、Trace、离线评测和 API 端到端验证已经完成。以下是有意延后的生产化扩展：

- MCP 外部工具传输适配；
- Session、Message 和 Trace 的 PostgreSQL 持久化；
- 使用真实 DeepSeek、PostgreSQL 和生产知识库的环境验收。

详见[重构计划](docs/REFACTOR_PLAN.md)、[数据库与评测审查](docs/DATABASE_AND_EVALUATION_REVIEW.md)和[实施状态](docs/IMPLEMENTATION_STATUS.md)。
