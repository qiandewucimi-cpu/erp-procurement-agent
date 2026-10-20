import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from erp_agent.agent import PurchasePOAgent
from erp_agent.knowledge import KnowledgeBase
from erp_agent.repository import ERPRepository
from erp_agent.security import AccessController
from erp_agent.tools import ToolRegistry
from erp_agent.validator import MaterialValidator

ROOT = Path(__file__).resolve().parents[1]


class NumericBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = ERPRepository(self.base / "test.db")
        self.kb = KnowledgeBase(ROOT / "knowledge")
        self.access = AccessController(enabled=False)
        self.tools = ToolRegistry(self.repo, self.kb, self.base, access_controller=self.access)
        self.agent = PurchasePOAgent(self.repo, self.kb, self.base, access_controller=self.access)

    def check_blocked(self, quantity):
        content = f"物料编码,物料名称,数量,单位\nMAT-FAB-001,,{quantity},件\n".encode("utf-8")
        (self.base / "test.csv").write_bytes(content)
        tool = json.loads(self.tools.call("create_purchase_order", {"filename": "test.csv"}))
        self.assertFalse(tool["ready"])
        json.dumps(tool, allow_nan=False)
        with self.assertRaises(ValueError):
            self.repo.confirm(tool["action_id"], "确认提交", "reviewer")
        flow = self.agent.prepare("生成采购PO", "test.csv", base64.b64encode(content).decode())
        self.assertEqual(flow.status, "blocked")
        json.dumps(flow.draft, allow_nan=False)
        self.assertEqual(self.repo.orders(), [])

    def test_nonfinite_quantities_block_both_entrypoints(self):
        for value in ("nan", "inf", "-inf", "1e309"):
            with self.subTest(value=value):
                self.check_blocked(value)

    def test_amount_overflow_blocks_both_entrypoints(self):
        self.check_blocked("1e308")

    def test_invalid_adapter_price_blocks_both_entrypoints(self):
        ref = self.repo.material("MAT-FAB-001")
        for field in ("unit_price", "packaging_fee"):
            for value in (float("nan"), float("inf"), -1):
                with self.subTest(field=field, value=value):
                    with patch.object(self.repo, "material", return_value={**ref, field: value}):
                        self.check_blocked("1")

    def test_import_skips_nonfinite_prices_without_persisting(self):
        for field in ("unit_price", "packaging_fee"):
            for value in ("nan", "inf", "-inf"):
                with self.subTest(field=field, value=value):
                    row = {"material_code": "INVALID", "unit_price": 1, "packaging_fee": 0, field: value}
                    result = self.repo.import_materials([row])
                    self.assertEqual(result["imported"], 0)
                    self.assertEqual(len(result["skipped"]), 1)
                    self.assertIsNone(self.repo.material("INVALID"))

    def test_audit_rejects_nonfinite_quantity(self):
        ref = self.repo.material("MAT-FAB-001")
        issues = MaterialValidator().validate_row("MAT-FAB-001", "", "nan", ref)
        self.assertTrue(any(x["type"] == "invalid_qty" for x in issues))
