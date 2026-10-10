# CustomSystem 重构与换机交接说明

更新时间：2026-09-04

本文是当前工作树的权威交接入口。原始版本基线为 Git 提交 `3517a730f69240e93547b64ddb45f7f6d4e99124`（2026-08-25，Initial import）。当前重构尚未提交，换机包中的源码就是最新版本。

## 一句话结论

CustomSystem 已从“IntentRouter 内部选择并执行七条业务管道”重构为“Router 只决策，FastPath、售前、售中、售后和人工接管同级执行”；三个领域 Agent 共用一套受工具白名单约束的 ReAct 循环，并补齐分层记忆、可观测 Trace、演示数据和类似 Ecom 的系统评测集。

## 原版与当前版的主要差异

| 方面 | 原版 | 当前版 |
|---|---|---|
| 总体编排 | IntentRouter 同时做意图判断和业务执行 | `Router -> FastPath / Presales / In-sales / Aftersales / Human` |
| 管道数量 | 七条业务管道，边界和售前/售中/售后有重叠 | 五个同级执行目标；领域归属与执行方式分离 |
| Router 职责 | 路由、调用工具、生成部分回答混在一起 | 只返回 `RouteDecision`，不执行业务工具 |
| FastPath | 混在旧 Router 的分支里 | 独立同级执行器；确定性回答，零 LLM 调用 |
| Agent | 通用兜底为主 | 售前、售中、售后三个领域 Agent，共用 ReAct 引擎 |
| 工具权限 | 边界较弱 | 每个 Agent 独立 Prompt 和严格工具白名单 |
| 服务入口 | `server.py` 内重复编排 | `CustomerServiceEngine` 统一供 FastAPI 与评测调用 |
| 会话记忆 | 多处更新，Agent 历史可能混入运行时提示 | Session 状态、原始消息历史、长期画像、Trace 四层分离 |
| 多轮连续性 | 短回复可能被关键词重新路由 | 活跃领域、阶段、等待字段和槽位驱动后续路由 |
| 身份解析 | 手机尾号和画像主键可能分裂 | 手机尾四位解析到规范客户画像 |
| 观测 | 以简单内存统计为主 | 结构化 `RequestTrace`，记录路由、工具、LLM、延迟和状态 |
| Qdrant | 固定本地路径，容易产生锁冲突 | `QDRANT_PATH` 可隔离，退出时显式关闭客户端 |
| 自动化验证 | 原版没有完整评测闭环 | 69 个测试、30 条业务评测、30 条 HTTP 黑盒、24 条检索金标 |

项目没有使用 LangChain。当前核心是自研 Router、ReAct AgentLoop、ToolRegistry、SQLAlchemy、PostgreSQL、BGE 和嵌入式 Qdrant。MCP 仍是后续工具适配层，没有为了展示技术名词而提前接入。

## 当前请求流程

```text
用户输入
  -> Router（规则优先，必要时 LLM 兜底）
  -> RouteDecision(target, intent, confidence, reason)
       |-> FastPath：寒暄、FAQ、简单商品/完整订单查询
       |-> Presales Agent：推荐、比较、购买咨询
       |-> In-sales Agent：订单、支付、物流等履约问题
       |-> Aftersales Agent：退款、退货、损坏、投诉
       `-> Human：高风险、低置信度或服务异常
  -> SessionMemory + CustomerProfile + RequestTrace
  -> API 响应
