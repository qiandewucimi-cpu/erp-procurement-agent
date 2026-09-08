from __future__ import annotations

# 错误类型注册表：key 供代码引用，label 供报告展示，level 决定是否阻断。
ERROR_TYPES: dict[str, dict] = {
    "empty_code": {"label": "编码为空", "level": "blocking"},
    "invalid_qty": {"label": "数量非法", "level": "blocking"},
    "not_filed": {"label": "未建档", "level": "blocking"},
    "name_mismatch": {"label": "名称不一致", "level": "warning"},
    "missing_price": {"label": "单价缺失", "level": "blocking"},
    "missing_packaging": {"label": "包装费缺失", "level": "warning"},
    "missing_supplier": {"label": "供应商缺失", "level": "blocking"},
}


def _num(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class MaterialValidator:
    """物料单行校验器：一条 BOM 行 + 档案记录 → 结构化错误列表。

    只做确定性校验，不参与金额计算、不写库；可被「生成采购单」和「物料错误检测」复用。
    """

    def validate_row(self, code: str, name: str, quantity, ref: dict | None) -> list[dict]:
        issues: list[dict] = []

        if not code:
            issues.append(self._issue("empty_code", "物料编码", "物料编码不能为空"))
            return issues  # 没有编码，后续无法查档案

        qty = _num(quantity)
        if qty is None or qty <= 0:
            issues.append(self._issue("invalid_qty", f"{code}.数量", "数量必须是大于 0 的数字"))

        if ref is None:
            issues.append(self._issue("not_filed", code, "物料未建档，需人工建档或修正编码"))
            return issues

        if name and name != ref["material_name"]:
            issues.append(
                self._issue(
                    "name_mismatch",
                    code,
                    f"BOM 名称“{name}”与档案“{ref['material_name']}”不一致，以档案为准",
                )
            )

        price = _num(ref.get("unit_price"))
        if price is None or price <= 0:
            issues.append(self._issue("missing_price", code, "采购单价缺失或非正数"))

        packaging = _num(ref.get("packaging_fee"))
        if packaging is None or packaging < 0:
            issues.append(self._issue("missing_packaging", code, "包装费缺失"))

        if not ref.get("supplier_code") or not ref.get("supplier_name"):
            issues.append(self._issue("missing_supplier", code, "供应商信息缺失"))

        return issues

    @staticmethod
    def _issue(type_key: str, field: str, message: str) -> dict:
        meta = ERROR_TYPES[type_key]
        return {
            "type": type_key,
            "label": meta["label"],
            "level": meta["level"],
            "field": field,
            "message": message,
        }


class MaterialAuditor:
    """批量审计：跑完整份 BOM，产出错误报告（分级汇总 + 可推送文本）。"""

    def __init__(self, repository):
        self.repository = repository
        self.validator = MaterialValidator()

    def audit_bom(self, rows: list[dict], min_level: str = "warning") -> dict:
        errors: list[dict] = []
        for index, row in enumerate(rows, 1):
            code = row.get("material_code") or ""
            ref = self.repository.material(code) if code else None
            for issue in self.validator.validate_row(code, row.get("material_name"), row.get("quantity"), ref):
                errors.append({"row": index, "material_code": code or "(空)", **issue})

        if min_level == "blocking":
            errors = [e for e in errors if e["level"] == "blocking"]

        blocking = sum(1 for e in errors if e["level"] == "blocking")
        warning = len(errors) - blocking

        by_type: dict = {}
        for e in errors:
            t = e["type"]
            if t not in by_type:
                by_type[t] = {"label": e["label"], "level": e["level"], "count": 0}
            by_type[t]["count"] += 1

        summary = {
            "total_rows": len(rows),
            "error_count": len(errors),
            "blocking": blocking,
            "warning": warning,
            "by_type": by_type,
        }
        return {
            "errors": errors,
            "summary": summary,
            "push_text": self._build_push_text(summary, errors),
        }

    @staticmethod
    def _build_push_text(summary: dict, errors: list[dict]) -> str:
        if not errors:
            return f"【物料错误报告】共 {summary['total_rows']} 行，未发现问题 ✅"
        lines = [
            f"【物料错误报告】共 {summary['total_rows']} 行，发现 {summary['error_count']} 个问题"
            f"（阻断 {summary['blocking']} / 警告 {summary['warning']}）"
        ]
        for e in errors:
            tag = "阻断" if e["level"] == "blocking" else "警告"
            lines.append(f"- [{tag}] 第{e['row']}行 {e['material_code']}：{e['message']}")
        return "\n".join(lines)
