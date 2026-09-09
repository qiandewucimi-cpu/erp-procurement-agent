# Streamlit UI 真实点击演示验证记录

> 验证时间：2026-09-09（Asia/Shanghai）
> 验证环境：Docker Compose 双容器（api:8000 / ui:8501），浏览器访问 `http://localhost:8501`
> 模型：智谱 glm-4-flash（容器内已配置 LLM 环境变量）

## 验证结论

UI 真实点击演示全部通过，此前唯一遗留的"未人工验证"环节已闭环：

1. **聊天框里模型真的会自主调工具**（不是固定脚本）——共验证 3 个工具的真实自主调用：
   - `detect_material_errors`：输入「检测一下 异常示例_BOM.xlsx 有哪些物料错误」，模型自主调用并返回分级报告；
   - `create_purchase_order`：输入「帮我根据 正常示例_BOM.xlsx 生成采购 PO 草稿，先给我看金额」，模型自主调用，返回总金额 ¥24164；
   - `confirm_commit`：输入「确认提交」，模型自主调用写入口令，生成单号 PO-DEMO-20260909-6E25。
2. **"订单与审计"页三张表全部渲染**：
   - 模拟 ERP 采购 PO：PO-DEMO-20260909-6E25 / COMMITTED；
   - 审计日志：5 条，含本次操作的 PREVIEW_CREATED → WRITE_CONFIRMED 全程留痕，以及历史 ERROR_REPORT_CREATED；
   - 物料错误报告（推送队列）：ERR-D24ABB3866 / PENDING_PUSH，3 行 3 错误（阻断 2 / 警告 1）。

## 演示截图

| 文件 | 内容 |
|---|---|
| `docs/ui-demo/chat-top-model-status.png` | 页面顶部：模型已启用 glm-4-flash（工具调用由模型自主编排）+ 物料错误检测对话 |
| `docs/ui-demo/chat-detect-errors-trace.png` | `detect_material_errors` 工具调用轨迹与返回 JSON（3 行 3 错误，阻断 2 / 警告 1） |
| `docs/ui-demo/chat-po-commit.png` | 生成 PO 草稿 ¥24164 + 「确认提交」写入 PO-DEMO-20260909-6E25 + `confirm_commit` 轨迹 |
| `docs/ui-demo/ui-tab-audit-tables.png` | "订单与审计"页三张表：采购 PO / 审计日志 / 物料错误报告（推送队列） |

## 操作步骤（可复现）

1. 启动：`docker compose up -d`（或 `start_demo.cmd`）；
2. 浏览器打开 `http://localhost:8501`，确认顶部绿色提示「模型已启用」；
3. 聊天框输入「检测一下 异常示例_BOM.xlsx 有哪些物料错误」→ 等待模型自主调用 `detect_material_errors`，展开"查看 Agent 工具调用轨迹"可见 JSON 报告；
4. 聊天框输入「帮我根据 正常示例_BOM.xlsx 生成采购 PO 草稿，先给我看金额」→ 模型自主调用 `create_purchase_order`，返回总金额 ¥24164；
5. 输入「确认提交」→ 模型自主调用 `confirm_commit`，返回单号 PO-DEMO-20260909-6E25；
6. 切到"订单与审计"页 → 三张表渲染，采购 PO 表出现 COMMITTED 单据，审计日志出现 WRITE_CONFIRMED。

## 对应面试脚本

本记录对应《面试演示脚本.md》0:00–2:30 的全部演示段落：问题与真实性 → 正常流程（工具调用循环）→ 多轮与安全写入 → 异常处理（物料错误检测）。截图可直接用于作品集。
