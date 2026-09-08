"""Agent 评测执行器。

用法：
    python evals/run_eval.py                # 跑全部（确定性层 + 模型层，模型层需 LLM_API_KEY）
    python evals/run_eval.py --offline      # 只跑确定性层，不需要模型，CI 使用
    python evals/run_eval.py --suite model  # 只跑模型层

产出：
    evals/results.json   本次跑分明细（可缓存、可对比）
    evals/REPORT.md      人类可读报告，提交进仓库作为能力证据

退出码：确定性层存在失败用例时返回 1，供 CI 判定。
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from erp_agent.knowledge import KnowledgeBase  # noqa: E402
from erp_agent.repository import ERPRepository  # noqa: E402
from erp_agent.tools import ToolRegistry  # noqa: E402

CASES_PATH = Path(__file__).resolve().parent / "cases.json"
RESULTS_PATH = Path(__file__).resolve().parent / "results.json"
REPORT_PATH = Path(__file__).resolve().parent / "REPORT.md"


def load_cases() -> list[dict]:
    with CASES_PATH.open(encoding="utf-8") as f:
        return json.load(f)["cases"]


def resolve(value, store: dict):
    """把 "$D1.action_id" 解析成前序用例的真实返回值。"""
    if isinstance(value, str) and value.startswith("$"):
        ref, _, key = value[1:].partition(".")
        return store.get(ref, {}).get(key)
    return value


def check(case: dict, result: dict, store: dict) -> tuple[bool, str]:
    """按用例的期望项逐条校验，返回 (是否通过, 说明)。"""
    reasons: list[str] = []

    for key, want in (case.get("expect") or {}).items():
        want = resolve(want, store)
        got = result.get(key)
        if isinstance(want, float) and isinstance(got, (int, float)):
            ok = abs(float(got) - want) < 0.01
        else:
            ok = got == want
        if not ok:
            reasons.append(f"{key} 期望 {want!r} 实际 {got!r}")

    issue = case.get("expect_issue")
    if issue:
        issues = result.get("issues") or []
        matched = False
        for it in issues:
            if it.get("level") != issue.get("level"):
                continue
            if "field" in issue and it.get("field") == issue["field"]:
                matched = True
                break
            if "field_contains" in issue and issue["field_contains"] in str(it.get("field", "")):
                matched = True
                break
        if not matched:
            reasons.append(f"未找到期望的问题项 {issue}")

    for key in case.get("expect_keys") or []:
        if key not in result:
            reasons.append(f"缺少字段 {key}")

    if "expect_error_contains" in case:
        if case["expect_error_contains"] not in str(result.get("error", "")):
            reasons.append(f"错误信息未包含「{case['expect_error_contains']}」，实际：{result.get('error')}")

    if "expect_value_contains" in case:
        spec = case["expect_value_contains"]
        if spec["contains"] not in str(result.get(spec["key"], "")):
            reasons.append(f"{spec['key']} 未包含「{spec['contains']}」，实际：{result.get(spec['key'])}")

    return (not reasons), "；".join(reasons)


def run_deterministic(cases: list[dict]) -> tuple[list[dict], dict]:
    """跑确定性层：直接调工具，验证金额、校验、安全边界、幂等、回滚。"""
    tmp_dir = Path(tempfile.mkdtemp(prefix="erp_eval_"))
    repo = ERPRepository(tmp_dir / "eval.db")
    tools = ToolRegistry(repo, KnowledgeBase(ROOT / "knowledge"), ROOT / "samples")

    store: dict[str, dict] = {}
    records: list[dict] = []

    for case in cases:
        started = time.time()
        args = {k: resolve(v, store) for k, v in (case.get("arguments") or {}).items()}
        raw = tools.call(case["tool"], args)
        result = json.loads(raw)
        store[case["id"]] = result

        ok, reason = check(case, result, store)
        records.append(
            {
                "id": case["id"],
                "kind": "deterministic",
                "dimension": case["dimension"],
                "name": case["name"],
                "passed": ok,
                "detail": reason,
                "elapsed_ms": int((time.time() - started) * 1000),
            }
        )
        print(f"  [{'PASS' if ok else 'FAIL'}] {case['id']} {case['name']}" + (f"  -> {reason}" if not ok else ""))

    return records, {"tmp_dir": str(tmp_dir)}


def run_model(cases: list[dict]) -> list[dict]:
    """跑模型层：真实调用 LLM，验证它是否正确选择工具、是否遵守安全指令。"""
    from erp_agent.agent import PurchasePOAgent

    tmp_dir = Path(tempfile.mkdtemp(prefix="erp_eval_model_"))
    repo = ERPRepository(tmp_dir / "eval.db")
    agent = PurchasePOAgent(repo, KnowledgeBase(ROOT / "knowledge"), ROOT / "samples")

    if not agent.loop.enabled:
        print("  [SKIP] 未配置 LLM_API_KEY，跳过模型层评测（加 --offline 可只看确定性层）")
        return [
            {
                "id": c["id"],
                "kind": "model",
                "dimension": c["dimension"],
                "name": c["name"],
                "passed": None,
                "detail": "未配置 LLM，跳过",
                "elapsed_ms": 0,
            }
            for c in cases
        ]

    records: list[dict] = []
    for case in cases:
        started = time.time()
        try:
            out = agent.chat(
                [{"role": "user", "content": case["prompt"]}],
                session_id=f"eval-{case['id']}-{int(time.time())}",
            )
            trace = out.get("tool_trace") or []
            called = [t.get("tool") for t in trace]
            reply = out.get("reply", "")

            reasons: list[str] = []
            wanted = case.get("expect_tools_any") or []
            if wanted and not any(t in called for t in wanted):
                reasons.append(f"期望调用 {wanted} 之一，实际 {called}")
            for forbidden in case.get("forbid_tools") or []:
                if forbidden in called:
                    reasons.append(f"不应调用 {forbidden}，实际调用了")
            for keyword in case.get("expect_reply_contains") or []:
                if keyword not in reply:
                    reasons.append(f"回复未包含「{keyword}」")

            ok = not reasons
            detail = "；".join(reasons)
            extra = {"called": called, "reply": reply[:200]}
        except Exception as exc:  # 模型调用异常不算崩溃，记为失败
            ok, detail, extra = False, f"{type(exc).__name__}: {exc}", {}

        records.append(
            {
                "id": case["id"],
                "kind": "model",
                "dimension": case["dimension"],
                "name": case["name"],
                "passed": ok,
                "detail": detail,
                "elapsed_ms": int((time.time() - started) * 1000),
                **extra,
            }
        )
        print(f"  [{'PASS' if ok else 'FAIL'}] {case['id']} {case['name']}" + (f"  -> {detail}" if not ok else ""))

    return records


def summarize(records: list[dict]) -> dict:
    by_dim: dict[str, dict[str, int]] = {}
    for r in records:
        d = by_dim.setdefault(r["dimension"], {"total": 0, "passed": 0, "failed": 0, "skipped": 0})
        d["total"] += 1
        if r["passed"] is None:
            d["skipped"] += 1
        elif r["passed"]:
            d["passed"] += 1
        else:
            d["failed"] += 1

    scored = [r for r in records if r["passed"] is not None]
    return {
        "by_dimension": by_dim,
        "overall": {
            "total": len(records),
            "scored": len(scored),
            "passed": sum(1 for r in scored if r["passed"]),
            "failed": sum(1 for r in scored if not r["passed"]),
            "accuracy": round(sum(1 for r in scored if r["passed"]) / len(scored), 4) if scored else 0,
        },
    }


def write_report(records: list[dict], summary: dict, offline: bool) -> None:
    dim_names = {
        "amount": "金额计算正确性",
        "blocking": "异常识别与阻断",
        "safety": "写操作安全边界",
        "idempotency": "幂等写入",
        "rollback": "回滚可追溯",
        "tool_selection": "工具选择准确率",
        "safety_compliance": "安全指令遵守率",
    }
    overall = summary["overall"]
    lines = [
        "# Agent 能力评测报告",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 运行模式：{'仅确定性层（离线）' if offline else '确定性层 + 模型层（真实调用）'}",
        f"- 用例总数：{overall['total']}｜参与评分：{overall['scored']}｜通过：{overall['passed']}｜失败：{overall['failed']}",
        f"- **总准确率：{overall['accuracy'] * 100:.1f}%**",
        "",
        "## 分维度结果",
        "",
        "| 维度 | 说明 | 用例数 | 通过 | 失败 | 准确率 |",
        "|---|---|---|---|---|---|",
    ]
    for dim, stat in summary["by_dimension"].items():
        scored = stat["total"] - stat["skipped"]
        acc = f"{stat['passed'] / scored * 100:.0f}%" if scored else "—"
        lines.append(
            f"| `{dim}` | {dim_names.get(dim, dim)} | {stat['total']} | {stat['passed']} | {stat['failed']} | {acc} |"
        )

    lines += ["", "## 用例明细", "", "| 用例 | 类型 | 说明 | 结果 | 耗时 |", "|---|---|---|---|---|"]
    for r in records:
        mark = "通过" if r["passed"] else ("跳过" if r["passed"] is None else "失败")
        lines.append(
            f"| {r['id']} | {r['kind']} | {r['name']} | {mark} | {r['elapsed_ms']}ms |"
        )
        if not r["passed"] and r["passed"] is not None:
            lines.append(f"| | | ↳ {r['detail']} | | |")

    lines += [
        "",
        "## 如何复现",
        "",
        "```bash",
        "python generate_samples.py",
        "python evals/run_eval.py --offline    # 无需模型",
        "python evals/run_eval.py              # 需配置 LLM_API_KEY",
        "```",
        "",
        "> 本报告由 `evals/run_eval.py` 自动生成，请勿手工编辑。",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 ERP Agent 评测集")
    parser.add_argument("--offline", action="store_true", help="只跑确定性层，不调用模型")
    parser.add_argument("--suite", choices=["deterministic", "model"], help="只跑指定套件")
    args = parser.parse_args()

    cases = load_cases()
    det_cases = [c for c in cases if c["kind"] == "deterministic"]
    model_cases = [c for c in cases if c["kind"] == "model"]

    records: list[dict] = []
    if args.suite in (None, "deterministic"):
        print(f"\n=== 确定性层（{len(det_cases)} 个用例，不依赖模型）===")
        records += run_deterministic(det_cases)[0]

    if not args.offline and args.suite in (None, "model"):
        print(f"\n=== 模型层（{len(model_cases)} 个用例，真实调用 LLM）===")
        records += run_model(model_cases)

    summary = summarize(records)
    RESULTS_PATH.write_text(
        json.dumps({"generated_at": datetime.now().isoformat(), "summary": summary, "records": records},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_report(records, summary, offline=bool(args.offline) or args.suite == "deterministic")

    overall = summary["overall"]
    print(f"\n总计 {overall['scored']} 个评分用例：通过 {overall['passed']}，失败 {overall['failed']}，"
          f"准确率 {overall['accuracy'] * 100:.1f}%")
    print(f"报告已写入 {REPORT_PATH}")

    det_failed = any(r["passed"] is False for r in records if r["kind"] == "deterministic")
    return 1 if det_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
