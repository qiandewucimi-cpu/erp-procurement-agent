from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill


BASE_DIR = Path(__file__).resolve().parent


def write_sample(filename: str, rows: list[list[object]]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "BOM"
    sheet.append(["物料编码", "物料名称", "数量", "单位"])
    for row in rows:
        sheet.append(row)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
    for width, column in zip((18, 22, 12, 10), ("A", "B", "C", "D")):
        sheet.column_dimensions[column].width = width
    sheet.freeze_panes = "A2"
    workbook.save(BASE_DIR / "samples" / filename)


if __name__ == "__main__":
    write_sample(
        "正常示例_BOM.xlsx",
        [
            ["MAT-FAB-001", "再生涤纶面料", 1200, "米"],
            ["MAT-ZIP-002", "尼龙拉链", 800, "条"],
            ["MAT-LBL-003", "洗水唛", 800, "个"],
        ],
    )
    write_sample(
        "异常示例_BOM.xlsx",
        [
            ["MAT-FAB-001", "涤纶面料（旧名称）", 1200, "米"],
            ["MAT-UNKNOWN-999", "未建档辅料", 500, "个"],
            ["MAT-ZIP-002", "尼龙拉链", 0, "条"],
        ],
    )
    print("已生成 2 份完全合成的 BOM 示例。")

