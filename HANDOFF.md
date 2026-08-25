# CustomSystem 换机与 AI 交接说明

## 1. 项目定位

CustomSystem（速充科技智能客服“小闪”）是一个中文电商客服演示项目。它通过规则优先的意图路由减少 LLM 调用，并结合 PostgreSQL 业务数据、本地 BGE 向量模型、嵌入式 Qdrant、工具调用、会话状态、长期用户画像、置信度评估和人工接管完成客服问答。

现有 `README.md` 已包含详细功能、架构、模块和 API 说明；本文只补充换机运行、真实依赖、审查结论和后续接手信息。

## 2. 主要功能

| 模块 | 功能 |
|---|---|
| IntentRouter | FAQ、订单、物流、售后、投诉等意图分类，简单请求规则直达 |
| AgentLoop | 复杂问题调用 DeepSeek，并支持多轮工具调用 |
| Tools | FAQ 查询、订单查询、RAG 搜索、人工接管 |
| PostgreSQL | FAQ、商品、订单和顾客长期画像 |
| BGE + Qdrant | 中文语义检索；Qdrant 使用本地嵌入式存储 |
| Context/Session | 订单号、意图、会话阶段和 JSONL 会话恢复 |
| Confidence | 评估回复可信度并触发人工关注 |
| WebUI | 用户聊天页和客服监控后台 |

## 3. 换机安装

推荐 Python 3.11。项目压缩包保留 `models/bge-base-zh-v1.5`，因此正常情况下不需要从 Hugging Face 下载模型。

```powershell
cd CustomSystem
conda create -n css python=3.11 -y
conda activate css
pip install -r requirements.txt
Copy-Item .env.example .env
```

编辑 `.env`，至少填写 `DEEPSEEK_API_KEY`、`DATABASE_URL` 和随机的 `ADMIN_TOKEN`。

## 4. PostgreSQL

项目必须连接 PostgreSQL，默认数据库名为 `cssdb`。可以使用本机 PostgreSQL，也可直接运行 Docker：

```powershell
docker run --name customsystem-postgres `
  -e POSTGRES_DB=cssdb `
  -e POSTGRES_USER=css `
  -e POSTGRES_PASSWORD=change-this-password `
  -p 5432:5432 `
  -d postgres:16
```

对应 `.env`：

```text
DATABASE_URL=postgresql+asyncpg://css:change-this-password@127.0.0.1:5432/cssdb
```

启动时 SQLAlchemy 会自动建表，`db/seed.py` 会从 `data/*.json` 写入演示数据，随后建立 Qdrant 索引。

## 5. 启动与验证

```powershell
conda activate css
cd CustomSystem
python server.py
```

访问：

- 聊天页：`http://127.0.0.1:8765/`
- 管理后台：`http://127.0.0.1:8765/admin`
- 健康信息：`http://127.0.0.1:8765/api/health`
- Swagger：`http://127.0.0.1:8765/docs`

后台接口要求 `X-Admin-Token`。如修改了 `.env` 的 `ADMIN_TOKEN`，在浏览器控制台执行以下命令并刷新后台：

```javascript
localStorage.setItem('adminToken', '你的 ADMIN_TOKEN')
```

## 6. API 摘要

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/` | 无 | 聊天页面 |
| POST | `/api/chat` | 无 | `message`、`session_key`，返回客服回复 |
| GET | `/api/health` | 无 | 模型、工具和路由统计；不是数据库就绪探针 |
| GET | `/admin` | 无 | 管理后台页面 |
| GET | `/api/admin/log` | `X-Admin-Token` | 最近 200 条内存对话日志 |
| GET | `/api/admin/stats` | `X-Admin-Token` | 路由、延迟和接管统计 |
| GET | `/api/admin/sessions` | `X-Admin-Token` | 当前会话状态 |

## 7. 数据与打包边界

交付包不包含以下本机运行数据：

- `.env`：包含真实 DeepSeek Key。
- `pgdata/`：本机 PostgreSQL 物理数据，不能作为跨设备备份直接复制。
- `workspace/sessions/`：可能含真实会话内容。
- `workspace/qdrant_data/`、`chroma_data/`：可由种子数据重新生成。
- `__pycache__/` 和其他缓存。

若必须迁移真实 PostgreSQL 数据，请使用 `pg_dump`/`pg_restore`；不要复制正在运行的 `pgdata` 目录。

## 8. 审查结论与已知风险

- 当前代码真实使用 BGE + Qdrant，依赖以 `requirements.txt` 为准；README 中对应架构和安装说明已同步。
- `server.py` 是完整 Web 入口；`main.py` 是较早的命令行演示入口，不包含全部 Web 功能。
- 服务启动时数据库失败只打印警告，`/api/health` 仍可能返回 `status=ok`，排障时必须同时观察启动日志并实际发送一次聊天请求。
- 管理后台仍是简化的开发级令牌方案，不适合直接暴露到公网。
- 项目没有自动化测试。换机后至少执行 Python 编译检查、启动检查、FAQ、订单查询、RAG 和后台接口冒烟测试。
- 启动时会自动建表，没有 Alembic 迁移历史；修改 ORM 前应先引入迁移工具。

## 9. 给后续 AI 的建议提示词

```text
先阅读 README.md 和 HANDOFF.md，再从 server.py 的 lifespan、/api/chat 入口开始追踪调用链。
requirements.txt 代表当前真实依赖，server.py 是完整启动入口。
不要提交或打印 .env；不要把 pgdata 当成可移植数据库备份。
先确认 PostgreSQL 可连接、本地 BGE 模型目录存在，再做实际 HTTP 冒烟测试。
修改路由或 Agent 后同时验证规则直达、工具调用、多轮订单流程和人工接管。
```
