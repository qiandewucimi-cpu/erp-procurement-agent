import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

import api as api_module
from erp_agent.llm import AgentLoop, IntentClassifier


ROOT = Path(__file__).resolve().parents[1]


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 隔离测试数据库，并固定走离线意图识别，避免依赖外部模型。
        cls.db_path = ROOT / "data" / f"api_test_{uuid4().hex}.db"
        cls.repository = api_module.ERPRepository(cls.db_path)
        cls.agent = api_module.PurchasePOAgent(
            cls.repository,
            api_module.KnowledgeBase(ROOT / "knowledge"),
            ROOT / "samples",
            intent_classifier=IntentClassifier(base_url=""),
            agent_loop=AgentLoop(base_url=""),
        )
        api_module.repository = cls.repository
        api_module.agent = cls.agent
        cls.client = TestClient(api_module.app)

    @classmethod
    def tearDownClass(cls):
        if cls.db_path.exists():
            cls.db_path.unlink()

    def test_health_declares_synthetic_mode(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["production_connected"], False)

    def test_prepare_normal_then_confirm_idempotent(self):
        prepared = self.client.post(
            "/agent/prepare",
            json={"task": "根据 BOM 生成采购 PO", "filename": "正常示例_BOM.xlsx"},
        )
        self.assertEqual(prepared.status_code, 200)
        action_id = prepared.json()["action_id"]
        self.assertEqual(prepared.json()["status"], "ready_for_confirmation")

        first = self.client.post(
            "/agent/confirm",
            json={"action_id": action_id, "confirmation": "确认提交", "operator": "api_tester"},
        )
        second = self.client.post(
            "/agent/confirm",
            json={"action_id": action_id, "confirmation": "确认提交", "operator": "api_tester"},
        )
        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.json()["idempotent"])
        self.assertTrue(second.json()["idempotent"])

    def test_confirm_wrong_password_returns_409(self):
        prepared = self.client.post(
            "/agent/prepare",
            json={"task": "根据 BOM 生成采购 PO", "filename": "正常示例_BOM.xlsx"},
        )
        action_id = prepared.json()["action_id"]
        response = self.client.post(
            "/agent/confirm",
            json={"action_id": action_id, "confirmation": "确定", "operator": "api_tester"},
        )
        self.assertEqual(response.status_code, 409)

    def test_confirm_unknown_action_returns_404(self):
        response = self.client.post(
            "/agent/confirm",
            json={"action_id": "ACT-NOTEXIST", "confirmation": "确认提交", "operator": "api_tester"},
        )
        self.assertEqual(response.status_code, 404)

    def test_prepare_missing_file_returns_400(self):
        response = self.client.post(
            "/agent/prepare",
            json={"task": "根据 BOM 生成采购 PO", "filename": "不存在.xlsx"},
        )
        self.assertEqual(response.status_code, 400)

    def test_chat_without_model_uses_safe_deterministic_fallback(self):
        session_id = uuid4().hex
        prepared = self.client.post(
            "/agent/chat",
            json={
                "session_id": session_id,
                "messages": [{"role": "user", "content": "根据正常示例_BOM.xlsx生成采购 PO 草稿，先给我看金额"}],
            },
        )
        self.assertEqual(prepared.status_code, 200)
        body = prepared.json()
        self.assertFalse(body["llm_enabled"])
        self.assertIn("¥24164", body["reply"])
        self.assertEqual(body["tool_trace"][0]["tool"], "create_purchase_order")

        detail = self.client.post(
            "/agent/chat",
            json={"session_id": session_id, "messages": [{"role": "user", "content": "查看具体金额"}]},
        )
        self.assertEqual(detail.status_code, 200)
        detail_reply = detail.json()["reply"]
        self.assertIn("采购 PO 金额明细", detail_reply)
        self.assertIn("MAT-FAB-001", detail_reply)
        self.assertIn("单价 ¥18.6", detail_reply)
        self.assertIn("包装费 ¥0.35", detail_reply)
        self.assertIn("¥22740", detail_reply)
        self.assertIn("合计：¥24164", detail_reply)

        confirmed = self.client.post(
            "/agent/chat",
            json={"session_id": session_id, "messages": [{"role": "user", "content": "确认提交"}]},
        )
        self.assertEqual(confirmed.status_code, 200)
        self.assertIn("已写入模拟 ERP", confirmed.json()["reply"])

    def test_exact_confirmation_bypasses_online_model_choice(self):
        session_id = uuid4().hex
        raw = self.agent.tools.call("create_purchase_order", {"filename": "正常示例_BOM.xlsx"})
        self.agent.sessions[session_id] = [{"role": "tool", "content": raw}]
        original_loop = self.agent.loop
        self.agent.loop = AgentLoop(base_url="http://model.invalid/v1")
        try:
            with patch.object(self.agent.loop, "run") as model_run:
                result = self.agent.chat(
                    [{"role": "user", "content": "确认提交"}], session_id=session_id
                )
        finally:
            self.agent.loop = original_loop
        model_run.assert_not_called()
        self.assertIn("已写入模拟 ERP", result["reply"])
        self.assertEqual(result["tool_trace"][0]["tool"], "confirm_commit")

    def test_amount_detail_bypasses_online_model_and_uses_tool_draft(self):
        session_id = uuid4().hex
        raw = self.agent.tools.call("create_purchase_order", {"filename": "正常示例_BOM.xlsx"})
        self.agent.sessions[session_id] = [{"role": "tool", "content": raw}]
        original_loop = self.agent.loop
        self.agent.loop = AgentLoop(base_url="http://model.invalid/v1")
        try:
            with patch.object(self.agent.loop, "run") as model_run:
                result = self.agent.chat(
                    [{"role": "user", "content": "查看具体金额"}], session_id=session_id
                )
        finally:
            self.agent.loop = original_loop
        model_run.assert_not_called()
        self.assertIn("MAT-ZIP-002", result["reply"])
        self.assertIn("合计：¥24164", result["reply"])


if __name__ == "__main__":
    unittest.main()
