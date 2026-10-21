"""Evaluate passage retrieval against human-labelled JSONL questions."""
import argparse
import json
import math
import re
import statistics
import time
from pathlib import Path

from app.core.config import Settings
from app.rag import KnowledgeBases

parser = argparse.ArgumentParser()
parser.add_argument("--tenant", required=True)
parser.add_argument("--dataset", required=True, type=Path)
parser.add_argument("--output", type=Path, default=Path("retrieval_report.json"))
args = parser.parse_args()
if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", args.tenant):
    parser.error("Invalid tenant")
settings = Settings()
kb = KnowledgeBases(settings).for_tenant(args.tenant)
records = [json.loads(line) for line in args.dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
if not records:
    raise SystemExit("Dataset is empty")
results, delays = [], []
for record in records:
    start = time.monotonic()
    hits = kb.retrieve(record["question"])
    delays.append(round((time.monotonic() - start) * 1000, 3))
    if record.get("no_answer"):
        passed = not hits
        rank = None
    else:
        expected_file = record["expected_filename"]
        phrase = record.get("expected_excerpt_contains", "")
        rank = next((i for i, hit in enumerate(hits, 1) if hit["filename"] == expected_file and phrase.lower() in hit["excerpt"].lower()), None)
        passed = rank is not None
    results.append({"id": record.get("id"), "passed": passed, "rank": rank, "latency_ms": delays[-1], "returned_chunks": len(hits)})
answerable = [r for r, original in zip(results, records, strict=True) if not original.get("no_answer")]
negative = [r for r, original in zip(results, records, strict=True) if original.get("no_answer")]
report = {"demo": settings.demo_mode, "embedding_provider": settings.embedding_provider,
          "questions": len(results), "top_k": settings.retrieval_top_k,
          "pass_rate": sum(r["passed"] for r in results) / len(results),
          "recall_at_k": sum(r["passed"] for r in answerable) / len(answerable) if answerable else None,
          "mrr_at_k": sum(1 / r["rank"] if r["rank"] else 0 for r in answerable) / len(answerable) if answerable else None,
          "no_answer_retrieval_rate": sum(r["passed"] for r in negative) / len(negative) if negative else None,
          "p50_ms": statistics.median(delays), "p95_ms": sorted(delays)[math.ceil(len(delays) * .95) - 1],
          "scope": "Retrieval only; does not measure semantic answer correctness", "results": results}
args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({key: value for key, value in report.items() if key != "results"}, ensure_ascii=False, indent=2))
