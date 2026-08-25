# 速充科技智能客服平台（小闪）

> 一个工程化的电商智能客服系统——从意图分类到记忆管理，从工具调用到人工兜底。

---

## 目录

- [1. 项目概述](#1-项目概述)
- [2. 设计理念](#2-设计理念)
- [3. 技术栈](#3-技术栈)
- [4. 系统架构](#4-系统架构)
- [5. 核心模块详解](#5-核心模块详解)
  - [5.1 意图路由器（IntentRouter）](#51-意图路由器intentrouter)
  - [5.2 Agent 循环（AgentLoop）](#52-agent-循环agentloop)
  - [5.3 上下文构建器（ContextBuilder）](#53-上下文构建器contextbuilder)
  - [5.4 工具系统（Tools）](#54-工具系统tools)
  - [5.5 RAG 语义搜索](#55-rag-语义搜索)
  - [5.6 记忆系统（三层）](#56-记忆系统三层)
  - [5.7 会话阶段跟踪（SessionContext）](#57-会话阶段跟踪sessioncontext)
  - [5.8 置信度评估（ConfidenceEvaluator）](#58-置信度评估confidenceevaluator)
  - [5.9 安全模块](#59-安全模块)
  - [5.10 持久化（SessionStore）](#510-持久化sessionstore)
  - [5.11 LLM Provider](#511-llm-provider)
  - [5.12 数据库](#512-数据库)
  - [5.13 监控指标](#513-监控指标)
- [6. 完整请求链路](#6-完整请求链路)
- [7. 与 nanobot 的区别](#7-与-nanobot-的区别)
- [8. 项目结构](#8-项目结构)
- [9. 快速启动](#9-快速启动)
- [10. API 文档](#10-api-文档)

---

## 1. 项目概述

速充科技智能客服平台是一个面向电商场景的智能客服系统。用户在 Web 聊天框里提问，系统自动判断意图并分发到不同的处理管线——FAQ 查询、订单查询、物流追踪、售后申请、投诉处理，或者交给 AI Agent 自由对话。

**核心指标**：80%+ 的请求被 Router 直接处理，不经过 LLM，毫秒级响应。

---

## 2. 设计理念

### 不是"让 AI 更聪明"，而是"让系统少用 AI"

很多 Agent 项目的思路是：

```
用户 → LLM → 调工具 → LLM → 回复
```

每条消息都走 LLM，无论多简单。成本高、速度慢、不可控。

我们的思路是：

```
用户 → 分类 → 直达对应管线（6条零 LLM 管线 + 1条 Agent 兜底）
```

只有说不出清的复杂问题才调 LLM。这不是"削弱 Agent"，而是"在正确的场景用正确的工具"。

### 借鉴 nanobot，但不照抄

本项目参考了 [nanobot](https://github.com/nanobot) 的工程模式（AgentLoop、ToolRegistry、ContextBuilder、SessionStore、MemoryConsolidator），但不是基于 nanobot 的二次开发。每一行代码都是自己写的，适配客服场景。

nanobot 是一个通用 Agent 框架（像操作系统），我们的项目是一个垂直客服应用（像 App）。

### 关键设计决策

| 决策 | 理由 |
|------|------|
| 本地 BGE embedding + 嵌入式 Qdrant | 模型随项目保存，兼顾中文语义召回和离线部署，不依赖外部向量服务 |
| JSONL 文件持久化而非仅 PostgreSQL | 开发阶段文件更灵活，后续可迁至 PostgreSQL |
| 结构化画像而非文本摘要 | 客服需要"VIP 等级、投诉 3 次"，不需要"三个月前说过什么" |
| 行为驱动置信度而非 LLM 评估 | 0 token 成本，实时判断 |
| NullPool 数据库连接 | startup 和 uvicorn 在不同事件循环，连接池无法共享 |

---

## 3. 技术栈

| 层次 | 技术 | 用途 |
|------|------|------|
| **Web 框架** | FastAPI + uvicorn | HTTP 服务，异步处理请求 |
| **前端** | HTML + CSS + vanilla JS | 聊天界面，零框架依赖 |
| **LLM** | DeepSeek-chat（OpenAI 兼容 API） | 复杂问题对话 + 意图分类 |
| **数据库** | PostgreSQL + asyncpg + SQLAlchemy 2.0 | FAQ、商品、订单、顾客画像 |
| **语义搜索** | sentence-transformers + Qdrant | 本地 BGE 稠密向量 + 余弦相似度 |
| **持久化** | JSONL（原子写） | 会话历史 + 上下文 |
| **异步** | asyncio（Lock、gather、wait_for） | 并发安全、并行工具、超时控制 |
| **日志** | loguru + print | 调试输出 |
| **环境** | python-dotenv | API Key 管理 |

---

## 4. 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                        前端 (index.html)                     │
│                     POST /api/chat                           │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI (server.py)                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  │
│  │ 安全校验  │→│ 画像加载  │→│ 上下文组装│→│ 路由分发    │  │
│  └──────────┘  └──────────┘  └──────────┘  └─────┬──────┘  │
│                                                   │         │
│                    ┌──────────────────────────────┤         │
│                    ▼                              ▼         │
│  ┌──────────────────────────────┐  ┌──────────────────────┐ │
│  │    IntentRouter (7条管线)     │  │    AgentLoop (ReAct) │ │
│  │                              │  │                      │ │
│  │  greeting → 模板回复          │  │  LLM ⇄ Tools 循环    │ │
│  │  faq → faq_lookup 工具       │  │  · 上下文治理         │ │
│  │  product → rag_search        │  │  · 超时保护           │ │
│  │  order_query → order_query   │  │  · 并行工具执行       │ │
│  │  logistics → order_query     │  │  · 对话历史           │ │
│  │  after_sales → 查订单+Agent  │  │                      │ │
│  │  complaint → 转人工           │  │                      │ │
│  │  complex → Agent 兜底        │  │                      │ │
│  └──────────┬───────────────────┘  └──────────┬───────────┘ │
│             │                                  │             │
│             ▼                                  ▼             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                    工具层 (ToolRegistry)               │   │
│  │  faq_lookup │ order_query │ rag_search │ human_handoff │   │
│  └──────────────────────┬───────────────────────────────┘   │
│                         │                                    │
│  ┌──────────────────────┼──────────────────────────────────┐│
│  │           数据层      │                                   ││
│  │  ┌───────────────────┴──────────────────────────┐       ││
│  │  │ PostgreSQL (FAQ/商品/订单/画像)               │       ││
│  │  │ BGE + 嵌入式 Qdrant (语义搜索)                 │       ││
│  │  │ JSONL 文件 (会话持久化)                        │       ││
│  │  │ 内存 dict (短期上下文)                         │       ││
│  │  └──────────────────────────────────────────────┘       ││
│  └─────────────────────────────────────────────────────────┘│
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  记忆系统 (三层)                                       │   │
│  │  短期: ContextStore (订单号/意图/阶段, TTL 30min)      │   │
│  │  会话: JSONL (user/assistant 交替, 原子写)            │   │
│  │  长期: CustomerProfile (12字段, PostgreSQL)           │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  置信度 + 指标                                         │   │
│  │  ConfidenceEvaluator (行为驱动评分)                     │   │
│  │  Router Stats (per-intent 计数/延迟/命中率)            │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. 核心模块详解

### 5.1 意图路由器（IntentRouter）

**文件**: `core/intent_router.py`

**职责**: 判断用户意图，分发到对应处理管线。这是整个系统的"前台调度"。

**分类策略（三层递进）**:

```
Layer 1 — 正则匹配（0 token）
  ├── 纯 5 位数字 → order_query
  ├── 快递单号格式 (SF/JD/EMS开头) → logistics
  └── 短消息含"你好/在吗/谢谢" → greeting

Layer 2 — 关键词规则（0 token）
  ├── "怎么退/退货政策/能退吗" → faq
  ├── "我要退/帮我退/申请退" → after_sales
  ├── "多少钱/什么配置/推荐" → product
  ├── "物流/快递/到哪了" → logistics
  ├── "投诉/差评/举报" → complaint
  └── "订单/帮我查/看一下" → order_query

Layer 3 — LLM 单次分类（~50 token）
  └── 以上都没命中 → 调 LLM 做 7 选 1 分类（只输出标签，不对话）
```

**7 条处理管线**:

| 管线 | 触发条件 | 处理流程 | LLM 消耗 |
|------|---------|---------|---------|
| `greeting` | 寒暄消息 | 返回模板文案 | 0 |
| `faq` | 政策咨询 | faq_lookup → 返回答案 | 0 |
| `product` | 商品咨询 | rag_search → 返回匹配商品 | 0 |
| `order_query` | 查询订单 | order_query → 返回订单信息 | 0 |
| `logistics` | 查询物流 | order_query(logistics) → 返回物流状态 | 0 |
| `after_sales` | 售后申请 | 查订单 → 反问或交 Agent | 路由层 0 + Agent 完整对话 |
| `complaint` | 投诉 | 标记优先级 → 转人工提示 | 0 |
| `complex` | 复杂问题 | 交给 AgentLoop | 完整 ReAct 对话 |

**会话感知**:
当 Agent 在等待用户回复时（例如 Agent 问了"请提供订单号"），Router 自动跳过分类，消息原样发给 Agent。避免"88001"被 Router 误判为新的订单查询。

---

### 5.2 Agent 循环（AgentLoop）

**文件**: `core/loop.py`

**职责**: 执行 ReAct（Reasoning + Acting）模式——LLM 调工具、执行工具、结果回传、继续推理，直到 LLM 给出最终回复。

**核心流程**:

```
用户消息 + system prompt + 对话历史
        ↓
    上下文治理（每轮 LLM 调用前自动做）
        ↓
    发给 LLM（带 tool definitions）
        ↓
   ┌─ LLM 返回 tool_calls → 执行工具 → 结果追加 → 回到治理步骤
   │
   └─ LLM 返回纯文本 → 结束，返回回复
```

**上下文治理（借鉴 nanobot AgentRunner）**:

| 治理步骤 | 做什么 | 防止什么 |
|---------|--------|---------|
| 孤儿清理 | 删除没有配对 tool_call 的 tool 结果 | 历史裁剪产生的垃圾消息 |
| Microcompact | 6 个以上的老工具结果 → `[xxx 结果已压缩]` | 10 轮前的查库结果占着上下文 |
| 结果截断 | 单条 > 3000 字符就截断 | 一个大 JSON 撑爆上下文窗口 |
| 历史裁剪 | 消息 > 40 条从前面裁剪，保留 system + 最近 | 超出 token 上限 |

**并发安全**:

- 所有 per-request 数据通过函数参数传入，不修改实例变量
- per-session 对话历史用 `asyncio.Lock` 保护
- 多用户同时发消息不会串数据

**并行工具执行**:

当 LLM 一次调用多个工具（如同时查 FAQ + 查订单），用 `asyncio.gather` 并行执行。所有客服工具都是只读的（`concurrency_safe = True`）。

**超时保护**:

LLM 单次调用 120 秒超时（`asyncio.wait_for`），防止请求无限挂起。

---

### 5.3 上下文构建器（ContextBuilder）

**文件**: `context/builder.py`

**职责**: 拼装发给 LLM 的完整 messages 列表。

**设计原则（借鉴 nanobot）**:

```
System Prompt（尽量稳定，可缓存）     User Message（每轮变化）
├── AGENTS.md（身份定义）              ├── [运行时上下文]
├── 顾客画像（长期记忆）               │   · 当前订单号
├── 工具契约（动态生成）               │   · 用户意图
                                       │   · 会话阶段
                                       └── [/运行时上下文]
                                       └── 用户原话
```

**为什么分离**: 
- System prompt 同一顾客连续对话中保持稳定 → provider 可做 prompt caching
- 动态上下文（订单号、意图）每轮都变 → 挂在 user message 上，不破坏 system prompt 缓存

**工具契约动态生成**:

不再硬编码工具列表。从 `ToolRegistry` 读取已注册工具，自动生成描述。新增工具无需修改 ContextBuilder——注册即生效。

---

### 5.4 工具系统（Tools）

**文件**: `tools/base.py`、`tools/registry.py`、`tools/faq_lookup.py`、`tools/order_query.py`、`tools/rag_search.py`、`tools/human_handoff.py`

**设计模式**: 抽象基类 + 注册表模式（借鉴 nanobot）。

**Tool 基类**:

```python
class Tool(ABC):
    name: str              # 工具名（LLM 通过它调用）
    description: str       # 告诉 LLM 什么时候该用
    parameters: dict       # JSON Schema，定义入参格式
    concurrency_safe: bool # 是否可以并行执行

    async def execute(**kwargs) -> str:  # 真正干活的代码
```

**4 个工具**:

| 工具 | 数据来源 | 查询方式 | 返回内容 |
|------|---------|---------|---------|
| `faq_lookup` | PostgreSQL `faq` 表 | ILIKE 模糊匹配 | FAQ 问题 + 答案 |
| `order_query` | PostgreSQL `customer_order` 表 | 精确匹配 order_id | 订单状态/金额/物流 |
| `rag_search` | 嵌入式 Qdrant | BGE 向量余弦相似度 | 语义匹配的 FAQ/商品 |
| `request_human` | 字符串模板 | 无查询 | 转人工提示文案 |

**ToolRegistry**:

```python
registry = ToolRegistry()
registry.register(FaqLookupTool())    # 注册即生效
tools = registry.get_definitions()    # 返回 OpenAI function calling 格式（缓存）
result = await registry.execute("faq_lookup", {"query": "退货"})  # 执行
```

---

### 5.5 RAG 语义搜索

**文件**: `rag/kb_store.py`、`rag/ingest.py`

**技术选型**: 本地 `bge-base-zh-v1.5` + 嵌入式 Qdrant（余弦相似度）。

**为什么使用本地 embedding 模型**:

项目将 BGE 中文模型放在 `models/bge-base-zh-v1.5`，换机时随项目一起迁移，避免运行时从 Hugging Face 下载。若项目内模型不存在，也可通过 `BGE_MODEL_PATH` 指定本地模型，最后才回退到在线模型名。

**向量编码策略**:

查询文本会添加 BGE 检索指令前缀，FAQ 和商品文档不添加前缀；全部向量做 L2 归一化，再由 Qdrant 使用 COSINE 距离检索。

**工作流程**:

```
启动时:
  PostgreSQL faq 表 → 拼接文本 → BGE 批量编码 → Qdrant faq collection
  PostgreSQL product 表 → 拼接文本 → BGE 批量编码 → Qdrant product collection

查询时:
  用户消息 → BGE query 编码 → Qdrant 近邻检索
  → 返回 top-3
```

向量库数据默认保存在 `workspace/qdrant_data`，可由 PostgreSQL 中的 FAQ 和商品数据重新构建。

---

### 5.6 记忆系统（三层）

> 借鉴 nanobot 的分层记忆理念：短期会话元数据、中期对话历史、长期持久化记忆。

#### 第一层：短期记忆（ContextStore）

**文件**: `core/context_store.py`

**存什么**:
- 当前处理的订单号
- 检测到的用户意图
- 会话阶段（normal / collecting_info / handoff）
- Agent 在等待什么信息

**怎么存**:
- 内存 dict，key 为 session_key
- TTL 30 分钟滑动窗口（每次读写自动续期）
- 并发安全的清理接口（`all_keys()` 加 asyncio.Lock）

**用在哪儿**: 每条消息都从 ContextStore 读取当前上下文，注入到 user message 的 `[运行时上下文]` 块。

#### 第二层：会话历史

**文件**: `core/loop.py`（历史管理）、`core/persistence.py`（持久化）

**存什么**: 用户和客服的完整对话（user/assistant 交替，不含 tool 调用中间步骤）。

**怎么存**:
- 内存: `AgentLoop._histories` dict，用 asyncio.Lock 保护
- 磁盘: `workspace/sessions/{safe_key}.jsonl`，每条消息一行 JSON
- 原子写入: 先写 `.tmp`，再 `os.replace()`

**用在哪儿**: 每次 AgentLoop 调用时，从磁盘加载历史 → 注入到 messages 列表（system 和 user 之间）。

#### 第三层：长期画像（CustomerProfile）

**文件**: `core/profile_manager.py`、`db/models.py`

**存什么**（12 个结构化字段）:

```
身份:    phone, name
等级:    vip_level（normal/silver/gold/platinum）
统计:    complaint_count, refund_count, total_orders
偏好:    preferred_category, avg_order_amount
最近:    last_intent, last_summary, last_session_time
标签:    tags（高净值/易投诉/退换敏感/...）
```

**怎么用**:
- 每次对话：`ProfileManager.get_or_create(phone)` 加载 → `to_prompt_text()` → 注入 system prompt
- 自动更新：检测到投诉 → `note_complaint()` → complaint_count +1，≥3 次自动打 `frequent_complainer` 标签
- Router 决策：`is_high_risk()` → True → 优先走人工通道

**记忆整合（MemoryConsolidator）**:

`core/memory.py` — 借鉴 nanobot 的 Dream 系统，但按会话边界触发（而非 token 预算）。

触发时机：低置信度 / 转人工（对话自然结束点）。

```
对话历史 → LLM 摘要（2-3 句）→ 存入 CustomerProfile.last_summary
```

LLM 不可用时自动降级：取第一条用户消息作为摘要。

---

### 5.7 会话阶段跟踪（SessionContext）

**文件**: `core/session_state.py`

**不是复杂的状态机**，只是一个标记位。

```
normal          → 正常聊天，Router 正常工作
collecting_info → Agent 在等用户提供信息（订单号/手机号），Router 跳过
handoff         → 已转人工
```

**为什么需要它**:

```
场景：Agent 问"请提供订单号"，用户回"88001"

问题："88001" 匹配订单号格式 → Router 会把它当成新的订单查询 → 查库返回
结果：Agent 永远收不到用户的订单号回复

解决：Agent 问问题后 → 设 phase = collecting_info
     Router 检查到 collecting_info → 自动跳过分类 → 消息直达 Agent
```

---

### 5.8 置信度评估（ConfidenceEvaluator）

**文件**: `core/confidence.py`

**评分方式**: 行为驱动——检查 Agent 做了什么，不是它说了什么。

```
调了工具            → +0.3
工具返回了有效数据   → +0.2
回复中包含具体数据   → +0.1
Agent 报了错        → -0.5

≥ 0.7 → 高置信度，正常返回
0.5-0.7 → 中置信度
< 0.5 → 低置信度，触发人工接管 + 记忆整合
```

**为什么不用 LLM 自评**: 0 token 成本，实时判断，不受 LLM 自我感觉良好的影响。

---

### 5.9 安全模块

**文件**: `core/security.py`

**输入校验**:
- 消息长度 ≤ 2000 字符
- Prompt injection 模式检测（`ignore previous instructions`、`system prompt:` 等）
- ASCII 控制字符清理

**工具层防护**:
- 参数必填字段校验（ToolRegistry.execute 自动检查）
- 执行异常捕获（工具报错返回描述性字符串，不崩溃）
- SQL 注入防护（asyncpg 参数化查询保证）

---

### 5.10 持久化（SessionStore）

**文件**: `core/persistence.py`

**借鉴 nanobot 的 session/manager.py**:

```
存储结构:
  workspace/sessions/{safe_key}.jsonl     ← 对话历史（每条消息一行 JSON）
  workspace/sessions/{safe_key}.meta.json  ← 会话上下文（key-value）

写入策略:
  1. 写入 .tmp 文件
  2. os.replace() 原子替换（Windows 兼容）

恢复策略:
  启动时自动扫描 .meta.json → 恢复到内存 ContextStore
  JSONL 解析失败的行自动跳过（损坏恢复）
```

---

### 5.11 LLM Provider

**文件**: `core/provider.py`

**抽象**:

```python
class LLMProvider(ABC):
    async def chat(messages, tools) -> LLMResponse      # 单次调用
    async def chat_with_retry(messages, tools) -> LLMResponse  # 带重试
```

**DeepSeek 实现**:

- API: `https://api.deepseek.com`（OpenAI 兼容接口）
- 模型: `deepseek-chat`
- 重试: 最多 3 次，线性退避（1s / 2s / 3s）
- 错误处理: 所有异常捕获为 `LLMResponse(finish_reason="error")`，不抛出

---

### 5.12 数据库

**文件**: `db/connection.py`、`db/models.py`、`db/seed.py`

**连接**: asyncpg + SQLAlchemy 2.0 async，NullPool（每次请求新建连接）。

**为什么用 NullPool**:

```
asyncio.run(startup()) → 临时事件循环 A → 初始化 DB（建表 + 导种子数据）
uvicorn.run(app)       → 事件循环 B → 处理 HTTP 请求

连接池的连接在 A 中创建，在 B 中无效 → 必须用 NullPool
```

**4 张表**:

| 表 | 行数 | 字段 |
|----|------|------|
| `faq` | 10 | id, question, answer, category |
| `product` | 7 | id, name, price, stock, category, description |
| `customer_order` | 4 | id, phone, product_name, price, quantity, order_date, status, logistics |
| `customer_profile` | 动态 | phone, name, vip_level, complaint_count, refund_count, total_orders, preferred_category, avg_order_amount, last_intent, last_summary, last_session_time, tags |

---

### 5.13 监控指标

**文件**: `core/intent_router.py`（stats 属性）

**每次请求自动记录**:
- 分类到哪个意图
- 响应时间（毫秒）
- 是否走了 LLM 分类（Layer 3 使用率）
- 是否转人工

**API 返回示例** (`/api/admin/stats`):

```json
{
  "total_requests": 100,
  "by_intent": {
    "greeting":     {"count": 20, "pct": 20.0, "avg_ms": 5},
    "faq":          {"count": 30, "pct": 30.0, "avg_ms": 12},
    "order_query":  {"count": 15, "pct": 15.0, "avg_ms": 45},
    "logistics":    {"count": 5,  "pct": 5.0,  "avg_ms": 38},
    "product":      {"count": 5,  "pct": 5.0,  "avg_ms": 28},
    "after_sales":  {"count": 10, "pct": 10.0, "avg_ms": 35},
    "complaint":    {"count": 5,  "pct": 5.0,  "avg_ms": 8},
    "complex":      {"count": 20, "pct": 20.0, "avg_ms": 2100}
  },
  "agent_pct": 20.0,
  "direct_pct": 80.0,
  "handoffs": 5,
  "avg_latency_ms": 234,
  "llm_classify_used": 8
}
```

---

## 6. 完整请求链路

以"我要退货 → 88001"为例，追踪一条消息的完整生命周期：

```
0ms    用户 POST /api/chat {"message": "我要退货"}
1ms    validate_message() → 安全检查通过
2ms    提取手机号 → 无
3ms    加载上下文 → 当前阶段 normal，无历史订单号
4ms    Router 分类 → Layer 2 关键词命中 "after_sales"
5ms    _handle_after_sales → 无订单号 → 反问提示
6ms    _update_context → 检测"我要退" → agent_is_waiting("订单号")
       → phase = collecting_info
8ms    返回 HTTP 200 {"reply": "好的～要帮你处理退货。请提供订单号..."}

      ...用户看到回复，输入 "88001"...

0ms    用户 POST /api/chat {"message": "88001"}
1ms    validate_message() → 安全检查通过
2ms    提取手机号 → 正则匹配 "8001" → phone = "***8001"
3ms    ProfileManager.get_or_create("***8001") → PostgreSQL 查询画像
       → 画像: VIP gold, 投诉 3 次, 偏好充电配件
4ms    加载上下文 → phase = collecting_info, waiting_for = "订单号"
5ms    Router Layer 0 → should_skip_router() → True → 跳过分类
       → 返回 (complex, needs_agent=True)
6ms    组装 system prompt:
         AGENTS.md（小闪身份）
         + 顾客画像（VIP gold, 投诉3次, 偏好充电配件）
         + 工具契约（4 个工具说明）
7ms    组装 user message:
         [运行时上下文] 订单号 88001, 意图 退货, Agent 在等订单号 [/运行时上下文]
         88001
8ms    加载对话历史（上一条 user/assistant 对）
9ms    发给 DeepSeek API...
        messages = [system, 历史user, 历史assistant, 当前user]

3000ms DeepSeek 返回 tool_calls:
         [faq_lookup(query="退货"), order_query(order_id="88001")]

3005ms asyncio.gather(
          faq_lookup("退货"),      ← PostgreSQL ILIKE 查询
          order_query("88001")     ← PostgreSQL 精确查询
       ) → 并行执行

3050ms 两个结果都回来了，追加为 tool 消息

3055ms 再发给 DeepSeek（带上工具结果）...

8000ms DeepSeek 返回最终回复:
       "查到了～你的订单 88001 是6月4日签收的，今天还在7天退货期内。
        想问一下是质量问题还是不想要了？另外请提供手机号后四位验证身份～"

8010ms confidence.evaluate()
        调了 2 个工具 → +0.3
        工具有效数据  → +0.2
        回复含具体数据 → +0.1
        无错误         → 0
        总分: 0.6 → 中置信度

8015ms _update_context → 记住订单号 88001
       订单号匹配 → info_received() → phase = normal

8020ms _save_history → 内存 + JSONL 写入本轮对话

8025ms router.record_latency("complex", 8015ms)
8026ms 返回 HTTP 200
```

---

## 7. 与 nanobot 的区别

| 维度 | nanobot | 本项目 |
|------|---------|--------|
| **定位** | 通用 AI Agent 框架 | 垂直电商客服应用 |
| **代码量** | ~50000 行 | ~3000 行 |
| **消息入口** | Channel → Bus → AgentLoop | FastAPI → Router → 7 条管线 |
| **路由** | 无（所有消息进 Agent，LLM 判断调什么工具） | 三层分类（正则→关键词→LLM），直达对应管线 |
| **Agent 角色** | 核心处理器 | 最后兜底（仅 20% 请求经过） |
| **状态调度** | 8 状态 AgentLoop（RESTORE→COMPACT→...→DONE） | 无状态调度，直接 ReAct |
| **工具** | 15+ 通用工具（文件读写/shell/搜索/...） | 4 个客服专用工具 |
| **工具发现** | pkgutil 自动扫描 + entry_points 插件 | 手动注册 |
| **上下文治理** | token 预算估算 + 精确裁剪 + 空回复重试 | 条数上限 + 字符串截断（粗粒度但够用） |
| **记忆** | Dream 两阶段（LLM 从历史中提取长期记忆→更新 MEMORY.md） | 结构化画像（12 字段）+ 对话摘要 |
| **持久化** | JSONL 原子写（tmp→replace→fsync） | JSONL 原子写（tmp→replace），同上 |
| **并发** | per-session Lock + 全局并发门控（默认 3） | per-session Lock + 无共享可变状态 |
| **多渠道** | 15+ 平台（Telegram/微信/Discord/Slack/...） | WebUI 单入口 |
| **MCP** | 完整支持（stdio/sse/streamableHttp 三种传输） | 无（客服不需要外挂工具服务器） |
| **子 Agent** | spawn 后台子任务 + mid-turn 结果注入 | 并行工具执行（asyncio.gather） |
| **流式输出** | 支持 streaming + progress delta | 无 |
| **Hook 系统** | before_run/after_iteration/on_stream 等 | 无 |
| **安全** | SSRF 检测 + workspace 越界 + 重试升级 | 输入校验 + 注入检测 + 工具参数校验 |
| **指标** | runtime_events 总线条 | per-intent 计数/延迟/命中率 + admin API |
| **前端** | React SPA + WebSocket | 单文件 HTML + vanilla JS |

**本质区别**:

nanobot 是"操作系统"——提供 Agent 运行所需的一切基础设施，用户可以基于它构建任何 AI 应用。

本项目是"App"——用 nanobot 的工程思想（ToolRegistry、ContextBuilder、SessionStore、MemoryConsolidator），从头写了一个只做客服的垂直应用。核心创新是三层漏斗路由——在客服场景下 80%+ 的请求根本不需要经过 Agent。

---

## 8. 项目结构

```
CustomSystem/
├── server.py                 # FastAPI 入口，协调所有模块
├── core/
│   ├── loop.py               # AgentLoop（ReAct 循环 + 上下文治理）
│   ├── intent_router.py      # IntentRouter（意图分类 + 7 条管线）
│   ├── provider.py           # LLMProvider 抽象 + DeepSeek 实现
│   ├── context_store.py      # 短期记忆（内存 dict + TTL）
│   ├── session_state.py      # 会话阶段跟踪（normal/collecting/handoff）
│   ├── profile_manager.py    # 顾客长期画像管理（12 字段，PostgreSQL）
│   ├── memory.py             # 记忆整合（LLM 摘要，Dream 模式）
│   ├── persistence.py        # JSONL 会话持久化（原子写）
│   ├── confidence.py         # 置信度评估（行为驱动打分）
│   ├── security.py           # 安全校验（输入 + 注入检测）
│   └── bus.py                # MessageBus（asyncio.Queue）
├── context/
│   └── builder.py            # ContextBuilder（system prompt + user message 组装）
├── tools/
│   ├── base.py               # Tool 抽象基类
│   ├── registry.py           # ToolRegistry（注册 + 缓存 + 执行）
│   ├── faq_lookup.py         # FAQ 查询工具（PostgreSQL ILIKE）
│   ├── order_query.py        # 订单查询工具
│   ├── rag_search.py         # RAG 语义搜索工具（BGE + Qdrant）
│   └── human_handoff.py      # 转人工工具
├── rag/
│   ├── kb_store.py           # KnowledgeBase（嵌入式 Qdrant 向量检索）
│   └── ingest.py             # 数据导入（PostgreSQL → BGE/Qdrant 索引）
├── db/
│   ├── connection.py         # DB 连接（asyncpg + SQLAlchemy, NullPool）
│   ├── models.py             # ORM 模型（4 张表）
│   └── seed.py               # 种子数据（faq.json → PostgreSQL）
├── static/
│   ├── index.html            # 聊天界面（vanilla JS + CSS）
│   └── admin.html            # 管理面板（实时统计 + 会话监控）
├── workspace/
│   ├── AGENTS.md             # Agent 身份定义（小闪 + 行为规则）
│   └── sessions/             # JSONL 对话历史（运行时自动创建）
└── data/
    ├── faq.json              # 种子 FAQ 数据（10 条）
    ├── products.json         # 种子商品数据（7 个）
    └── orders.json           # 种子订单数据（4 个）
```

---

## 9. 快速启动

### 环境要求

- Python 3.11+
- PostgreSQL（数据库名 `cssdb`）
- DeepSeek API Key

### 安装

```bash
# 1. 创建虚拟环境
conda create -n css python=3.11
conda activate css

# 2. 安装依赖（当前实现为本地 BGE + 嵌入式 Qdrant）
pip install -r requirements.txt

# 3. 配置环境变量
copy .env.example .env
# 编辑 .env，填写 DEEPSEEK_API_KEY、DATABASE_URL 和 ADMIN_TOKEN

# 4. 创建 PostgreSQL 数据库
createdb cssdb

# 5. 启动
cd CustomSystem
python server.py
```

### 访问

- 聊天界面: http://localhost:8765
- 管理面板: http://localhost:8765/admin
- 健康检查: http://localhost:8765/api/health
- 指标 API: http://localhost:8765/api/admin/stats

---

## 10. API 文档

### POST /api/chat

发送消息并获取回复。

**请求**:
```json
{
  "message": "我要退货",
  "session_key": "web:default"
}
```

**响应**:
```json
{
  "reply": "好的～要帮你处理退货。请提供你的订单号（5位数字）～",
  "session_key": "web:default"
}
```

### GET /api/health

系统健康检查。

**响应**:
```json
{
  "status": "ok",
  "model": "deepseek-chat",
  "tools": ["faq_lookup", "order_query", "rag_search", "request_human"],
  "router": {
    "total": 42,
    "agent_pct": 19.0,
    "direct_pct": 81.0
  }
}
```

### GET /api/admin/stats

系统运行指标。

**响应**: 见 [5.13 监控指标](#513-监控指标)

### GET /api/admin/sessions

所有活跃会话的上下文。

### GET /api/admin/log

最近 200 条对话日志。
