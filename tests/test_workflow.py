import unittest
from pathlib import Path
from uuid import uuid4

from erp_agent.agent import PurchasePOAgent
from erp_agent.knowledge import KnowledgeBase
from erp_agent.repository import ERPRepository


ROOT = Path(__file__).resolve().parents[1]


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        # 使用项目内的明确文件，避免 Windows 临时目录 ACL 阻止 SQLite 打开。
        self.db_path = ROOT / "data" / f"test_{uuid4().hex}.db"
        repository = ERPRepository(self.db_path)
        self.repository = repository
        self.agent = PurchasePOAgent(repository, KnowledgeBase(ROOT / "knowledge"), ROOT / "samples")

    def tearDown(self):
        if self.db_path.exists():
            self.db_path.unlink()

    def test_happy_path_confirm_is_idempotent_and_can_rollback(self):
        preview = self.agent.prepare("根据 BOM 生成采购 PO，写入前确认", "正常示例_BOM.xlsx")
        self.assertEqual(preview.status, "ready_for_confirmation")
        self.assertEqual(len(preview.draft["items"]), 3)
        first = self.repository.confirm(preview.action_id, "确认提交", "tester")
        second = self.repository.confirm(preview.action_id, "确认提交", "tester")
        self.assertFalse(first["idempotent"])
        self.assertTrue(second["idempotent"])
        rolled_back = self.repository.rollback(preview.action_id, "测试回滚", "tester")
        self.assertEqual(rolled_back["status"], "ROLLED_BACK")

    def test_bad_bom_is_blocked(self):
        preview = self.agent.prepare("根据 BOM 生成采购 PO", "异常示例_BOM.xlsx")
        self.assertEqual(preview.status, "blocked")
        self.assertTrue(any(issue.level == "blocking" for issue in preview.issues))
        with self.assertRaises(ValueError):
            self.repository.confirm(preview.action_id, "确认提交", "tester")

    def test_wrong_confirmation_is_rejected(self):
        preview = self.agent.prepare("根据 BOM 生成采购 PO", "正常示例_BOM.xlsx")
        with self.assertRaises(ValueError):
            self.repository.confirm(preview.action_id, "确定", "tester")


if __name__ == "__main__":
    unittest.main()
