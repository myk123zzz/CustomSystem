"""Run the complete reproducible evaluation suite and write a JSON report."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.dataset import load_cases
from evaluation.deterministic import build_deterministic_engine
from evaluation.metrics import evaluate_results
from evaluation.sandbox import EvaluationSandbox


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "workspace" / "eval_report.json",
    )
    args = parser.parse_args()

    pairs = await EvaluationSandbox(build_deterministic_engine).run_all(load_cases())
    report = evaluate_results(pairs)
    payload = asdict(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"cases={report.total} passed={report.passed} pass_rate={report.pass_rate:.1%}")
    print(f"route={report.route_accuracy:.1%} tools={report.tool_accuracy:.1%} "
          f"llm_budget={report.llm_budget_accuracy:.1%} "
          f"session={report.session_accuracy:.1%} handoff={report.handoff_accuracy:.1%}")
    for category, rate in sorted(report.category_pass_rate.items()):
        print(f"  {category}: {rate:.1%}")
    print(f"report={args.output}")
    return 0 if report.passed == report.total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
