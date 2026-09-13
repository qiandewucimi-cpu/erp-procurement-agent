"""面试前一键证据冒烟：不依赖外部模型、网络或已有数据库。"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from erp_agent.knowledge import KnowledgeBase
from erp_agent.observability import METRICS
from erp_agent.repository import ERPRepository
from erp_agent.security import AccessController, Actor
from erp_agent.tools import ToolRegistry


ROOT = Path(__file__).resolve().parent

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass


def _call(tools: ToolRegistry, name: str, arguments: dict, actor: Actor) -> dict:
    return json.loads(tools.call(name, arguments, actor=actor))


def main() -> int:
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, condition: bool, detail: str) -> None:
        checks.append((name, condition, detail))
        print(f"[{'PASS' if condition else 'FAIL'}] {name}: {detail}")

    with tempfile.TemporaryDirectory(prefix="erp-agent-interview-") as temp_dir:
        repository = ERPRepository(Path(temp_dir) / "demo.db")
        access = AccessController(enabled=True)
        tools = ToolRegistry(repository, KnowledgeBase(ROOT / "knowledge"), ROOT / "samples", access_controller=access)
        viewer = Actor("viewer_interview", "viewer")
        operator = Actor("operator_interview", "operator")
        approver = Actor("approver_interview", "approver")
        METRICS.reset()

        normal = _call(tools, "create_purchase_order", {"filename": "正常示例_BOM.xlsx"}, operator)
        check("正常 BOM 生成待审批草稿", normal.get("ok") is True and normal.get("ready") is True, f"action={normal.get('action_id')}")
        check("金额由确定性工具算得 ¥24164", normal.get("total_amount") == 24164.0, f"total={normal.get('total_amount')}")

        denied = _call(tools, "create_purchase_order", {"filename": "正常示例_BOM.xlsx"}, viewer)
        check("viewer 越权写操作被拒绝", denied.get("ok") is False, denied.get("error", ""))

        action_id = str(normal["action_id"])
        approved = _call(tools, "approve_action", {"action_id": action_id}, approver)
        committed = _call(tools, "confirm_commit", {"action_id": action_id, "confirmation": "确认提交"}, approver)
        repeated = _call(tools, "confirm_commit", {"action_id": action_id, "confirmation": "确认提交"}, approver)
        check("职责分离审批后允许提交", approved.get("ok") is True and committed.get("ok") is True, f"po={committed.get('po_no')}")
        check("重复确认保持幂等", repeated.get("idempotent") is True and len(repository.orders()) == 1, f"orders={len(repository.orders())}")

        abnormal = _call(tools, "create_purchase_order", {"filename": "异常示例_BOM.xlsx"}, operator)
        blocking = sum(1 for item in abnormal.get("issues", []) if item.get("level") == "blocking")
        check("异常 BOM 被阻断", abnormal.get("ready") is False and blocking >= 2, f"blocking={blocking}")

        metric_ops = METRICS.snapshot()["operations"]
        check("工具指标可查询", "tool.create_purchase_order" in metric_ops, f"operations={len(metric_ops)}")

    passed = sum(1 for _, ok, _ in checks if ok)
    print(f"\n面试证据冒烟：{passed}/{len(checks)} 通过")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
