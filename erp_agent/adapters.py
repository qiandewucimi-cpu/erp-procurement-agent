from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable
from urllib.parse import quote

import requests

from .repository import ERPRepository


def _load_env_file(path: Path) -> None:
    """让 API、MCP、飞书三种入口都能读取同一份 Adapter 配置。"""

    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))


class ERPAdapterError(RuntimeError):
    """真实 ERP 适配器错误的稳定基类，避免上层依赖厂商报错文案。"""


class ERPAuthenticationError(ERPAdapterError):
    pass


class ERPNotFoundError(ERPAdapterError):
    pass


class ERPConflictError(ERPAdapterError):
    pass


class ERPUnavailableError(ERPAdapterError):
    pass


@runtime_checkable
class ERPAdapter(Protocol):
    """Agent 所需的最小 ERP 端口；SQLite 与 HTTP 实现均遵守该协议。"""

    def material(self, code: str) -> dict | None: ...
    def materials(self) -> list[dict]: ...
    def import_materials(self, rows: list[dict]) -> dict: ...
    def create_pending(self, payload: dict, operator: str = "demo_user") -> str: ...
    def approve(self, action_id: str, approver: str) -> dict: ...
    def confirm(self, action_id: str, confirmation: str, operator: str) -> dict: ...
    def rollback(self, action_id: str, reason: str, operator: str) -> dict: ...
    def orders(self) -> list[dict]: ...
    def pending_actions(self) -> list[dict]: ...
    def audits(self) -> list[dict]: ...
    def save_error_report(self, summary: dict, errors: list[dict], operator: str = "demo_user") -> str: ...
    def error_reports(self) -> list[dict]: ...


class HTTPERPAdapter:
    """客户 ERP HTTP API 适配器：协议翻译、鉴权、重试与稳定错误映射。"""

    RETRYABLE_STATUS = {429, 500, 502, 503, 504}

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        timeout: float = 5.0,
        max_retries: int = 2,
        backoff_seconds: float = 0.2,
        session: Any | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        if not base_url.strip():
            raise ValueError("ERP_API_BASE_URL 不能为空")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self.backoff_seconds = max(0.0, backoff_seconds)
        self.session = session or requests.Session()
        self.sleeper = sleeper

    @staticmethod
    def _idempotency_key(prefix: str, value: Any) -> str:
        canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
        return f"erp-agent:{prefix}:{digest}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict | list | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.request(
                    method,
                    f"{self.base_url}{path}",
                    json=payload,
                    headers=headers,
                    timeout=self.timeout,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    self.sleeper(self.backoff_seconds * (2**attempt))
                    continue
                raise ERPUnavailableError(f"ERP 服务不可用：{type(exc).__name__}") from exc

            if response.status_code in self.RETRYABLE_STATUS and attempt < self.max_retries:
                self.sleeper(self.backoff_seconds * (2**attempt))
                continue
            if response.status_code in (401, 403):
                raise ERPAuthenticationError("ERP 鉴权失败")
            if response.status_code == 404:
                raise ERPNotFoundError("ERP 资源不存在")
            if response.status_code == 409:
                raise ERPConflictError("ERP 状态冲突或幂等键冲突")
            if response.status_code >= 400:
                raise ERPAdapterError(f"ERP 请求失败：HTTP {response.status_code}")
            try:
                return response.json()
            except ValueError as exc:
                raise ERPAdapterError("ERP 返回了非 JSON 响应") from exc

        raise ERPUnavailableError(f"ERP 服务不可用：{last_error}")

    def material(self, code: str) -> dict | None:
        try:
            return self._request("GET", f"/materials/{quote(code, safe='')}")
        except ERPNotFoundError:
            return None

    @staticmethod
    def _items(result: Any) -> list[dict]:
        return result.get("items", []) if isinstance(result, dict) else result

    def materials(self) -> list[dict]:
        return self._items(self._request("GET", "/materials"))

    def import_materials(self, rows: list[dict]) -> dict:
        return self._request(
            "POST", "/materials/import", payload={"items": rows},
            idempotency_key=self._idempotency_key("materials", rows),
        )

    def create_pending(self, payload: dict, operator: str = "demo_user") -> str:
        body = {"payload": payload, "operator": operator}
        result = self._request(
            "POST", "/actions/preview", payload=body,
            idempotency_key=self._idempotency_key("preview", body),
        )
        return str(result["action_id"])

    def confirm(self, action_id: str, confirmation: str, operator: str) -> dict:
        return self._request(
            "POST", f"/actions/{quote(action_id, safe='')}/confirm",
            payload={"confirmation": confirmation, "operator": operator},
            idempotency_key=f"erp-agent:confirm:{action_id}",
        )

    def approve(self, action_id: str, approver: str) -> dict:
        return self._request(
            "POST", f"/actions/{quote(action_id, safe='')}/approve",
            payload={"approver": approver},
            idempotency_key=f"erp-agent:approve:{action_id}",
        )

    def rollback(self, action_id: str, reason: str, operator: str) -> dict:
        return self._request(
            "POST", f"/actions/{quote(action_id, safe='')}/rollback",
            payload={"reason": reason, "operator": operator},
            idempotency_key=f"erp-agent:rollback:{action_id}",
        )

    def orders(self) -> list[dict]:
        return self._items(self._request("GET", "/orders"))

    def pending_actions(self) -> list[dict]:
        return self._items(self._request("GET", "/approvals"))

    def audits(self) -> list[dict]:
        return self._items(self._request("GET", "/audit"))

    def save_error_report(self, summary: dict, errors: list[dict], operator: str = "demo_user") -> str:
        body = {"summary": summary, "errors": errors, "operator": operator}
        result = self._request(
            "POST", "/error-reports", payload=body,
            idempotency_key=self._idempotency_key("error-report", body),
        )
        return str(result["report_id"])

    def error_reports(self) -> list[dict]:
        return self._items(self._request("GET", "/error-reports"))


def build_erp_adapter(base_dir: Path) -> ERPAdapter:
    """按环境变量选择 Demo SQLite 或客户 HTTP ERP，默认保持离线可运行。"""

    _load_env_file(base_dir / ".env")
    backend = os.getenv("ERP_BACKEND", "sqlite").strip().lower()
    if backend == "sqlite":
        return ERPRepository(base_dir / "data" / "demo_erp.db")
    if backend == "http":
        return HTTPERPAdapter(
            base_url=os.getenv("ERP_API_BASE_URL", ""),
            token=os.getenv("ERP_API_TOKEN") or None,
            timeout=float(os.getenv("ERP_API_TIMEOUT", "5")),
            max_retries=int(os.getenv("ERP_API_MAX_RETRIES", "2")),
        )
    raise ValueError(f"不支持的 ERP_BACKEND：{backend}")
