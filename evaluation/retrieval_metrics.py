"""Reusable ranking metrics for RAG evaluation."""

from __future__ import annotations


def retrieval_metrics(rows: list[dict]) -> dict:
    total = len(rows)
    if total == 0:
        return {"queries": 0, "recall_at_1": 0.0, "recall_at_3": 0.0, "mrr": 0.0}
    return {
        "queries": total,
        "recall_at_1": sum(row["rank"] == 1 for row in rows) / total,
        "recall_at_3": sum(
            row["rank"] is not None and row["rank"] <= 3 for row in rows
        ) / total,
        "mrr": sum(1 / row["rank"] if row["rank"] else 0 for row in rows) / total,
    }
