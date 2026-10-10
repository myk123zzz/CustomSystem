# CustomSystem 最新系统说明

更新时间：2026-10-03

本文描述 `D:\agent\CustomSystem` 当前实际运行的架构和功能。代码实现以本文所列入口为准。`D:\agent\agent1\02-工程实践\项目.md` 是通用面试资料，其中的 LangGraph、Milvus、Neo4j、GraphRAG、BM25、RRF 和 Cross-Encoder Rerank 不等同于 CustomSystem 已实现能力。

## 1. 项目定位

CustomSystem 是面向电商客服场景的可评测 Multi-Agent 系统。系统通过统一 Router，在确定性 FastPath、三个专业 Agent 和人工接管之间选择一个执行目标。

当前版本已经完成业务管线整合：原先由 IntentRouter 内部选择并执行的七条业务管线，已收敛为一个统一编排入口和五个同级执行目标。

## 2. 当前请求管线

```text
POST /api/chat
  -> 输入校验、会话和客户画像加载
  -> CustomerServiceEngine
      -> Router：只判断意图、目标和置信度
          |-> FastPath
          |-> Presales Agent
          |-> In-sales Agent
          |-> Aftersales Agent
          `-> Human
  -> Session Memory + Customer Profile + Request Trace
  -> API 响应
```

五个执行目标：

| 目标 | 负责场景 | 执行特点 |
|---|---|---|
| FastPath | 寒暄、FAQ、简单商品查询、完整订单及物流查询 | 确定性执行，通常不调用 LLM |
| Presales Agent | 商品推荐、对比、选购咨询 | 共享 ReAct 循环，使用售前工具白名单 |
| In-sales Agent | 订单、支付、物流及缺失信息补充 | 共享 ReAct 循环，使用售中工具白名单 |
| Aftersales Agent | 退款、退货、换货、损坏及售后问题 | 共享 ReAct 循环，使用售后工具白名单 |
| Human | 明确投诉、高风险请求、低置信度或系统异常 | 调用人工接管工具 |

FastPath 与三个领域 Agent 是同级执行目标。FastPath 无法安全处理时，才降级到对应领域 Agent 或人工。一次请求只执行一个最终目标。

## 3. 统一编排与关键代码

| 文件 | 职责 |
|---|---|
| `core/service.py` | 唯一业务编排入口 `CustomerServiceEngine` |
| `core/router.py` | 产生 `RouteDecision`，不执行业务工具 |
| `core/fast_path.py` | FAQ、简单商品、订单和物流等确定性流程 |
| `core/domain_agents.py` | 售前、售中、售后三个 Agent 定义及工具白名单 |
| `core/loop.py` | 三个领域 Agent 共用的 ReAct 循环 |
| `core/session_memory.py` | 会话状态、槽位和原始消息历史 |
| `core/trace.py` | 路由、工具、LLM 次数、延迟和状态轨迹 |
| `server.py` | FastAPI 接口、依赖装配和生命周期管理 |

FastAPI、离线评测和 HTTP 黑盒评测共用 `CustomerServiceEngine`，避免线上接口和测试沙箱存在两套业务逻辑。

## 4. 当前 RAG 检索管线

```text
FAQ 请求
  -> PostgreSQL ILIKE 问题/分类匹配
  -> 未命中时降级到 BGE 向量检索

语义请求
  -> bge-base-zh-v1.5 编码 Query
  -> Qdrant FAQ Collection + Product Collection 分别召回
  -> 合并候选并按余弦相似度降序排序
  -> Top-3 返回给 Agent
