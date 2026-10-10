"""Evaluate Qdrant retrieval with Recall@K and reciprocal rank."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from db.connection import init_db
from rag.ingest import ingest_all
from rag.kb_store import KnowledgeBase
from evaluation.retrieval_metrics import retrieval_metrics


async def main() -> int:
    cases = json.loads(
        (ROOT / "evaluation" / "retrieval_cases.json").read_text(encoding="utf-8")
    )
    output = ROOT / "workspace" / "retrieval_eval_report.json"
    rows = []

    with tempfile.TemporaryDirectory(prefix="customsystem-retrieval-") as temp_dir:
        kb = KnowledgeBase(persist_dir=temp_dir)
        try:
            await init_db()
            await ingest_all(kb)
            for case in cases:
                if case["collection"] == "product":
                    hits = kb.search_products(case["query"], n_results=3)
                    values = [hit.get("product_id") for hit in hits]
                else:
                    hits = kb.search_faq(case["query"], n_results=3)
                    values = [hit.get("question") for hit in hits]
                rank = next(
                    (index + 1 for index, value in enumerate(values)
                     if value in case["expected"]),
                    None,
                )
                rows.append({
                    "id": case["id"],
                    "collection": case["collection"],
                    "query": case["query"],
                    "expected": case["expected"],
                    "retrieved": values,
                    "scores": [hit["score"] for hit in hits],
                    "rank": rank,
                })
        finally:
            kb.close()

    report = {
        "overall": retrieval_metrics(rows),
        "product": retrieval_metrics([row for row in rows if row["collection"] == "product"]),
        "faq": retrieval_metrics([row for row in rows if row["collection"] == "faq"]),
        "results": rows,
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for name in ("overall", "product", "faq"):
        item = report[name]
        print(
            f"{name}: queries={item['queries']} "
            f"R@1={item['recall_at_1']:.1%} "
            f"R@3={item['recall_at_3']:.1%} MRR={item['mrr']:.3f}"
        )
    print(f"report={output}")
    return 0 if report["overall"]["recall_at_3"] >= 0.9 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
