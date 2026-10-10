# CustomSystem 启动说明

完整架构差异、记忆设计、测试结果和换机步骤见 `HANDOFF.md`。

推荐 Conda + Python 3.11。环境名不影响代码：

```powershell
conda create -n customsystem python=3.11 -y
conda activate customsystem
pip install -r requirements.txt
Copy-Item .env.example .env
```

在 `.env` 中配置 `DEEPSEEK_API_KEY`、`DATABASE_URL` 和随机的 `ADMIN_TOKEN`。确保 PostgreSQL 已启动且数据库存在，然后运行 `python server.py`。首次启动会自动建表并导入 `data/*.json`；需要完整演示数据时，停止服务后运行 `python scripts/seed_demo_data.py`，再启动服务。

- 聊天页：`http://127.0.0.1:8765/`
- 管理后台：`http://127.0.0.1:8765/admin`
- 健康接口：`http://127.0.0.1:8765/api/health`
- Swagger：`http://127.0.0.1:8765/docs`

验证命令：

```powershell
python -m pytest -q
python scripts/run_deterministic_eval.py
python scripts/run_retrieval_eval.py
```

服务运行且真实模型/数据库可用时，再执行 `python scripts/run_live_api_eval.py`。健康接口不是完整数据库探针，启动后还应发送一次 `/api/chat` 请求。嵌入式 Qdrant 同一目录仅允许一个进程使用。
