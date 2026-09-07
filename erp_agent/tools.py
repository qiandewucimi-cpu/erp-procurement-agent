from __future__ import annotations

import json
from pathlib import Path

from .knowledge import KnowledgeBase
from .models import ValidationIssue
from .parser import parse_bom
from .repository import ERPRepository


class ToolRegistry:
    """把「BOM → 采购 PO」的业务能力封装成可供模型调用的工具。

    安全边界（本项目的核心设计，务必保留）：
    - 金额计算：在工具内部由确定性代码完成，模型只传物料编码/文件名，不参与数字运算；
    - 业务校验：在工具内部由确定性代码完成，返回 ready 与 issues；
    - 写入权限：confirm_commit 强制要求「确认提交」口令 + 幂等 + 审计。

    模型能自主决定的是：调用哪个工具、传什么参数、调用顺序与次数。
    """

    def __init__(self, repository: ERPRepository, knowledge: KnowledgeBase, samples_dir: Path):
        self.repository = repository
        self.knowledge = knowledge
        self.samples_dir = samples_dir

    # ------------------------------------------------------------------ #
    # 工具 schema（OpenAI function-calling 格式，模型靠它理解工具）
    # ------------------------------------------------------------------ #
    @property
    def schemas(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_knowledge",
                    "description": "检索采购 PO 的业务规则库，了解字段含义、校验规则和安全要求。生成或校验采购单前应先调用它。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "要检索的关键词或问题，如「采购PO 必填字段」「包装费 写入确认」"},
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "query_materials",
                    "description": "查询物料档案、供应商、单价和包装费（只读，不生成任何单据）。当用户只想查价格、不想建单时用它。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "material_codes": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "物料编码列表，如 ['MAT-FAB-001', 'MAT-ZIP-002']",
                            },
                        },
                        "required": ["material_codes"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "create_purchase_order",
                    "description": "根据 BOM 文件生成采购 PO 草稿（内部自动完成：解析 BOM → 查物料档案 → 算金额 → 业务校验 → 生成待确认预览）。生成的只是预览，不会真正写入，需要用户确认后才写。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "filename": {"type": "string", "description": "BOM 文件名，如「正常示例_BOM.xlsx」或「异常示例_BOM.xlsx」"},
                        },
                        "required": ["filename"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "confirm_commit",
                    "description": "把已生成的采购 PO 草稿真正写入模拟 ERP。仅当用户明确输入了「确认提交」口令后才能调用，否则会失败。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action_id": {"type": "string", "description": "create_purchase_order 返回的 action_id"},
                            "confirmation": {"type": "string", "description": "用户输入的确认口令，必须是「确认提交」"},
                            "operator": {"type": "string", "description": "操作人，默认 demo_user"},
                        },
                        "required": ["action_id", "confirmation"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "rollback_po",
                    "description": "回滚一张已写入的采购 PO，状态标记为 ROLLED_BACK，审计记录仍保留。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action_id": {"type": "string", "description": "要回滚的 action_id"},
                            "reason": {"type": "string", "description": "回滚原因"},
                            "operator": {"type": "string", "description": "操作人，默认 demo_user"},
                        },
                        "required": ["action_id", "reason"],
                    },
                },
            },
        ]

    # ------------------------------------------------------------------ #
    # 工具实现（返回 JSON 字符串，供模型继续编排）
    # ------------------------------------------------------------------ #
    def call(self, name: str, arguments: dict) -> str:
        handler = {
            "search_knowledge": self._search_knowledge,
            "query_materials": self._query_materials,
            "create_purchase_order": self._create_purchase_order,
            "confirm_commit": self._confirm_commit,
            "rollback_po": self._rollback_po,
        }.get(name)
        if handler is None:
            return json.dumps({"ok": False, "error": f"未知工具：{name}"}, ensure_ascii=False)
        try:
            return handler(arguments)
        except Exception as exc:  # 工具内部异常也转成可读 JSON，不让循环崩溃
            return json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)

    def _search_knowledge(self, args: dict) -> str:
        query = str(args.get("query", ""))
        results = self.knowledge.search(query, top_k=3)
        return json.dumps(
            {"ok": True, "count": len(results), "rules": results},
            ensure_ascii=False,
        )

    def _query_materials(self, args: dict) -> str:
        codes = args.get("material_codes") or []
        found, missing = [], []
        for code in codes:
            ref = self.repository.material(str(code))
            if ref:
                found.append(
                    {
                        "material_code": ref["material_code"],
                        "material_name": ref["material_name"],
                        "supplier": f"{ref['supplier_code']} {ref['supplier_name']}",
                        "unit_price": ref["unit_price"],
                        "packaging_fee": ref["packaging_fee"],
                        "currency": ref["currency"],
                    }
                )
            else:
                missing.append(str(code))
        return json.dumps(
            {"ok": True, "found": found, "missing": missing},
            ensure_ascii=False,
        )

    def _create_purchase_order(self, args: dict) -> str:
        filename = str(args.get("filename", ""))
        source_path = (self.samples_dir / Path(filename).name).resolve()
        if source_path.parent != self.samples_dir.resolve() or not source_path.exists():
            return json.dumps({"ok": False, "error": f"文件不存在：{filename}，可用示例见 /samples 接口"}, ensure_ascii=False)

        content = source_path.read_bytes()
        rows = parse_bom(source_path.name, content)
        issues: list[ValidationIssue] = []
        if not rows:
            issues.append(ValidationIssue(level="blocking", field="BOM", message="没有解析到有效物料行"))

        items: list[dict] = []
        suppliers: set[str] = set()
        currencies: set[str] = set()
        for index, row in enumerate(rows, 1):
            code = row["material_code"]
            if not code:
                issues.append(ValidationIssue(level="blocking", field=f"第{index}行物料编码", message="物料编码不能为空"))
                continue
            try:
                quantity = float(row["quantity"])
                if quantity <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                issues.append(ValidationIssue(level="blocking", field=f"{code}.数量", message="数量必须是大于 0 的数字"))
                continue
            ref = self.repository.material(code)
            if not ref:
                issues.append(ValidationIssue(level="blocking", field=code, message="模拟 ERP 物料档案中不存在，需人工建档或修正编码"))
                continue
            if row["material_name"] and row["material_name"] != ref["material_name"]:
                issues.append(ValidationIssue(level="warning", field=code, message=f"BOM 名称“{row['material_name']}”与档案“{ref['material_name']}”不一致，以档案为准"))
            suppliers.add(ref["supplier_code"])
            currencies.add(ref["currency"])
            unit_price = float(ref["unit_price"])
            packaging_fee = float(ref["packaging_fee"])
            items.append(
                {
                    "line_no": index,
                    "material_code": code,
                    "material_name": ref["material_name"],
                    "quantity": quantity,
                    "unit": row["unit"] or "件",
                    "unit_price": unit_price,
                    "packaging_fee": packaging_fee,
                    "line_amount": round(quantity * (unit_price + packaging_fee), 2),
                    "data_sources": ["上传的 BOM", "模拟 ERP 物料档案", "模拟价格/包装费表"],
                }
            )

        if len(suppliers) > 1:
            issues.append(ValidationIssue(level="blocking", field="供应商", message="物料属于多个供应商，应拆分采购 PO"))
        if len(currencies) > 1:
            issues.append(ValidationIssue(level="blocking", field="币种", message="同一采购 PO 出现多个币种"))
        ready = not any(issue.level == "blocking" for issue in issues)
        supplier = self.repository.material(items[0]["material_code"]) if items else None
        draft = {
            "document_type": "采购PO",
            "contract_no": "CT-DEMO-2026-0818",
            "supplier_code": supplier["supplier_code"] if supplier else None,
            "supplier_name": supplier["supplier_name"] if supplier else None,
            "currency": next(iter(currencies), None),
            "payment_terms": "月结30天（演示规则）",
            "source_file": Path(filename).name,
            "items": items,
            "total_amount": round(sum(item["line_amount"] for item in items), 2),
        }

        payload = {"ready": ready, "draft": draft, "issues": [issue.model_dump() for issue in issues]}
        action_id = self.repository.create_pending(payload)
        return json.dumps(
            {
                "ok": True,
                "action_id": action_id,
                "ready": ready,
                "total_amount": draft["total_amount"],
                "supplier": draft["supplier_name"],
                "items_count": len(items),
                "issues": [issue.model_dump() for issue in issues],
            },
            ensure_ascii=False,
        )

    def _confirm_commit(self, args: dict) -> str:
        action_id = str(args.get("action_id", ""))
        confirmation = str(args.get("confirmation", ""))
        operator = str(args.get("operator", "demo_user"))
        try:
            result = self.repository.confirm(action_id, confirmation, operator)
            return json.dumps({"ok": True, **result}, ensure_ascii=False)
        except (ValueError, KeyError) as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    def _rollback_po(self, args: dict) -> str:
        action_id = str(args.get("action_id", ""))
        reason = str(args.get("reason", ""))
        operator = str(args.get("operator", "demo_user"))
        try:
            result = self.repository.rollback(action_id, reason, operator)
            return json.dumps({"ok": True, **result}, ensure_ascii=False)
        except KeyError as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
