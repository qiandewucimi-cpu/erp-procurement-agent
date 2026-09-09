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


MATERIAL_ALIASES = {
    "物料编码": {"物料编码", "物料编号", "material_code", "code", "sku"},
    "物料名称": {"物料名称", "品名", "material_name", "name"},
    "供应商编码": {"供应商编码", "供应商编号", "supplier_code"},
    "供应商名称": {"供应商名称", "供应商", "supplier_name"},
    "单价": {"单价", "采购单价", "含税单价", "unit_price", "price"},
    "包装费": {"包装费", "包装单价", "packaging_fee"},
    "币种": {"币种", "货币", "币别", "currency"},
}


def _canonical_material(header: object) -> str:
    value = str(header or "").strip().lower()
    for canonical, aliases in MATERIAL_ALIASES.items():
        if value in {alias.lower() for alias in aliases}:
            return canonical
    return str(header or "").strip()


def parse_materials(filename: str, content: bytes | None = None) -> list[dict]:
    """解析物料档案表（物料主数据），用于把用户自己的物料导入模拟 ERP。

    必需列：物料编码、单价。可选列：物料名称、供应商编码、供应商名称、包装费、币种。
    支持 .xlsx / .xlsm / .csv，列名同 ALIASES 兼容中英文写法。
    """
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        text = (content or Path(filename).read_bytes()).decode("utf-8-sig")
        raw_rows = list(csv.DictReader(StringIO(text)))
    elif suffix in {".xlsx", ".xlsm"}:
        source: BinaryIO | str = BytesIO(content) if content is not None else filename
        workbook = load_workbook(source, read_only=True, data_only=True)
        values = list(workbook.active.iter_rows(values_only=True))
        if not values:
            return []
        headers = [_canonical_material(value) for value in values[0]]
        raw_rows = [dict(zip(headers, row)) for row in values[1:]]
    else:
        raise ValueError("仅支持 .xlsx、.xlsm 或 .csv 格式的物料档案")

    if raw_rows and "物料编码" not in {_canonical_material(k) for k in raw_rows[0]}:
        raise ValueError("物料档案缺少「物料编码」列；必需列：物料编码、单价")

    result = []
    for row in raw_rows:
        item = {_canonical_material(k): v for k, v in row.items() if k is not None}
        if not any(v not in (None, "") for v in item.values()):
            continue
        result.append(
            {
                "material_code": str(item.get("物料编码") or "").strip(),
                "material_name": str(item.get("物料名称") or "").strip(),
                "supplier_code": str(item.get("供应商编码") or "").strip(),
                "supplier_name": str(item.get("供应商名称") or "").strip(),
                "unit_price": item.get("单价"),
                "packaging_fee": item.get("包装费"),
                "currency": str(item.get("币种") or "").strip(),
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

