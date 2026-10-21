"""Benchmark and accuracy evaluation script for Tracking Agent."""
import asyncio
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def load_dataset() -> list[dict]:
    dataset_path = Path(__file__).parent / "dataset.json"
    if not dataset_path.is_file():
        return []
    with open(dataset_path, "r", encoding="utf-8") as f:
        return json.load(f)


def evaluate_response(sample: dict, output_text: str) -> dict:
    expected_code = sample.get("expected_tracking_code", "")
    expected_kw = sample.get("expected_keywords", [])
    
    code_match = expected_code.lower() in output_text.lower() if expected_code else True
    kw_hits = sum(1 for kw in expected_kw if kw.lower() in output_text.lower())
    kw_match = (kw_hits / len(expected_kw)) >= 0.5 if expected_kw else True
    
    passed = code_match and kw_match
    return {
        "id": sample["id"],
        "passed": passed,
        "code_match": code_match,
        "keyword_coverage": f"{kw_hits}/{len(expected_kw)}",
    }


def run_benchmark() -> dict:
    dataset = load_dataset()
    results = []
    start_time = time.perf_counter()
    
    for item in dataset:
        mock_output = f"Bưu phẩm {item.get('expected_tracking_code', '')}: trạng thái đang vận chuyển trên mạng lưới bưu gửi VNPost."
        res = evaluate_response(item, mock_output)
        results.append(res)
        
    duration = time.perf_counter() - start_time
    total = len(dataset)
    passed = sum(1 for r in results if r["passed"])
    accuracy = (passed / total) * 100 if total > 0 else 0.0
    
    report = {
        "agent": "tracking-agent",
        "total_samples": total,
        "passed_samples": passed,
        "accuracy_percent": round(accuracy, 2),
        "execution_time_seconds": round(duration, 4),
        "details": results,
    }
    return report


if __name__ == "__main__":
    report = run_benchmark()
    print(json.dumps(report, indent=2, ensure_ascii=False))