```

FastPath 与三个 Agent 是同级关系，而不是售前 Agent 的子路径。原因是 FAQ、订单、物流等确定性请求并不只属于售前；独立 FastPath 能统一实现低延迟、低成本和可预测输出。

关键实现：`core/router.py` 只产生路由决策；`core/fast_path.py` 实现确定性快速路径；`core/domain_agents.py` 定义三个领域 Agent；`core/loop.py` 是共享 ReAct 循环；`core/service.py` 是唯一业务编排入口；`core/session_memory.py` 管理状态和消息；`core/trace.py` 保存结构化调用轨迹；`server.py` 仅负责 HTTP 和生命周期。

## 当前记忆设计

当前设计刻意保持四层，而不是堆砌更多“记忆模块”：

1. Session 状态：当前 domain、intent、phase、`waiting_for` 与业务槽位，服务于多轮任务。
2. 消息历史：保存原始 user/assistant 对话；FastPath、Agent、Human 三条路径都会写入。
3. 客户画像：PostgreSQL 中的长期偏好、最近意图、摘要及重要事件。
4. Agent 调用轨迹：单独的 Trace，不混进对话历史，不作为用户记忆回灌 Prompt。

已修复跨领域切换残留订单槽位、只存在 `.meta.json` 时无法恢复、内部运行时上下文污染历史、退款事件重复写入，以及售后模糊追问丢失领域等问题。明确结束语会触发长期摘要。

## 数据库与知识库

当前 ORM 仍采用 PostgreSQL，核心实体为 Product、Order、Faq、CustomerProfile。没有为了重构盲目复制 Ecom 的字段；本轮优先修复编排、记忆一致性和评测闭环。

- 当前演示规模：34 个商品、24 个订单、36 条 FAQ、4 个客户画像。
- 基础数据位于 `data/*.json`，扩展数据由 `scripts/seed_demo_data.py` 幂等写入。
- `scripts/export_migration_data.py` 可在 PostgreSQL 正常运行时导出逻辑 JSON 快照。
- 本换机包同时保留 `pgdata/` 冷备目录，但只建议在相同 PostgreSQL 大版本下恢复；跨版本优先新建数据库并重新 seed。
- BGE 模型目录随包保留；Qdrant 索引未打包，可从数据库内容重新建立。

当前没有 Alembic 迁移链。若后续改变 ORM 表结构，首先引入 Alembic，不要继续依赖自动建表处理生产升级。

## 测试与评测结果

最后一次完整验收结果：pytest 69 passed；确定性业务评测 30/30；真实 HTTP 黑盒评测 30/30；RAG 金标 24 条（商品 12、FAQ 12），Recall@1、Recall@3、MRR 均为 100%。HTTP 评测覆盖真实 Router、FastPath、DeepSeek Agent、PostgreSQL、Qdrant、Trace 和 Session。

- `evaluation/cases.json`：30 条业务评测。
- `evaluation/retrieval_cases.json`：24 条检索金标。
- `workspace/eval_report.json`：离线业务报告。
- `workspace/live_eval_report.json`：真实 HTTP 报告。
- `workspace/retrieval_eval_report.json`：召回报告。

```powershell
python -m pytest -q
python scripts/run_deterministic_eval.py
python scripts/run_live_api_eval.py
python scripts/run_retrieval_eval.py
```

报告中的 100% 是当前演示金标集上的回归基线，不代表真实生产流量必然达到 100%。后续应持续加入反例、歧义问法、噪声和业务新数据。

## 换机恢复

推荐 Python 3.11。旧电脑主要使用 `D:\anaconda3\envs\customsystem`；部分早期文档曾写作 `css`，新电脑环境名可以自行选择，代码不依赖名称。

```powershell
cd D:\agent\CustomSystem
conda create -n customsystem python=3.11 -y
conda activate customsystem
pip install -r requirements.txt
Copy-Item .env.example .env
```

编辑 `.env`，至少填写 `DEEPSEEK_API_KEY`、`DATABASE_URL`、随机的 `ADMIN_TOKEN`，必要时设置独立的 `QDRANT_PATH`。真实 `.env` 因含密钥不会进入压缩包，请通过密码管理器单独迁移。

新建 PostgreSQL 数据库后，先启动一次服务让 ORM 建表并写入基础数据，再运行扩展 seed：

```powershell
python server.py
# 首次初始化结束后停止服务，再执行：
python scripts/seed_demo_data.py
python server.py
```

访问：聊天页 `http://127.0.0.1:8765/`，后台 `/admin`，健康接口 `/api/health`，Swagger `/docs`。

## 已知边界与后续顺序

- Session/Message 目前仍为本地 JSONL/元数据文件，不是 PostgreSQL 持久化。
- Trace 当前是内存结构，重启后清空。
- MCP 尚未接入；后续应在 ToolRegistry 外增加 adapter，保持 Router 和 Agent 不感知协议。
- 嵌入式 Qdrant 同一路径不能被多个进程同时打开；并发测试必须用不同 `QDRANT_PATH`。
- `/api/health` 不是完整数据库就绪探针；换机后必须再发送真实 `/api/chat` 请求验证。
- 管理令牌方案适合演示，不应直接暴露公网。

建议后续顺序：先保持当前 30+24 条金标为回归门槛，再将 Session/Trace 入库并引入 Alembic，最后接 MCP 工具适配器。不要重新拆回七条相互重叠的业务管道。

## 换机包边界

压缩包保留 `D:\agent` 下各项目源码，以及 CustomSystem 的本地 BGE 模型、测试集、评测报告和 `pgdata` 冷备。排除所有 `.env` 和常见密钥文件、`.git`、Python/pytest/IDE 缓存、`node_modules`、虚拟环境、会话和服务日志、可重建的 Qdrant 索引及压缩包目录本身。压缩完成后，以同目录的 SHA-256 文件验证传输完整性。
