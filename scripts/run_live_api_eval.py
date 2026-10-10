"""Black-box evaluation against a running production API instance."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.persistence import _safe_filename
from evaluation.dataset import load_cases
from evaluation.metrics import evaluate_results


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "workspace" / "live_eval_report.json",
    )
    args = parser.parse_args()
    token = str(dotenv_values(ROOT / ".env").get("ADMIN_TOKEN") or "change-me")
    run_id = int(time.time())
    pairs = []

    async with httpx.AsyncClient(base_url=args.base_url, timeout=180) as client:
        for case in load_cases():
            session_key = f"liveeval:{run_id}:{case.id}"
            reply = ""
            for turn in case.turns:
                response = await client.post(
                    "/api/chat",
                    json={"message": turn, "session_key": session_key},
                )
                response.raise_for_status()
                reply = response.json()["reply"]

            trace_response = await client.get(
                "/api/admin/traces", headers={"X-Admin-Token": token}
            )
            trace_response.raise_for_status()
            traces = [
                item for item in trace_response.json()["traces"]
                if item["session_key"] == session_key
            ]
            if not traces:
                raise RuntimeError(f"missing trace for {case.id}")
            trace = traces[-1]
            all_tools = [
                tool for item in traces for tool in item["tools_called"]
            ]
            total_llm_calls = sum(item["llm_calls"] for item in traces)

            meta_path = (
                ROOT / "workspace" / "sessions"
                / f"{_safe_filename(session_key)}.meta.json"
            )
            state = json.loads(meta_path.read_text(encoding="utf-8"))
            result = SimpleNamespace(
                reply=reply,
                final_target=SimpleNamespace(value=trace["target"]),
                decision=SimpleNamespace(
                    intent=SimpleNamespace(value=trace["intent"])
                ),
                tools_called=all_tools,
                llm_calls=total_llm_calls,
                session_state=state,
            )
            pairs.append((case, result))
            print(f"[{len(pairs):02d}/{len(load_cases()):02d}] {case.id}: {trace['target']}")

    report = evaluate_results(pairs)
    args.output.write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"cases={report.total} passed={report.passed} pass_rate={report.pass_rate:.1%}")
    print(f"route={report.route_accuracy:.1%} tools={report.tool_accuracy:.1%} "
          f"llm_budget={report.llm_budget_accuracy:.1%} "
          f"session={report.session_accuracy:.1%} handoff={report.handoff_accuracy:.1%}")
    print(f"report={args.output}")
    return 0 if report.passed == report.total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
