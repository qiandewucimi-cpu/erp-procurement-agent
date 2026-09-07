from __future__ import annotations

import base64
from pathlib import Path

from .knowledge import KnowledgeBase
from .models import Citation, PrepareResponse, ToolStep, ValidationIssue
from .parser import parse_bom
from .repository import ERPRepository


class PurchasePOAgent:
    """围绕“BOM → 采购 PO”的可解释、安全工作流 Agent。"""

    def __init__(self, repository: ERPRepository, knowledge: KnowledgeBase, samples_dir: Path):
        self.repository = repository
        self.knowledge = knowledge
        self.samples_dir = samples_dir

    def prepare(self, task: str, filename: str, content_base64: str | None = None) -> PrepareResponse:
        trace: list[ToolStep] = []
        issues: list[ValidationIssue] = []

        citations_raw = self.knowledge.search(f"{task} 采购 PO BOM 单价 包装费 写入确认", top_k=3)
        trace.append(ToolStep(step=1, tool="knowledge_search", purpose="查询采购 PO 字段与安全规则", result=f"命中 {len(citations_raw)} 条规则"))

        if content_base64:
            content = base64.b64decode(content_base64)
            source = filename
        else:
            source_path = (self.samples_dir / Path(filename).name).resolve()
            if source_path.parent != self.samples_dir.resolve() or not source_path.exists():
                raise FileNotFoundError("示例文件不存在")
            content = source_path.read_bytes()
            source = source_path.name
        rows = parse_bom(source, content)
        trace.append(ToolStep(step=2, tool="parse_bom", purpose="解析 BOM 物料与需求数量", result=f"解析到 {len(rows)} 行物料"))
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
        trace.append(ToolStep(step=3, tool="query_material_master", purpose="查询物料、供应商、价格和包装费", result=f"匹配 {len(items)}/{len(rows)} 行"))

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
        trace.append(ToolStep(step=4, tool="validate_purchase_po", purpose="执行必填、档案、供应商和币种校验", result="通过，可等待确认" if ready else "存在阻断问题，禁止写入"))

        payload = {"ready": ready, "draft": draft, "issues": [issue.model_dump() for issue in issues]}
        action_id = self.repository.create_pending(payload)
        trace.append(ToolStep(step=5, tool="create_change_preview", purpose="保存变更预览而不写入正式业务表", result=f"生成待确认操作 {action_id}"))
        return PrepareResponse(
            action_id=action_id,
            status="ready_for_confirmation" if ready else "blocked",
            intent="根据 BOM 生成并校验采购 PO 草稿",
            message="草稿已生成；输入“确认提交”后才会写入模拟 ERP。" if ready else "草稿存在阻断问题，已禁止提交。",
            draft=draft,
            issues=issues,
            citations=[Citation(**item) for item in citations_raw],
            tool_trace=trace,
        )