```

当前已实现：

- 本地 `bge-base-zh-v1.5`，Query 和 Document 使用不同编码方法；
- Qdrant 嵌入式向量库；
- FAQ 与商品独立 Collection；
- PostgreSQL 关键词查询失败后自动降级到语义召回；
- Recall@1、Recall@3、MRR 检索评测；
- 24 条检索金标，当前交接基线为 Recall@1、Recall@3、MRR 100%。

当前未实现：

- BM25 稀疏检索；
- Dense、Sparse、Graph 三路并发召回；
- RRF 融合排序；
- Cross-Encoder 或 `bge-reranker` 精排；
- Milvus、Neo4j 和 GraphRAG。

因此，当前按余弦相似度排序属于向量召回排序，不能表述为独立 Rerank 精排。模型目录 README 中出现的 reranker 示例是 BGE 官方说明，不代表本项目已经接入该模型。

## 5. 记忆与可观测性

系统保留四类相互分离的数据：

1. Session 状态：领域、意图、阶段、等待字段和业务槽位。
2. 消息历史：保存原始 user/assistant 对话。
3. Customer Profile：PostgreSQL 中的长期偏好、最近意图、摘要和重要事件。
4. Request Trace：记录目标、意图、工具、LLM 次数、耗时、状态和错误，不混入用户对话历史。

当前 Session 和消息记录仍使用本地文件，Trace 使用内存存储，Customer Profile 使用 PostgreSQL。

## 6. 运行环境

当前设备配置：

| 项目 | 当前值 |
|---|---|
| 项目目录 | `D:\agent\CustomSystem` |
| Python | Conda 环境 `css`，Python 3.11 |
| Python 路径 | `C:\Users\Mike\.conda\envs\css\python.exe` |
| 数据库 | Docker 容器 `customsystem-postgres` |
| PostgreSQL 端口 | `55432` |
| Web 端口 | `9000` |
| 配置文件 | `.env` |
| LLM | DeepSeek Chat |

当前 Windows 将 `8757-8856` 设为 TCP 排除端口范围，因此原文档中的 `8765` 无法绑定。本机使用 `9000`。

访问地址：

- 聊天页面：`http://127.0.0.1:9000/`
- 管理后台：`http://127.0.0.1:9000/admin`
- 健康接口：`http://127.0.0.1:9000/api/health`
- Swagger：`http://127.0.0.1:9000/docs`

启动命令：

```powershell
docker start customsystem-postgres
Set-Location D:\agent\CustomSystem
C:\Users\Mike\.conda\envs\css\python.exe -m uvicorn server:app --host 127.0.0.1 --port 9000
```

`/api/health` 只证明 HTTP 服务已启动，不代表数据库链路可用。启动后还应调用一次 `/api/chat`，例如查询“退货政策是什么？”。

## 7. 当前验证基线

- pytest：69 passed；
- 确定性业务评测：30/30；
- 历史真实 HTTP 黑盒评测：30/30；
- RAG 金标：24 条；
- Recall@1、Recall@3、MRR：当前金标集上均为 100%；
- 换机后已验证首页、健康接口、FAQ、订单查询、数据库、Trace 和真实 DeepSeek 调用。

这些结果是当前演示数据和版本化金标集上的回归基线，不代表生产流量中的所有问题均能达到相同效果。

## 8. 后续优化顺序

1. 扩充检索难例、歧义问法和无答案样本，记录 Top-10 候选排名。
2. 增加相关性阈值、拒答或澄清机制，避免无关结果被强制返回。
3. 对价格、容量、接口等商品条件先做结构化过滤，再做语义排序。
4. 当正确答案经常出现在 Top-10 但进不了 Top-3 时，再引入 Cross-Encoder Rerank，并通过 A/B 评测决定是否进入主流程。
5. 数据规模扩大且关键词召回成为明显短板后，再评估 BM25 与 RRF。
6. Session 和 Trace 入库并引入 Alembic，最后接入 MCP 工具适配层。

## 9. 对外介绍建议

可以准确表述为：

> CustomSystem 将原有七条重叠客服管线整合为统一 Router、独立 FastPath、售前/售中/售后三个领域 Agent 和人工接管五个同级目标。三个 Agent 共用受工具白名单约束的 ReAct 循环。检索采用 PostgreSQL 关键词优先、BGE + Qdrant 语义召回降级，并使用 Recall@1、Recall@3 和 MRR 建立回归基线。当前尚未接入独立 Cross-Encoder Rerank，是否引入将由更大规模难例评测决定。

