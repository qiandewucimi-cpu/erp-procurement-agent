from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from erp_agent.knowledge import KnowledgeBase
from erp_agent.llm import AgentLoop
from erp_agent.repository import ERPRepository
from erp_agent.tools import ToolRegistry


ROOT = Path(__file__).resolve().parent.parent


class TestToolRegistry(unittest.TestCase):
    """工具层：确定性业务逻辑（金额、校验、写入口令）不依赖模型与网络。"""

    @classmethod
    def setUpClass(cls):
        cls.repo = ERPRepository(ROOT / "data" / "_test_tools.db")
        cls.tools = ToolRegistry(cls.repo, KnowledgeBase(ROOT / "knowledge"), ROOT / "samples")

    @classmethod
    def tearDownClass(cls):
        (ROOT / "data" / "_test_tools.db").unlink(missing_ok=True)

    def test_create_purchase_order_normal(self):
        result = json.loads(self.tools.call("create_purchase_order", {"filename": "正常示例_BOM.xlsx"}))
        self.assertTrue(result["ok"])
        self.assertTrue(result["ready"])
        self.assertEqual(result["total_amount"], 24164.0)
        self.assertIn("action_id", result)

    def test_create_purchase_order_abnormal_blocked(self):
        result = json.loads(self.tools.call("create_purchase_order", {"filename": "异常示例_BOM.xlsx"}))
        self.assertTrue(result["ok"])
        self.assertFalse(result["ready"])
        self.assertTrue(any(i["level"] == "blocking" for i in result["issues"]))

    def test_confirm_wrong_password_rejected(self):
        result = json.loads(self.tools.call("create_purchase_order", {"filename": "正常示例_BOM.xlsx"}))
        confirm = json.loads(self.tools.call("confirm_commit", {"action_id": result["action_id"], "confirmation": "确定"}))
        self.assertFalse(confirm["ok"])

    def test_confirm_correct_and_idempotent(self):
        result = json.loads(self.tools.call("create_purchase_order", {"filename": "正常示例_BOM.xlsx"}))
        aid = result["action_id"]
        c1 = json.loads(self.tools.call("confirm_commit", {"action_id": aid, "confirmation": "确认提交"}))
        self.assertTrue(c1["ok"])
        c2 = json.loads(self.tools.call("confirm_commit", {"action_id": aid, "confirmation": "确认提交"}))
        self.assertTrue(c2["ok"])
        self.assertTrue(c2.get("idempotent"))

    def test_rollback(self):
        result = json.loads(self.tools.call("create_purchase_order", {"filename": "正常示例_BOM.xlsx"}))
        aid = result["action_id"]
        self.tools.call("confirm_commit", {"action_id": aid, "confirmation": "确认提交"})
        rb = json.loads(self.tools.call("rollback_po", {"action_id": aid, "reason": "测试回滚"}))
        self.assertTrue(rb["ok"])
        self.assertEqual(rb["status"], "ROLLED_BACK")

    def test_query_materials(self):
        result = json.loads(self.tools.call("query_materials", {"material_codes": ["MAT-FAB-001", "NOT-EXIST"]}))
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["found"]), 1)
        self.assertEqual(result["missing"], ["NOT-EXIST"])


class TestAgentLoop(unittest.TestCase):
    """工具调用循环：模型自主决定调用工具与参数（mock 模型，不依赖网络）。"""

    @classmethod
    def setUpClass(cls):
        cls.repo = ERPRepository(ROOT / "data" / "_test_loop.db")
        cls.tools = ToolRegistry(cls.repo, KnowledgeBase(ROOT / "knowledge"), ROOT / "samples")

    @classmethod
    def tearDownClass(cls):
        (ROOT / "data" / "_test_loop.db").unlink(missing_ok=True)

    def test_loop_tool_call_then_reply(self):
        loop = AgentLoop(base_url="http://x/v1", model="m")
        responses = [
            {
                "content": None,
                "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "query_materials", "arguments": '{"material_codes": ["MAT-FAB-001"]}'}}
                ],
            },
            {"content": "查到了，单价 18.6 元。", "tool_calls": []},
        ]
        with patch.object(loop, "_chat", side_effect=responses):
            reply, trace, full = loop.run([{"role": "user", "content": "查一下价格"}], self.tools)
        self.assertEqual(reply, "查到了，单价 18.6 元。")
        self.assertEqual(len(trace), 1)
        self.assertEqual(trace[0]["tool"], "query_materials")

    def test_loop_direct_reply_without_tools(self):
        loop = AgentLoop(base_url="http://x/v1", model="m")
        with patch.object(loop, "_chat", return_value={"content": "你好", "tool_calls": []}):
            reply, trace, full = loop.run([{"role": "user", "content": "你好"}], self.tools)
        self.assertEqual(reply, "你好")
        self.assertEqual(trace, [])

    def test_loop_returns_full_history_for_multiturn(self):
        loop = AgentLoop(base_url="http://x/v1", model="m")
        responses = [
            {"content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "query_materials", "arguments": '{"material_codes": ["MAT-FAB-001"]}'}}]},
            {"content": "done", "tool_calls": []},
        ]
        with patch.object(loop, "_chat", side_effect=responses):
            reply, trace, full = loop.run([{"role": "user", "content": "查"}], self.tools)
        self.assertGreater(len(full), 1)  # 包含 user + assistant + tool 消息
        roles = [m["role"] for m in full]
        self.assertIn("tool", roles)


if __name__ == "__main__":
    unittest.main()
