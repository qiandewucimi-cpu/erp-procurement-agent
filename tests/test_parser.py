import unittest

from erp_agent.parser import parse_bom


class ParserTest(unittest.TestCase):
    def test_csv_with_utf8_bom_and_aliases(self):
        csv_text = "material_code,品名,qty,unit\nMAT-FAB-001,再生涤纶面料,1200,米\n"
        rows = parse_bom("demo.csv", csv_text.encode("utf-8-sig"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["material_code"], "MAT-FAB-001")
        self.assertEqual(rows[0]["material_name"], "再生涤纶面料")
        self.assertEqual(rows[0]["unit"], "米")

    def test_header_aliases_map_to_canonical(self):
        csv_text = "SKU,material_name,quantity,单位\nMAT-001,面料,5,米\n"
        rows = parse_bom("demo.csv", csv_text.encode())
        self.assertEqual(rows[0]["material_code"], "MAT-001")
        self.assertEqual(rows[0]["quantity"], "5")
        self.assertEqual(rows[0]["unit"], "米")

    def test_blank_rows_are_skipped(self):
        csv_text = "物料编码,物料名称,数量,单位\nMAT-001,面料,5,米\n,,,\n\nMAT-002,拉链,2,条\n"
        rows = parse_bom("demo.csv", csv_text.encode("utf-8-sig"))
        self.assertEqual(len(rows), 2)

    def test_unsupported_format_raises(self):
        with self.assertRaises(ValueError):
            parse_bom("demo.txt", b"whatever")

    def test_empty_xlsx_returns_empty(self):
        from io import BytesIO
        from openpyxl import Workbook

        buf = BytesIO()
        wb = Workbook()
        wb.active.append([])
        wb.save(buf)
        rows = parse_bom("empty.xlsx", buf.getvalue())
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
