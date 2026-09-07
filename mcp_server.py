from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from erp_agent.knowledge import KnowledgeBase
from erp_agent.repository import ERPRepository
from erp_agent.tools import ToolRegistry


BASE_DIR = Path(__file__).resolve().parent
repository = ERPRepository(BASE_DIR / "data" / "demo_erp.db")
tools = ToolRegistry(repository, KnowledgeBase(BASE_DIR / "knowledge"), BASE_DIR / "samples")

mcp = FastMCP(
    "erp-procurement-agent",
    instructions="外贸 ERP 采购操作助手，提供物料查询、采购单生成、确认写入与回滚等工具。安全边界：金额计算与写入口令由确定性代码控制。",
)


@mcp.tool()
def search_knowledge(query: str) -> str:
    """检索采购 PO 业务规则库，了解字段含义、校验规则与安全要求。"""
    return tools.call("search_knowledge", {"query": query})


@mcp.tool()
def query_materials(material_codes: list[str]) -> str:
    """查询物料档案、供应商、单价与包装费（只读，不生成单据）。"""
    return tools.call("query_materials", {"material_codes": material_codes})


@mcp.tool()
def create_purchase_order(filename: str) -> str:
    """根据 BOM 文件生成采购 PO 草稿。只生成待确认预览，不会真正写入。"""
    return tools.call("create_purchase_order", {"filename": filename})


@mcp.tool()
def confirm_commit(action_id: str, confirmation: str, operator: str = "demo_user") -> str:
    """把采购 PO 草稿真正写入模拟 ERP。仅当 confirmation 为「确认提交」时才成功。"""
    return tools.call("confirm_commit", {"action_id": action_id, "confirmation": confirmation, "operator": operator})


@mcp.tool()
def rollback_po(action_id: str, reason: str, operator: str = "demo_user") -> str:
    """回滚一张已写入的采购 PO，状态标记为 ROLLED_BACK，审计记录仍保留。"""
    return tools.call("rollback_po", {"action_id": action_id, "reason": reason, "operator": operator})


if __name__ == "__main__":
    mcp.run()
