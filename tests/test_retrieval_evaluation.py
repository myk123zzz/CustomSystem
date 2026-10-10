import json
from pathlib import Path

from evaluation.retrieval_metrics import retrieval_metrics


def test_retrieval_dataset_has_balanced_unique_cases():
    path = Path(__file__).parents[1] / "evaluation" / "retrieval_cases.json"
    cases = json.loads(path.read_text(encoding="utf-8"))
    assert len(cases) >= 24
    assert len({case["id"] for case in cases}) == len(cases)
    assert sum(case["collection"] == "product" for case in cases) == 12
    assert sum(case["collection"] == "faq" for case in cases) == 12
    assert all(case["query"] and case["expected"] for case in cases)


def test_retrieval_metrics_compute_recall_and_mrr():
    metrics = retrieval_metrics([
        {"rank": 1}, {"rank": 2}, {"rank": None}, {"rank": 4},
    ])
    assert metrics["queries"] == 4
    assert metrics["recall_at_1"] == 0.25
    assert metrics["recall_at_3"] == 0.5
    assert metrics["mrr"] == (1 + 0.5 + 0 + 0.25) / 4
