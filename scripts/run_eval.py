"""Run the versioned offline suite through the production service engine."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from evaluation.dataset import load_cases
from evaluation.metrics import evaluate_results
from evaluation.sandbox import EvaluationSandbox


async def main() -> int:
    # Embedded Qdrant is single-process. Evaluation therefore builds an
    # isolated disposable index and can run while the web server is active.
    temp_qdrant = tempfile.TemporaryDirectory(prefix="customsystem-eval-")
    os.environ["QDRANT_PATH"] = temp_qdrant.name

    from db.connection import init_db
    from db.seed import seed_all
    from rag.ingest import ingest_all
    from server import engine, kb

    try:
        try:
            await init_db()
            await seed_all()
            await ingest_all(kb)
        except Exception as exc:
            print(
                "[EVAL SETUP ERROR] PostgreSQL/RAG 初始化失败："
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            print(
                "请检查 DATABASE_URL、数据库角色和数据库是否存在；"
                "评测未调用模型。",
                file=sys.stderr,
            )
            return 2
        sandbox = EvaluationSandbox(lambda: engine)
        report = evaluate_results(await sandbox.run_all(load_cases()))
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
        return 0 if report.passed == report.total else 1
    finally:
        kb.close()
        temp_qdrant.cleanup()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
