import unittest
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

import api as api_module
from erp_agent.llm import IntentClassifier


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


if __name__ == "__main__":
    unittest.main()
