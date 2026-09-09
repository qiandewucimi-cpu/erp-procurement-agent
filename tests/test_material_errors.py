import json
import unittest
from pathlib import Path
from uuid import uuid4

from erp_agent.knowledge import KnowledgeBase
from erp_agent.parser import parse_bom
from erp_agent.repository import ERPRepository
from erp_agent.tools import ToolRegistry
from erp_agent.validator import MaterialAuditor, MaterialValidator


ROOT = Path(__file__).resolve().parents[1]

VALID_REF = {
    "material_code": "MAT-FAB-001",
    "material_name": "再生涤纶面料",
    "supplier_code": "SUP-001",
    "supplier_name": "示例纺织供应商",
    "unit_price": 18.60,
    "packaging_fee": 0.35,
    "currency": "CNY",
}


class ValidatorTest(unittest.TestCase):
    """校验器单测：覆盖 7 种错误类型 + 正常通过。"""

    def setUp(self):
        self.validator = MaterialValidator()

    def test_empty_code_is_blocking(self):
        issues = self.validator.validate_row("", "", 5, None)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["type"], "empty_code")
        self.assertEqual(issues[0]["level"], "blocking")

    def test_invalid_qty_is_blocking(self):
        issues = self.validator.validate_row("MAT-FAB-001", "再生涤纶面料", 0, VALID_REF)
        self.assertTrue(any(i["type"] == "invalid_qty" for i in issues))

    def test_not_filed_is_blocking(self):
        issues = self.validator.validate_row("MAT-XXX", "x", 5, None)
        self.assertTrue(any(i["type"] == "not_filed" for i in issues))

    def test_name_mismatch_is_warning(self):
        issues = self.validator.validate_row("MAT-FAB-001", "旧名称", 5, VALID_REF)
        self.assertTrue(any(i["type"] == "name_mismatch" and i["level"] == "warning" for i in issues))

    def test_missing_price_is_blocking(self):
        issues = self.validator.validate_row("MAT-FAB-001", "再生涤纶面料", 5, dict(VALID_REF, unit_price=0))
        self.assertTrue(any(i["type"] == "missing_price" for i in issues))

    def test_missing_packaging_is_warning(self):
        issues = self.validator.validate_row("MAT-FAB-001", "再生涤纶面料", 5, dict(VALID_REF, packaging_fee=-1))
        self.assertTrue(any(i["type"] == "missing_packaging" for i in issues))

    def test_missing_supplier_is_blocking(self):
        issues = self.validator.validate_row(
            "MAT-FAB-001", "再生涤纶面料", 5, dict(VALID_REF, supplier_code="", supplier_name="")
        )
        self.assertTrue(any(i["type"] == "missing_supplier" for i in issues))

    def test_clean_row_has_no_issues(self):
        self.assertEqual(self.validator.validate_row("MAT-FAB-001", "再生涤纶面料", 5, VALID_REF), [])


class AuditorAndToolTest(unittest.TestCase):
    def setUp(self):
        # 使用项目内的明确文件，避免 Windows 临时目录 ACL 阻止 SQLite 打开。
        self.db_path = ROOT / "data" / f"test_{uuid4().hex}.db"
        self.repository = ERPRepository(self.db_path)
        self.auditor = MaterialAuditor(self.repository)
        self.tools = ToolRegistry(self.repository, KnowledgeBase(ROOT / "knowledge"), ROOT / "samples")

    def tearDown(self):
        if self.db_path.exists():
            self.db_path.unlink()

    def test_auditor_reports_three_errors_on_bad_bom(self):
        content = (ROOT / "samples" / "异常示例_BOM.xlsx").read_bytes()
        report = self.auditor.audit_bom(parse_bom("异常示例_BOM.xlsx", content))
        self.assertEqual(report["summary"]["total_rows"], 3)
        self.assertEqual(report["summary"]["error_count"], 3)
        self.assertEqual(report["summary"]["blocking"], 2)
        self.assertEqual(report["summary"]["warning"], 1)

    def test_auditor_clean_bom_has_no_errors(self):
        content = (ROOT / "samples" / "正常示例_BOM.xlsx").read_bytes()
        report = self.auditor.audit_bom(parse_bom("正常示例_BOM.xlsx", content))
        self.assertEqual(report["summary"]["error_count"], 0)

    def test_tool_detect_on_bad_bom(self):
        result = json.loads(self.tools.call("detect_material_errors", {"filename": "异常示例_BOM.xlsx"}))
        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"]["error_count"], 3)
        self.assertFalse(result["pushed"])
        self.assertIsNone(result["report_id"])
        self.assertIn("阻断", result["push_text"])

    def test_tool_min_level_blocking_filters_warnings(self):
        result = json.loads(
            self.tools.call("detect_material_errors", {"filename": "异常示例_BOM.xlsx", "min_level": "blocking"})
        )
        self.assertEqual(result["summary"]["error_count"], 2)
        self.assertEqual(result["summary"]["warning"], 0)

    def test_tool_push_saves_report_and_audit(self):
        result = json.loads(
            self.tools.call("detect_material_errors", {"filename": "异常示例_BOM.xlsx", "push": True})
        )
        self.assertTrue(result["pushed"])
        self.assertTrue(result["report_id"].startswith("ERR-"))
        reports = self.repository.error_reports()
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]["report_id"], result["report_id"])
        self.assertIn("ERROR_REPORT_CREATED", [a["event"] for a in self.repository.audits()])

    def test_tool_missing_file(self):
        result = json.loads(self.tools.call("detect_material_errors", {"filename": "不存在.xlsx"}))
        self.assertFalse(result["ok"])
        self.assertIn("找不到 BOM 文件", result["error"])


if __name__ == "__main__":
    unittest.main()
