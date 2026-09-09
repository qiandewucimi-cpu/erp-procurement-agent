"""物料档案导入测试：解析、落库、工具层与「导入后自己的 BOM 能跑通」端到端。"""

import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from erp_agent.knowledge import KnowledgeBase
from erp_agent.parser import parse_materials
from erp_agent.repository import ERPRepository
from erp_agent.tools import ToolRegistry


ROOT = Path(__file__).resolve().parents[1]

MASTER_CSV = (
    "物料编码,物料名称,供应商编码,供应商名称,单价,包装费,币种\n"
    "MY-FAB-100,自定义面料,SUP-900,自定义供应商,25.80,0.40,CNY\n"
    "MY-ACC-200,自定义辅料,SUP-900,自定义供应商,3.20,0.10,CNY\n"
)

BOM_CSV = (
    "物料编码,物料名称,数量,单位\n"
    "MY-FAB-100,自定义面料,100,米\n"
    "MY-ACC-200,自定义辅料,200,个\n"
)


def make_registry(tmp: Path) -> ToolRegistry:
    db = ROOT / "data" / f"test_import_{uuid4().hex}.db"
    return ToolRegistry(
        ERPRepository(db),
        KnowledgeBase(ROOT / "knowledge"),
        ROOT / "samples",
        uploads_dir=tmp,
    )


class ParseMaterialsTest(unittest.TestCase):
    def test_parse_template_file(self):
        rows = parse_materials("物料档案模板.xlsx", (ROOT / "samples" / "物料档案模板.xlsx").read_bytes())
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["material_code"], "MY-FAB-100")
        self.assertEqual(rows[0]["supplier_code"], "SUP-900")
        self.assertEqual(rows[0]["currency"], "CNY")
        self.assertAlmostEqual(float(rows[0]["unit_price"]), 25.80, places=2)

    def test_parse_csv(self):
        rows = parse_materials("master.csv", MASTER_CSV.encode("utf-8"))
        self.assertEqual([r["material_code"] for r in rows], ["MY-FAB-100", "MY-ACC-200"])
        self.assertAlmostEqual(float(rows[1]["unit_price"]), 3.20, places=2)

    def test_missing_code_column_raises(self):
        bad = "物料名称,单价\n面料,10\n".encode("utf-8")
        with self.assertRaises(ValueError):
            parse_materials("bad.csv", bad)

    def test_unsupported_suffix_raises(self):
        with self.assertRaises(ValueError):
            parse_materials("a.txt", b"x")


class ImportMaterialsTest(unittest.TestCase):
    def setUp(self):
        self.db = ROOT / "data" / f"test_import_{uuid4().hex}.db"
        self.repo = ERPRepository(self.db)

    def tearDown(self):
        self.db.unlink(missing_ok=True)

    def test_import_then_update(self):
        rows = parse_materials("master.csv", MASTER_CSV.encode("utf-8"))
        first = self.repo.import_materials(rows)
        self.assertEqual(first["imported"], 2)
        self.assertEqual(first["updated"], 0)
        self.assertEqual(first["skipped"], [])

        second = self.repo.import_materials(rows)
        self.assertEqual(second["imported"], 0)
        self.assertEqual(second["updated"], 2)

    def test_skip_bad_rows_without_aborting_batch(self):
        rows = [
            {"material_code": "", "material_name": "无编码", "unit_price": 1},
            {"material_code": "BAD-PRICE", "unit_price": "abc"},
            {"material_code": "NEG", "unit_price": -5},
            {"material_code": "GOOD-1", "unit_price": 9.9},
        ]
        result = self.repo.import_materials(rows)
        self.assertEqual(result["imported"], 1)
        self.assertEqual(len(result["skipped"]), 3)
        self.assertEqual(result["skipped"][0]["reason"], "物料编码为空")
        self.assertEqual(result["skipped"][1]["reason"], "单价缺失或不是数字")
        self.assertEqual(result["skipped"][2]["reason"], "单价或包装费为负数")
        self.assertIsNotNone(self.repo.material("GOOD-1"))

    def test_defaults_for_optional_columns(self):
        result = self.repo.import_materials([{"material_code": "X-1", "unit_price": 5}])
        self.assertEqual(result["imported"], 1)
        ref = self.repo.material("X-1")
        self.assertEqual(ref["currency"], "CNY")
        self.assertEqual(ref["supplier_code"], "SUP-IMPORTED")
        self.assertEqual(ref["material_name"], "X-1")


class ImportToolTest(unittest.TestCase):
    def test_tool_imports_and_then_bom_is_recognized(self):
        """端到端：导入自己的档案 → 自己的 BOM 不再被判「未建档」。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "master.csv").write_text(MASTER_CSV, encoding="utf-8")
            (tmp / "my_bom.csv").write_text(BOM_CSV, encoding="utf-8")

            tools = make_registry(tmp)
            self.addCleanup(lambda: (ROOT / "data" / tools.repository.db_path.name).unlink(missing_ok=True))

            imported = json.loads(tools.call("import_material_master", {"filename": "master.csv"}))
            self.assertTrue(imported["ok"])
            self.assertEqual(imported["imported"], 2)
            self.assertEqual(imported["updated"], 0)

            detected = json.loads(tools.call("detect_material_errors", {"filename": "my_bom.csv"}))
            self.assertTrue(detected["ok"])
            self.assertEqual(detected["summary"]["blocking"], 0, "导入档案后不应再有未建档阻断")

    def test_tool_reports_missing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tools = make_registry(Path(tmpdir))
            self.addCleanup(lambda: (ROOT / "data" / tools.repository.db_path.name).unlink(missing_ok=True))
            result = json.loads(tools.call("import_material_master", {"filename": "不存在.csv"}))
            self.assertFalse(result["ok"])


class ImportApiTest(unittest.TestCase):
    """API 层测试。

    注意：其他测试（test_api.py）会替换 api 模块的全局 repository 为临时库并在结束时删除，
    因此这里必须自带一个干净的 repository/agent，跑完再恢复，否则会撞上已被删除的库。
    """

    def setUp(self):
        import api as api_module
        from erp_agent.agent import PurchasePOAgent

        self.api_module = api_module
        self._orig_repository = api_module.repository
        self._orig_agent = api_module.agent
        self.db = ROOT / "data" / f"api_import_{uuid4().hex}.db"
        api_module.repository = ERPRepository(self.db)
        api_module.agent = PurchasePOAgent(
            api_module.repository,
            KnowledgeBase(ROOT / "knowledge"),
            ROOT / "samples",
        )

    def tearDown(self):
        self.api_module.repository = self._orig_repository
        self.api_module.agent = self._orig_agent
        self.db.unlink(missing_ok=True)

    def test_api_import_endpoint(self):
        from fastapi.testclient import TestClient

        client = TestClient(self.api_module.app)
        upstream = ROOT / "uploads"
        upstream.mkdir(parents=True, exist_ok=True)
        target = upstream / f"api_probe_{uuid4().hex}.csv"
        target.write_text(MASTER_CSV, encoding="utf-8")
        try:
            response = client.post("/materials/import", json={"filename": target.name})
            self.assertEqual(response.status_code, 200, msg=response.text)
            body = response.json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["imported"], 2)
            self.assertEqual(body["updated"], 0)

            listed = client.get("/materials").json()
            codes = {row["material_code"] for row in listed}
            self.assertIn("MY-FAB-100", codes)
        finally:
            target.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
