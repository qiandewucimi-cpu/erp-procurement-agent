from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from erp_agent.knowledge import KnowledgeBase


DEFAULT_CASES = ROOT / "evals" / "rag_cases.json"
DEFAULT_RESULTS = ROOT / "evals" / "rag_results.json"
DEFAULT_REPORT = ROOT / "evals" / "RAG_REPORT.md"


def _rank(results: list[dict], source: str, section: str) -> int | None:
    for index, item in enumerate(results, start=1):
        if item["source"] == source and item["section"] == section:
            return index
    return None


def evaluate(cases_path: Path = DEFAULT_CASES) -> dict:
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    knowledge = KnowledgeBase(ROOT / "knowledge")
    details: list[dict] = []
    positive_count = negative_count = recall_1_hits = recall_3_hits = rejected = 0
    reciprocal_rank_sum = 0.0

    for case in cases:
        results = knowledge.search(case["query"], top_k=3)
        if case.get("expect_reject"):
            negative_count += 1
            passed = not results
            rejected += int(passed)
            details.append({**case, "passed": passed, "returned": results})
            continue

        positive_count += 1
        rank = _rank(results, case["expected_source"], case["expected_section"])
        recall_1_hits += int(rank == 1)
        recall_3_hits += int(rank is not None and rank <= 3)
        reciprocal_rank_sum += 0.0 if rank is None else 1.0 / rank
        details.append({**case, "passed": rank is not None and rank <= 3, "rank": rank, "returned": results})

    metrics = {
        "positive_cases": positive_count,
        "negative_cases": negative_count,
        "recall_at_1": round(recall_1_hits / max(1, positive_count), 4),
        "recall_at_3": round(recall_3_hits / max(1, positive_count), 4),
        "mrr": round(reciprocal_rank_sum / max(1, positive_count), 4),
        "rejection_accuracy": round(rejected / max(1, negative_count), 4),
    }
    thresholds = {"recall_at_3": 0.9, "mrr": 0.75, "rejection_accuracy": 1.0}
    passed = all(metrics[name] >= value for name, value in thresholds.items())
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "retriever": "offline lexical bigram overlap",
        "metrics": metrics,
        "thresholds": thresholds,
        "passed": passed,
        "cases": details,
    }


def write_report(payload: dict, results_path: Path = DEFAULT_RESULTS, report_path: Path = DEFAULT_REPORT) -> None:
    results_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    metrics = payload["metrics"]
    lines = [
        "# RAG 检索评测报告",
        "",
        f"- 生成时间：{payload['generated_at']}",
        f"- 检索器：{payload['retriever']}",
        f"- 总结：{'通过' if payload['passed'] else '未通过'}",
        "",
        "| 指标 | 结果 | 门槛 |",
        "|---|---:|---:|",
        f"| Recall@1 | {metrics['recall_at_1']:.1%} | 观察项 |",
        f"| Recall@3 | {metrics['recall_at_3']:.1%} | ≥ {payload['thresholds']['recall_at_3']:.0%} |",
        f"| MRR | {metrics['mrr']:.3f} | ≥ {payload['thresholds']['mrr']:.2f} |",
        f"| 拒答命中率 | {metrics['rejection_accuracy']:.1%} | = {payload['thresholds']['rejection_accuracy']:.0%} |",
        "",
        "## 用例明细",
        "",
        "| 用例 | 查询 | 预期 | 结果 |",
        "|---|---|---|---|",
    ]
    for case in payload["cases"]:
        expected = "拒答" if case.get("expect_reject") else f"{case['expected_source']} / {case['expected_section']}"
        if case.get("expect_reject"):
            actual = "拒答" if case["passed"] else "返回了伪相关结果"
        else:
            actual = f"rank={case['rank']}" if case["rank"] else "未命中 Top-3"
        lines.append(f"| {case['id']} | {case['query']} | {expected} | {'通过' if case['passed'] else '失败'}（{actual}） |")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="离线 RAG 检索质量评测")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    args = parser.parse_args()
    payload = evaluate(args.cases)
    write_report(payload)
    metrics = payload["metrics"]
    print(
        "RAG eval: "
        f"Recall@1={metrics['recall_at_1']:.1%}, Recall@3={metrics['recall_at_3']:.1%}, "
        f"MRR={metrics['mrr']:.3f}, rejection={metrics['rejection_accuracy']:.1%}"
    )
    print(f"Result: {'PASS' if payload['passed'] else 'FAIL'}")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
