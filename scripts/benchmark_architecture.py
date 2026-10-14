"""Run reproducible route/latency measurements without storing prompts or answers.

Default mode uses the deterministic local demo model. Pass ``--live`` to use
current .env providers and measure the deployed embedding/LLM path.
"""

import argparse
import asyncio
import json
import math
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

from pydantic import SecretStr

from app.config import Settings
from app.schemas import ChatRequest
from app.service import ChatService

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "evaluation" / "architecture_benchmark.jsonl"
DEFAULT_OUTPUT = ROOT / "reports" / "architecture_metrics.json"


def percentile(values: list[float], level: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(level * len(ordered)) - 1)
    return round(ordered[index], 2)


def event_metrics(events: list[dict]) -> dict[str, Any]:
    starts: dict[str, int] = {}
    intervals: list[tuple[int, int]] = []
    first_token = next((event["elapsed_ms"] for event in events if event["type"] == "token"), None)
    for event in events:
        if event["type"] == "llm_start":
            starts[event["call_id"]] = event["elapsed_ms"]
        elif event["type"] in {"llm_end", "llm_error"} and event["call_id"] in starts:
            intervals.append((starts.pop(event["call_id"]), event["elapsed_ms"]))
    # Include unfinished calls (normally only a provider failure) through the
    # last observed event so the concurrency metric remains conservative.
    end = max((event["elapsed_ms"] for event in events), default=0)
    intervals.extend((started, end) for started in starts.values())
    points: list[tuple[int, int]] = []
    for started, finished in intervals:
        points.extend(((started, 1), (finished, -1)))
    active = maximum = 0
    for _, change in sorted(points, key=lambda item: (item[0], -item[1])):
        active += change
        maximum = max(maximum, active)
    source_gate = next((event for event in events if event["type"] == "source_gate"), None)
    router = next((event for event in events if event["type"] == "router_decision"), {})
    return {
        "initial_tier": router.get("tier"),
        "router_strategy": router.get("strategy"),
        "llm_calls": len(intervals),
        "max_parallel_llm_calls": maximum,
        "retrieval_calls": sum(event["type"] == "retrieval" for event in events),
        "retrieval_cache_hits": sum(event["type"] == "retrieval_cache_hit" for event in events),
        "subagent_tasks": sum(event["type"] == "task_start" for event in events),
        "source_gate": source_gate.get("status") if source_gate else None,
        "ttft_ms": first_token,
        "escalated": any(event["type"] == "route_escalated" for event in events),
        "deep_timeout": any(event["type"] == "deep_timeout" for event in events),
    }


def aggregate(rows: list[dict]) -> dict[str, Any]:
    successful = [row for row in rows if not row.get("error")]
    by_route: dict[str, list[dict]] = defaultdict(list)
    for row in successful:
        by_route[row["route"]].append(row)

    def group_summary(group: list[dict]) -> dict[str, Any]:
        elapsed = [row["elapsed_ms"] for row in group]
        ttft = [row["metrics"]["ttft_ms"] for row in group if row["metrics"]["ttft_ms"] is not None]
        return {
            "count": len(group),
            "p50_elapsed_ms": percentile(elapsed, 0.50),
            "p95_elapsed_ms": percentile(elapsed, 0.95),
            "p50_ttft_ms": percentile(ttft, 0.50),
            "p95_ttft_ms": percentile(ttft, 0.95),
            "mean_llm_calls": round(mean(row["metrics"]["llm_calls"] for row in group), 2),
            "mean_retrieval_calls": round(mean(row["metrics"]["retrieval_calls"] for row in group), 2),
            "mean_cache_hits": round(mean(row["metrics"]["retrieval_cache_hits"] for row in group), 2),
            "mean_subagent_tasks": round(mean(row["metrics"]["subagent_tasks"] for row in group), 2),
        }

    return {
        "requested": len(rows),
        "completed": len(successful),
        "errors": len(rows) - len(successful),
        "route_distribution": dict(Counter(row["route"] for row in successful)),
        "initial_tier_distribution": dict(Counter(str(row["metrics"]["initial_tier"]) for row in successful)),
        "source_gate_distribution": dict(Counter(str(row["metrics"]["source_gate"]) for row in successful)),
        "escalations": sum(row["metrics"]["escalated"] for row in successful),
        "deep_timeouts": sum(row["metrics"]["deep_timeout"] for row in successful),
        "overall": group_summary(successful) if successful else {},
        "by_executed_route": {route: group_summary(group) for route, group in by_route.items()},
    }


def read_dataset(path: Path, limit: int | None) -> list[dict]:
    items = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            items.append(json.loads(line))
    return items[:limit] if limit else items


def kb_metadata(settings: Settings, tenant: str) -> dict[str, Any]:
    current = settings.data_dir / "kb" / tenant / "current.json"
    if not current.exists():
        return {"available": False}
    data = json.loads(current.read_text(encoding="utf-8"))
    return {"available": True, "revision": data.get("revision"), "records": len(data.get("records", []))}


async def run(args: argparse.Namespace) -> dict[str, Any]:
    settings = Settings()
    if not args.live:
        settings = settings.model_copy(update={"llm_api_key": SecretStr(""), "tts_enabled": False})
    samples = read_dataset(args.dataset, args.limit)
    service = ChatService(settings)
    rows = []
    try:
        for sample in samples:
            started = time.perf_counter()
            request = ChatRequest(
                message=sample["message"], grounded=sample.get("grounded", True),
                mode=sample.get("mode", "auto"), voice=False,
            )
            try:
                # Passing a queue enables fast-token events; no prompt/completion is retained.
                response = await service.chat(args.tenant, request, queue=asyncio.Queue())
                rows.append({
                    "id": sample["id"], "expected_tier": sample.get("expected_tier"),
                    "route": response.route, "grounding_status": response.grounding_status,
                    "elapsed_ms": response.elapsed_ms,
                    "wall_ms": round((time.perf_counter() - started) * 1000, 2),
                    "source_count": len(response.sources), "answer_chars": len(response.answer),
                    "metrics": event_metrics(response.events),
                })
            except Exception as exc:
                rows.append({"id": sample["id"], "error": type(exc).__name__,
                             "wall_ms": round((time.perf_counter() - started) * 1000, 2)})
    finally:
        await service.close()
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "measurement_mode": "live" if args.live else "demo",
        "tenant": args.tenant,
        "dataset": str(args.dataset.relative_to(ROOT) if args.dataset.is_relative_to(ROOT) else args.dataset),
        "configuration": {
            "embedding_provider": settings.embedding_provider,
            "embedding_model": settings.local_embedding_model if settings.embedding_provider == "huggingface" else settings.embedding_model,
            "retrieval_top_k": settings.retrieval_top_k,
            "fast_min_sources": settings.fast_min_sources,
            "fast_min_retrieval_score": settings.fast_min_retrieval_score,
            "llm_router_enabled": settings.llm_router_enabled,
            "deep_timeout_seconds": settings.deep_timeout,
            "deep_max_agent_steps": settings.deep_max_agent_steps,
        },
        "knowledge_base": kb_metadata(settings, args.tenant),
        "summary": aggregate(rows),
        "samples": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure fast/deep routing and source-gate metrics")
    parser.add_argument("--tenant", default="vnpost")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--live", action="store_true", help="Call providers configured in .env; default is deterministic demo model")
    args = parser.parse_args()
    args.dataset = args.dataset.resolve()
    args.output = args.output.resolve()
    report = asyncio.run(run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
