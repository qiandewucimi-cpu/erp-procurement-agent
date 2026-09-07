from __future__ import annotations

import csv
from io import BytesIO, StringIO
from pathlib import Path
from typing import BinaryIO

from openpyxl import load_workbook


ALIASES = {
    "物料编码": {"物料编码", "物料编号", "material_code", "sku"},
    "物料名称": {"物料名称", "品名", "material_name"},
    "数量": {"数量", "采购数量", "qty", "quantity"},
    "单位": {"单位", "unit"},
}


def _canonical(header: object) -> str:
    value = str(header or "").strip().lower()
    for canonical, aliases in ALIASES.items():
        if value in {alias.lower() for alias in aliases}:
            return canonical
    return str(header or "").strip()


def _normalize(rows: list[dict]) -> list[dict]:
    result = []
    for row in rows:
        normalized = {_canonical(k): v for k, v in row.items()}
        if not any(v not in (None, "") for v in normalized.values()):
            continue
        result.append(
            {
                "material_code": str(normalized.get("物料编码") or "").strip(),
                "material_name": str(normalized.get("物料名称") or "").strip(),
                "quantity": normalized.get("数量"),
                "unit": str(normalized.get("单位") or "").strip(),
            }
        )
    return result


def parse_bom(filename: str, content: bytes | None = None) -> list[dict]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        text = (content or Path(filename).read_bytes()).decode("utf-8-sig")
        return _normalize(list(csv.DictReader(StringIO(text))))
    if suffix not in {".xlsx", ".xlsm"}:
        raise ValueError("仅支持 .xlsx、.xlsm 或 .csv 格式的 BOM")
    source: BinaryIO | str = BytesIO(content) if content is not None else filename
    workbook = load_workbook(source, read_only=True, data_only=True)
    sheet = workbook.active
    values = list(sheet.iter_rows(values_only=True))
    if not values:
        return []
    headers = [_canonical(value) for value in values[0]]
    rows = [dict(zip(headers, row)) for row in values[1:]]
    return _normalize(rows)

