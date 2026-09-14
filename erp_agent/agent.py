from __future__ import annotations

import base64
import json
import logging
import re
import time
from pathlib import Path

from .adapters import ERPAdapter
from .knowledge import KnowledgeBase
from .llm import AgentLoop, IntentClassifier
from .models import Citation, PrepareResponse, ToolStep, ValidationIssue
from .observability import METRICS, bind_context, log_event
from .parser import parse_bom
from .security import AccessController, Actor
from .tools import ToolRegistry


class PurchasePOAgent:
    """围绕“BOM → 采购 PO”的可解释、安全工作流 Agent。

    提供两种入口：
    - chat()：多轮对话，模型通过工具调用循环自主编排（agent 感来源）；
    - prepare()：保留的确定性六步流水线（离线也可用，向后兼容）。
    """

    def __init__(
        self,
        repository: ERPAdapter,
        knowledge: KnowledgeBase,
        samples_dir: Path,
        intent_classifier: IntentClassifier | None = None,
        agent_loop: AgentLoop | None = None,
        access_controller: AccessController | None = None,
    ):
        self.repository = repository
        self.knowledge = knowledge
        self.samples_dir = samples_dir
        self.intent_classifier = intent_classifier or IntentClassifier()
        self.access = access_controller or AccessController.from_env()
        self.tools = ToolRegistry(repository, knowledge, samples_dir, access_controller=self.access)
        self.loop = agent_loop or AgentLoop()
        self.sessions: dict[str, list[dict]] = {}
        self.offline_actions: dict[str, str] = {}

    @staticmethod
    def _offline_reply(tool: str, payload: dict) -> str:
        if payload.get("ok") is False:
            return str(payload.get("error") or payload.get("message") or "确定性流程执行失败。")
        if tool == "create_purchase_order":
            action_id = payload.get("action_id", "")
            if payload.get("ready"):
                return (
                    f"已用确定性流程生成采购 PO 草稿，总金额 ¥{payload.get('total_amount', 0):g}，"
                    f"action_id={action_id}。当前未启用模型；确认无误后请完整输入「确认提交」。"
                )
            blocking = sum(1 for issue in payload.get("issues", []) if issue.get("level") == "blocking")
            return f"草稿存在 {blocking} 个阻断问题，已禁止提交。action_id={action_id}。"
        if tool == "confirm_commit":
            if payload.get("ok"):
                return f"已写入模拟 ERP，采购单号 {payload.get('po_number', payload.get('po_no', ''))}。"
            return str(payload.get("error") or "确认提交失败。")
        if tool == "detect_material_errors":
            return str(payload.get("summary_text") or payload.get("message") or "物料错误检测已完成。")
        if tool == "query_materials":
            return json.dumps(payload, ensure_ascii=False)
        return "当前未启用模型；请使用生成采购草稿、查询物料或检测 BOM 错误等明确指令。"

    def _filename_in_text(self, text: str) -> str | None:
        """只从受控目录匹配真实文件名，避免自然语言前缀被当成路径。"""
        allowed_suffixes = {".xlsx", ".xlsm", ".csv"}
        filenames: set[str] = set()
        for base in (self.tools.uploads_dir, self.tools.samples_dir):
            if base.exists():
                filenames.update(
                    path.name for path in base.iterdir() if path.is_file() and path.suffix.lower() in allowed_suffixes
                )
        lowered = text.lower()
        return next((name for name in sorted(filenames, key=len, reverse=True) if name.lower() in lowered), None)

    def _trusted_action_id(self, session_id: str | None) -> str | None:
        """从服务端会话中的真实工具结果取最近 action_id，不信任用户或模型文本。"""
        for item in reversed(self.sessions.get(session_id or "", [])):
            if item.get("role") != "tool":
                continue
            try:
                payload = json.loads(item.get("content") or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            action_id = payload.get("action_id") if isinstance(payload, dict) else None
            if isinstance(action_id, str) and action_id:
                return action_id
        return None

    def _trusted_draft(self, session_id: str | None) -> dict | None:
        """从服务端保存的真实工具结果取最近采购草稿，不根据模型回答反推金额。"""
        for item in reversed(self.sessions.get(session_id or "", [])):
            if item.get("role") != "tool":
                continue
            try:
                payload = json.loads(item.get("content") or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            draft = payload.get("draft") if isinstance(payload, dict) else None
            if isinstance(draft, dict) and isinstance(draft.get("items"), list):
                return draft
        return None

    @staticmethod
    def _draft_amount_reply(draft: dict) -> str:
        """把确定性计算结果格式化成适合飞书卡片的金额明细。"""
        currency = str(draft.get("currency") or "CNY")
        lines = [
            "**采购 PO 金额明细**",
            f"供应商：{draft.get('supplier_name') or '-'}（{draft.get('supplier_code') or '-'}）",
            "",
        ]
        for item in draft.get("items", []):
            quantity = float(item.get("quantity", 0))
            unit_price = float(item.get("unit_price", 0))
            packaging_fee = float(item.get("packaging_fee", 0))
            line_amount = float(item.get("line_amount", 0))
            lines.append(
                f"- {item.get('material_code', '-')} {item.get('material_name', '')}："
                f"{quantity:g}{item.get('unit', '')} ×（单价 ¥{unit_price:g} + 包装费 ¥{packaging_fee:g}）"
                f"= **¥{line_amount:g}**"
            )
        lines.extend(
            [
                "",
                f"币种：{currency}",
                f"**合计：¥{float(draft.get('total_amount', 0)):g}**",
                "",
                "以上仍是草稿，确认无误请完整输入「确认提交」。",
            ]
        )
        return "\n".join(lines)

    def _chat_amount_detail(self, messages: list[dict], session_id: str | None) -> tuple[str, list[dict], list[dict]]:
        history = self.sessions.get(session_id or "", [])
        full = history + list(messages)
        draft = self._trusted_draft(session_id)
        reply = self._draft_amount_reply(draft) if draft else "当前会话没有可查看的采购草稿，请先生成采购 PO 草稿。"
        full.append({"role": "assistant", "content": reply})
        return reply, [], full

    def _chat_confirmation(self, messages: list[dict], session_id: str | None, actor: Actor | None) -> tuple[str, list[dict], list[dict]]:
        """精确确认走确定性工具，避免模型在线时因编排波动反复询问。"""
        history = self.sessions.get(session_id or "", [])
        full = history + list(messages)
        action_id = self._trusted_action_id(session_id)
        if not action_id:
            reply = "当前会话没有可确认的真实草稿，请先生成采购 PO 草稿。"
            full.append({"role": "assistant", "content": reply})
            return reply, [], full
        arguments = {"action_id": action_id, "confirmation": "确认提交"}
        raw = self.tools.call("confirm_commit", arguments) if actor is None else self.tools.call("confirm_commit", arguments, actor=actor)
        payload = json.loads(raw)
        reply = self._offline_reply("confirm_commit", payload)
        trace = [{"step": 1, "tool": "confirm_commit", "arguments": arguments, "result": raw}]
        full.extend([{"role": "tool", "name": "confirm_commit", "content": raw}, {"role": "assistant", "content": reply}])
        return reply, trace, full

    def _chat_offline(self, messages: list[dict], session_id: str | None, actor: Actor | None) -> tuple[str, list[dict], list[dict]]:
        """无模型时提供可演示的确定性聊天降级，写入安全边界保持不变。"""
        history = self.sessions.get(session_id, []) if session_id else []
        full = history + list(messages)
        text = next((str(item.get("content", "")) for item in reversed(messages) if item.get("role") == "user"), "").strip()
        tool = ""
        arguments: dict = {}
        if text == "确认提交":
            action_id = self.offline_actions.get(session_id or "")
            if not action_id:
                reply = "当前会话没有可确认的真实草稿，请先生成采购 PO 草稿。"
                full.append({"role": "assistant", "content": reply})
                return reply, [], full
            tool, arguments = "confirm_commit", {"action_id": action_id, "confirmation": text}
        else:
            filename = self._filename_in_text(text)
            material_codes = re.findall(r"MAT-[A-Z0-9-]+", text.upper())
            if "检测" in text and filename:
                tool, arguments = "detect_material_errors", {"filename": filename, "push": False}
            elif ("查" in text or "价格" in text) and material_codes:
                tool, arguments = "query_materials", {"material_codes": material_codes}
            elif filename and any(word in text for word in ("采购", "草稿", "生成", "创建")):
                tool, arguments = "create_purchase_order", {"filename": filename}
            else:
                reply = "当前未启用模型；可输入“根据正常示例_BOM.xlsx生成采购 PO 草稿”进行确定性演示。"
                full.append({"role": "assistant", "content": reply})
                return reply, [], full

        raw = self.tools.call(tool, arguments) if actor is None else self.tools.call(tool, arguments, actor=actor)
        payload = json.loads(raw)
        if tool == "create_purchase_order" and isinstance(payload.get("action_id"), str) and session_id:
            self.offline_actions[session_id] = payload["action_id"]
        reply = self._offline_reply(tool, payload)
        trace = [{"step": 1, "tool": tool, "arguments": arguments, "result": raw}]
        full.extend([{"role": "tool", "name": tool, "content": raw}, {"role": "assistant", "content": reply}])
        return reply, trace, full

    def chat(self, messages: list[dict], session_id: str | None = None, actor: Actor | None = None) -> dict:
        """多轮对话入口：模型自主调用工具完成采购业务。

        messages 为 OpenAI 格式对话历史（含 role 与 content）。
        传入 session_id 时，会接续该会话的完整上下文（模型能记住之前的 action_id）。
        返回 {"reply", "tool_trace", "model", "llm_enabled"}。
        """
        started = time.perf_counter()
        with bind_context(session_id=session_id, actor_id=actor.user_id if actor else None):
            log_event(logging.getLogger("erp_agent.agent"), "agent.chat.started", message_count=len(messages))
            try:
                if session_id and session_id in self.sessions:
                    full = self.sessions[session_id] + list(messages)
                else:
                    full = list(messages)
                latest_user = next(
                    (str(item.get("content", "")).strip() for item in reversed(messages) if item.get("role") == "user"),
                    "",
                )
                if latest_user == "确认提交":
                    reply, trace, full = self._chat_confirmation(messages, session_id, actor)
                elif "金额" in latest_user and any(word in latest_user for word in ("具体", "明细", "详细", "构成")):
                    reply, trace, full = self._chat_amount_detail(messages, session_id)
                elif self.loop.enabled:
                    reply, trace, full = self.loop.run(full, self.tools, actor=actor)
                else:
                    reply, trace, full = self._chat_offline(messages, session_id, actor)
                if session_id:
                    self.sessions[session_id] = full
                desc_map = {s["function"]["name"]: s["function"]["description"] for s in self.tools.schemas}
                for item in trace:
                    item["purpose"] = desc_map.get(item["tool"], "")
                result = {"reply": reply, "tool_trace": trace, "model": self.loop.model, "llm_enabled": self.loop.enabled}
                success = True
                return result
            except Exception:
                success = False
                raise
            finally:
                duration_ms = (time.perf_counter() - started) * 1000
                METRICS.record("agent.chat", success, duration_ms)
                log_event(logging.getLogger("erp_agent.agent"), "agent.chat.completed", success=success, duration_ms=round(duration_ms, 3))

    def prepare(self, task: str, filename: str, content_base64: str | None = None, actor: Actor | None = None) -> PrepareResponse:
        self.access.authorize(actor, "prepare")
        trace: list[ToolStep] = []
        issues: list[ValidationIssue] = []

        # 第 1 步：意图识别（可选 LLM，失败回退确定性规则）。
        # 安全边界：LLM 只产出「意图」，不参与金额计算、业务校验或写入决策。
        intent = self.intent_classifier.classify(task)
        intent_source = f"{intent.model}（{intent.source}）" if intent.model else "确定性规则（offline）"
        trace.append(
            ToolStep(
                step=1,
                tool="intent_recognition",
                purpose="用模型理解业务意图（可选，失败自动回退）",
                result=f"意图={intent.action} · {intent_source} · {intent.reasoning}",
            )
        )

        citations_raw = self.knowledge.search(f"{task} 采购 PO BOM 单价 包装费 写入确认", top_k=3)
        trace.append(ToolStep(step=2, tool="knowledge_search", purpose="查询采购 PO 字段与安全规则", result=f"命中 {len(citations_raw)} 条规则"))

        if content_base64:
            content = base64.b64decode(content_base64)
            source = filename
        else:
            # 复用工具层的白名单解析（samples/ 与 uploads/），否则用户上传的 BOM 走不了 prepare
            source_path = self.tools.resolve_bom_file(filename)
            content = source_path.read_bytes()
            source = source_path.name
        rows = parse_bom(source, content)
        trace.append(ToolStep(step=3, tool="parse_bom", purpose="解析 BOM 物料与需求数量", result=f"解析到 {len(rows)} 行物料"))
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
        trace.append(ToolStep(step=4, tool="query_material_master", purpose="查询物料、供应商、价格和包装费", result=f"匹配 {len(items)}/{len(rows)} 行"))

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
        trace.append(ToolStep(step=5, tool="validate_purchase_po", purpose="执行必填、档案、供应商和币种校验", result="通过，可等待确认" if ready else "存在阻断问题，禁止写入"))

        payload = {"ready": ready, "draft": draft, "issues": [issue.model_dump() for issue in issues]}
        action_id = self.repository.create_pending(payload, actor.user_id if actor else "demo_operator")
        trace.append(ToolStep(step=6, tool="create_change_preview", purpose="保存变更预览而不写入正式业务表", result=f"生成待确认操作 {action_id}"))
        return PrepareResponse(
            action_id=action_id,
            status="ready_for_confirmation" if ready else "blocked",
            intent=f"{intent.action}：{intent.reasoning}",
            message="草稿已生成；输入“确认提交”后才会写入模拟 ERP。" if ready else "草稿存在阻断问题，已禁止提交。",
            draft=draft,
            issues=issues,
            citations=[Citation(**item) for item in citations_raw],
            tool_trace=trace,
        )
