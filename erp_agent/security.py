from __future__ import annotations

import json
import os
from dataclasses import dataclass


class AuthenticationRequired(PermissionError):
    pass


class PermissionDenied(PermissionError):
    pass


@dataclass(frozen=True)
class Actor:
    user_id: str
    role: str


ROLE_PERMISSIONS = {
    "viewer": {"search_knowledge", "query_materials", "detect_material_errors", "read"},
    "operator": {
        "search_knowledge", "query_materials", "detect_material_errors", "read",
        "create_purchase_order", "import_material_master", "prepare",
    },
    "approver": {
        "search_knowledge", "query_materials", "detect_material_errors", "read",
        "approve_action", "confirm_commit", "rollback_po", "approve", "confirm", "rollback",
    },
}


class AccessController:
    """可选的 API-Key 身份绑定；关闭时保持本地离线 Demo 向后兼容。"""

    def __init__(self, enabled: bool = False, identities: dict[str, Actor] | None = None):
        self.enabled = enabled
        self.identities = identities or {}

    @classmethod
    def from_env(cls) -> "AccessController":
        enabled = os.getenv("ERP_AUTH_ENABLED", "false").lower() in {"1", "true", "yes"}
        raw = os.getenv("ERP_AUTH_IDENTITIES_JSON", "{}").strip() or "{}"
        try:
            configured = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("ERP_AUTH_IDENTITIES_JSON 必须是合法 JSON") from exc
        identities = {}
        for token, item in configured.items():
            user_id = str(item.get("user_id", "")).strip()
            role = str(item.get("role", "")).strip().lower()
            if not user_id or role not in ROLE_PERMISSIONS:
                raise ValueError("每个身份必须包含 user_id 和 viewer/operator/approver 角色")
            identities[str(token)] = Actor(user_id, role)
        return cls(enabled, identities)

    def authenticate(self, authorization: str | None) -> Actor | None:
        if not self.enabled:
            return None
        if not authorization or not authorization.startswith("Bearer "):
            raise AuthenticationRequired("缺少 Bearer 身份凭证")
        actor = self.identities.get(authorization.removeprefix("Bearer ").strip())
        if actor is None:
            raise AuthenticationRequired("身份凭证无效")
        return actor

    def actor_for_user_id(self, user_id: str) -> Actor | None:
        """给已有可信入口（如飞书 open_id）绑定配置中的同一身份。"""

        if not self.enabled:
            return None
        for actor in self.identities.values():
            if actor.user_id == user_id:
                return actor
        raise AuthenticationRequired("当前入口用户未配置角色")

    def authorize(self, actor: Actor | None, permission: str) -> None:
        if not self.enabled:
            return
        if actor is None:
            raise AuthenticationRequired("当前操作需要身份凭证")
        if permission not in ROLE_PERMISSIONS.get(actor.role, set()):
            raise PermissionDenied(f"角色 {actor.role} 无权执行 {permission}")
