"""MCP stdio 冒烟：验证 mcp_server.py 能作为标准 MCP 服务被任意客户端调用。

用法（项目根目录）：

    python smoke_mcp.py

验证三件事：
1. 能通过 stdio 启动 MCP Server；
2. 客户端能列出全部 6 个工具；
3. 客户端能调用 detect_material_errors 并拿到分级结果。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

BASE_DIR = Path(__file__).resolve().parent
EXPECTED_TOOLS = {
    "search_knowledge",
    "query_materials",
    "create_purchase_order",
    "confirm_commit",
    "rollback_po",
    "detect_material_errors",
}


async def main() -> int:
    params = StdioServerParameters(command=sys.executable, args=[str(BASE_DIR / "mcp_server.py")])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            print(f"1) 列出工具（{len(names)} 个）：{sorted(names)}")
            missing = EXPECTED_TOOLS - names
            if missing:
                print(f"   缺少工具：{sorted(missing)}")
                return 1
            print("   6 个工具全部暴露 OK")

            result = await session.call_tool("query_materials", {"material_codes": ["MAT-FAB-001"]})
            text = result.content[0].text if result.content else ""
            print(f"2) 调用 query_materials：{text[:110]}")

            result = await session.call_tool("detect_material_errors", {"filename": "异常示例_BOM.xlsx"})
            text = result.content[0].text if result.content else ""
            print(f"3) 调用 detect_material_errors：{text[:150]}")
            if '"ok": true' not in text or "未建档" not in text:
                print("   工具调用结果异常")
                return 1
            print("   检测工具返回分级结果 OK")

    print("\nMCP stdio 冒烟通过：6 个工具可被任意 MCP 客户端调用")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        # Windows 下 stdio 子进程需要 Selector 事件循环策略
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    raise SystemExit(asyncio.run(main()))
