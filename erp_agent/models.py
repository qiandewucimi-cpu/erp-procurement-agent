from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class PrepareRequest(BaseModel):
    task: str = Field(min_length=3, description="用户用自然语言描述的业务任务")
    filename: str = "正常示例_BOM.xlsx"
    content_base64: str | None = None


class ChatRequest(BaseModel):
    messages: list[dict[str, Any]] = Field(description="OpenAI 格式对话历史（含 role 与 content）")
    session_id: str | None = Field(default=None, description="会话 ID，传入后接续该会话上下文")


class ConfirmRequest(BaseModel):
    action_id: str
    confirmation: str
    operator: str = "demo_user"


class RollbackRequest(BaseModel):
    action_id: str
    reason: str = Field(min_length=2)
    operator: str = "demo_user"


class ValidationIssue(BaseModel):
    level: Literal["warning", "blocking"]
    field: str
    message: str


class ToolStep(BaseModel):
    step: int
    tool: str
    purpose: str
    result: str


class Citation(BaseModel):
    source: str
    section: str
    excerpt: str
    score: float


class PrepareResponse(BaseModel):
    action_id: str
    status: Literal["ready_for_confirmation", "blocked"]
    intent: str
    message: str
    draft: dict[str, Any]
    issues: list[ValidationIssue]
    citations: list[Citation]
    tool_trace: list[ToolStep]

