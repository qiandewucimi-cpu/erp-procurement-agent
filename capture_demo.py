"""Capture real deterministic tool outputs with synthetic data, no model/network.

python capture_demo.py --output docs/demo/trace.json
The output is a tool execution replay, not a chat UI recording.
"""
import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from erp_agent.knowledge import KnowledgeBase
from erp_agent.repository import ERPRepository
from erp_agent.security import AccessController, Actor
from erp_agent.tools import ToolRegistry

ROOT = Path(__file__).resolve().parent


def capture():
    events = []
    with tempfile.TemporaryDirectory(prefix="erp-public-demo-") as folder:
        repo = ERPRepository(Path(folder) / "demo.db")
        tools = ToolRegistry(repo, KnowledgeBase(ROOT / "knowledge"), ROOT / "samples",
                             access_controller=AccessController(enabled=True))
        operator = Actor("demo_operator", "operator")
        approver = Actor("demo_approver", "approver")
        viewer = Actor("demo_viewer", "viewer")

        def call(title, name, args, actor):
            result = json.loads(tools.call(name, args, actor))
            events.append({"title": title, "tool": name, "role": actor.role, "result": result})
            return result

        normal = call("01 正常 BOM：生成草稿", "create_purchase_order",
                      {"filename": "正常示例_BOM.xlsx"}, operator)
        assert normal["ready"] and normal["total_amount"] == 24164
        denied = call("02 权限：viewer 不可建单", "create_purchase_order",
                      {"filename": "正常示例_BOM.xlsx"}, viewer)
        assert not denied["ok"]
        abnormal = call("03 异常 BOM：阻断提交", "create_purchase_order",
                        {"filename": "异常示例_BOM.xlsx"}, operator)
        assert not abnormal["ready"]
        action = {"action_id": normal["action_id"]}
        approved = call("04 独立审批人：审核草稿", "approve_action", action, approver)
        assert approved["ok"]
        committed = call("05 精确确认：写入模拟单据", "confirm_commit",
                         {**action, "confirmation": "确认提交"}, approver)
        assert committed["ok"]
        repeated = call("06 重复确认：不重复建单", "confirm_commit",
                        {**action, "confirmation": "确认提交"}, approver)
        assert repeated["idempotent"] and len(repo.orders()) == 1
        events.append({"title": "07 审计：保留动作记录", "tool": "repository.audit",
                       "role": "local_test", "result": {"orders": len(repo.orders()), "audit": repo.audits()}})
    return {"recorded_at": datetime.now(timezone.utc).isoformat(),
            "mode": "deterministic_tool_replay_no_llm", "data": "synthetic",
            "events": events}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    trace = capture()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(trace, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"PASS: {len(trace['events'])} real execution steps; replay saved to {args.output}")


if __name__ == "__main__":
    main()
