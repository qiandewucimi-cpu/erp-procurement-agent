from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

import requests


# 白名单：LLM 只允许产出这些意图，其余一律回退默认，防止模型幻觉引入越权动作。
SUPPORTED_INTENTS = {
    "generate_purchase_po",
    "query_materials",
    "unknown",
}

DEFAULT_INTENT = "generate_purchase_po"

# 小模型往往不严格遵循英文枚举，会把意图写成中文/口语变体。
# 归一化层把这些变体映射回白名单，避免 LLM 结果被白白回退。
_ACTION_ALIASES = {
    "generate_purchase_po": {
        "generate_purchase_po", "generate po", "generate purchase po",
        "生成采购po", "生成采购单", "生成po", "创建采购po", "创建po", "生成采购", "采购po",
    },
    "query_materials": {
        "query_materials", "query material", "查询物料", "查物料", "查询价格", "查价格", "查询", "只查",
    },
    "unknown": {"unknown", "未知", "无法判断"},
}

_ACTION_HINTS = (
    ("generate_purchase_po", ("生成", "创建", "采购", "create", "purchase")),
    ("query_materials", ("查询", "查价", "查物料", "query")),
)


def _normalize_action(raw: str) -> str | None:
    """把模型输出的意图（中英文、口语变体）归一化到白名单；无法识别返回 None。"""
    value = (raw or "").strip().lower()
    for canonical, aliases in _ACTION_ALIASES.items():
        if value in aliases:
            return canonical
    # 模糊兜底：按关键词判断；若同时命中多类，保守返回 None 交给确定性回退。
    hits = [canonical for canonical, hints in _ACTION_HINTS if any(h in value for h in hints)]
    action = hits[0] if len(hits) == 1 else None
    return action if action in SUPPORTED_INTENTS else None


@dataclass(frozen=True)
class Intent:
    action: str
    source: str  # "llm" | "fallback"
    model: str | None
    reasoning: str


def _default_prompt(task: str) -> str:
    return (
        "你是外贸 ERP 采购助手的意图识别模块。只输出一行 JSON，不要输出任何解释或其他内容。\n"
        "根据用户描述判断意图，action 只能取以下三个英文值之一：\n"
        '- "generate_purchase_po"：用户要生成采购 PO 草稿；\n'
        '- "query_materials"：用户只想查询物料、价格或包装费信息；\n'
        '- "unknown"：无法判断。\n'
        "示例：\n"
        '用户说"帮我生成采购PO" → {"action":"generate_purchase_po","reason":"生成采购单"}\n'
        '用户说"查一下这个物料多少钱" → {"action":"query_materials","reason":"查询价格"}\n\n'
        f"现在判断：{task}\n"
        '输出格式严格为：{"action":"<上述三个值之一>","reason":"<一句话原因>"}'
    )


def _extract_json(text: str) -> dict | None:
    """从可能被 markdown 代码块或前后缀包裹的输出里提取 JSON。"""
    if not text:
        return None
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            text = match.group(0)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


class IntentClassifier:
    """可插拔的意图识别层：优先调用 LLM，失败或不可用时回退到确定性规则。

    安全边界：这里只产出「意图」，不产出金额、校验结论或写入指令；
    金额计算、业务校验、写入权限全部留在确定性代码里。
    因此即使模型不可用、输出非法或被幻觉干扰，也不会产生错误写入。
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float = 8.0,
    ):
        # 优先用显式参数，其次读环境变量；云端/本地通过 base_url + model 区分。
        self.base_url = (base_url if base_url is not None else os.getenv("LLM_BASE_URL", "")).rstrip("/")
        self.model = model or os.getenv("LLM_MODEL", "qwen2:1.5b")
        self.api_key = api_key if api_key is not None else os.getenv("LLM_API_KEY", "")
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

    def classify(self, task: str) -> Intent:
        if self.enabled:
            try:
                return self._classify_llm(task)
            except Exception:
                # 网络异常、超时、非 2xx 等任何情况都静默回退，保证流程离线稳定。
                return self._classify_fallback(task)
        return self._classify_fallback(task)

    def _chat_completions(self, task: str) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是 ERP 采购助手的意图识别模块，只输出 JSON。"},
                {"role": "user", "content": _default_prompt(task)},
            ],
            "temperature": 0,
            "stream": False,
        }
        response = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    def _classify_llm(self, task: str) -> Intent:
        content = self._chat_completions(task)
        parsed = _extract_json(content)
        if not parsed:
            return self._classify_fallback(task)  # 输出非法，回退
        action = _normalize_action(str(parsed.get("action", "")))
        if action is None or action == "unknown":
            # 模型无法判断或输出白名单外 → 交给确定性规则兜底。
            return self._classify_fallback(task)
        reason = str(parsed.get("reason", "")).strip()
        return Intent(action=action, source="llm", model=self.model, reasoning=reason)

    @staticmethod
    def _classify_fallback(task: str) -> Intent:
        text = (task or "").lower()
        if "查询" in text or "只查" in text or "query" in text:
            action, reason = "query_materials", "描述中包含查询意图"
        else:
            action, reason = DEFAULT_INTENT, "未识别到特定意图，默认按生成采购 PO 处理"
        return Intent(action=action, source="fallback", model=None, reasoning=reason)
