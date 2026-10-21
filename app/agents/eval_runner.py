"""Unified benchmark runner across all subagents."""
import importlib
import json
import logging
import sys
from pathlib import Path

SUBAGENTS = [
    "tracking",
    "booking",
    "complaint",
    "analyst",
    "post_office",
    "rag",
    "writer",
]

def run_all_benchmarks() -> dict:
    summary = {
        "total_agents": len(SUBAGENTS),
        "passed_agents": 0,
        "agents": {},
    }
    
    for agent_name in SUBAGENTS:
        try:
            module = importlib.import_module(f"app.agents.subagents.{agent_name}.eval.eval_agent")
            if hasattr(module, "run_benchmark"):
                report = module.run_benchmark()
                summary["agents"][agent_name] = report
                if report.get("accuracy_percent", 0) >= 80.0:
                    summary["passed_agents"] += 1
        except Exception as exc:
            summary["agents"][agent_name] = {"error": str(exc), "accuracy_percent": 0.0}

    summary["overall_health"] = "healthy" if summary["passed_agents"] == len(SUBAGENTS) else "degraded"
    return summary

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "reports" / "subagents_benchmark.json"

if __name__ == "__main__":
    report = run_all_benchmarks()
    DEFAULT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_OUTPUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"Saved: {DEFAULT_OUTPUT}")

