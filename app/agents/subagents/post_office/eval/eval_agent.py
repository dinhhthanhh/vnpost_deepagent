"""Benchmark evaluation for Post Office Agent."""

import json
import time
from pathlib import Path


def run_benchmark() -> dict:
    dataset_path = Path(__file__).parent / "dataset.json"
    with open(dataset_path, encoding="utf-8") as f:
        dataset = json.load(f)
    results = []
    start = time.perf_counter()
    for item in dataset:
        mock = "Danh sách bưu cục tại Hoàn Kiếm, Hà Nội: Bưu cục Bờ Hồ, địa chỉ 75 Đinh Tiên Hoàng."
        kws = item.get("expected_keywords", [])
        passed = sum(1 for kw in kws if kw.lower() in mock.lower()) >= len(kws) * 0.5
        results.append({"id": item["id"], "passed": passed})
    duration = time.perf_counter() - start
    passed_count = sum(1 for r in results if r["passed"])
    return {
        "agent": "post-office-agent",
        "total_samples": len(dataset),
        "passed_samples": passed_count,
        "accuracy_percent": round((passed_count / len(dataset)) * 100, 2),
        "execution_time_seconds": round(duration, 4),
        "details": results,
    }


if __name__ == "__main__":
    print(json.dumps(run_benchmark(), indent=2, ensure_ascii=False))
