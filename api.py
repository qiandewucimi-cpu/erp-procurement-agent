import json
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from erp_agent.adapters import (
    ERPAdapterError,
    ERPAuthenticationError,
    ERPConflictError,
    ERPNotFoundError,
    ERPUnavailableError,
    build_erp_adapter,
)
from erp_agent.agent import PurchasePOAgent
from erp_agent.knowledge import KnowledgeBase
from erp_agent.models import (
    ChatRequest,
    ApprovalRequest,
    ConfirmRequest,
    DetectRequest,
    MaterialImportRequest,
    PrepareRequest,
    PrepareResponse,
    RollbackRequest,
)
from erp_agent.repository import ERPRepository
from erp_agent.security import AccessController, AuthenticationRequired, PermissionDenied


BASE_DIR = Path(__file__).resolve().parent
repository = build_erp_adapter(BASE_DIR)
access = AccessController.from_env()
agent = PurchasePOAgent(repository, KnowledgeBase(BASE_DIR / "knowledge"), BASE_DIR / "samples", access_controller=access)

app = FastAPI(
    title="外贸 ERP 安全操作 Agent",
    version="0.1.0",
    description="基于合成数据演示 BOM → 采购 PO、写前确认、审计与回滚。",
)


@app.exception_handler(ERPAdapterError)
async def erp_adapter_error_handler(_request: Request, exc: ERPAdapterError) -> JSONResponse:
    """把不同厂商的失败收敛为对调用方稳定的 HTTP 语义。"""

    if isinstance(exc, ERPUnavailableError):
        status_code = 503
    elif isinstance(exc, ERPNotFoundError):
        status_code = 404
    elif isinstance(exc, ERPConflictError):
        status_code = 409
    elif isinstance(exc, ERPAuthenticationError):
        status_code = 502
    else:
        status_code = 502
    return JSONResponse(status_code=status_code, content={"detail": str(exc), "type": type(exc).__name__})


def _actor(authorization: str | None):
    try:
        return access.authenticate(authorization)
    except AuthenticationRequired as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _authorize(actor, permission: str) -> None:
    try:
        access.authorize(actor, permission)
    except AuthenticationRequired as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/health")
def health() -> dict:
    """健康检查，同时回传 LLM 可用性，便于前端显示「模型是否真的在工作」。"""
    return {
        "status": "ok",
        "mode": "synthetic-demo",
        "production_connected": False,
        "llm_enabled": agent.loop.enabled,
        "llm_model": agent.loop.model,
        "auth_enabled": access.enabled,
    }


@app.get("/materials")
def materials(authorization: str | None = Header(default=None)) -> list[dict]:
    """列出模拟 ERP 的物料档案（编码、名称、供应商、单价、包装费、币种）。"""
    actor = _actor(authorization)
    _authorize(actor, "read")
    return repository.materials()


@app.post("/materials/import")
def import_materials(request: MaterialImportRequest, authorization: str | None = Header(default=None)) -> dict:
    """导入用户自己的物料档案到模拟 ERP（已存在的编码则更新价格）。

    导入后，用户自己的 BOM 才能被正确匹配，否则会全部判为「未建档」而阻断。
    """
    actor = _actor(authorization)
    _authorize(actor, "import_material_master")
    raw = agent.tools.call("import_material_master", {"filename": request.filename}, actor=actor)
    result = json.loads(raw)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "物料档案导入失败"))
    return result


@app.get("/samples")
def samples(authorization: str | None = Header(default=None)) -> list[str]:
    _authorize(_actor(authorization), "read")
    return sorted(path.name for path in (BASE_DIR / "samples").glob("*.xlsx"))


@app.post("/agent/prepare", response_model=PrepareResponse)
def prepare(request: PrepareRequest, authorization: str | None = Header(default=None)) -> PrepareResponse:
    actor = _actor(authorization)
    _authorize(actor, "prepare")
    try:
        return agent.prepare(request.task, request.filename, request.content_base64, actor)
    except ERPAdapterError:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/agent/detect")
def detect(request: DetectRequest, authorization: str | None = Header(default=None)) -> dict:
    """物料错误检测：解析 BOM → 逐行校验 → 生成分级错误报告。

    push=true 时把报告写入推送队列（error_reports 表，模拟推送给录单员），
    之后可通过 GET /error_reports 查看。
    """
    actor = _actor(authorization)
    _authorize(actor, "detect_material_errors")
    raw = agent.tools.call(
        "detect_material_errors",
        {"filename": request.filename, "min_level": request.min_level, "push": request.push},
        actor=actor,
    )
    result = json.loads(raw)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "物料错误检测失败"))
    return result


@app.post("/agent/chat")
def chat(request: ChatRequest, authorization: str | None = Header(default=None)) -> dict:
    """多轮对话入口：模型通过工具调用循环自主编排采购业务。"""
    actor = _actor(authorization)
    try:
        return agent.chat(request.messages, request.session_id, actor)
    except ERPAdapterError:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/agent/approve")
def approve(request: ApprovalRequest, authorization: str | None = Header(default=None)) -> dict:
    actor = _actor(authorization)
    _authorize(actor, "approve")
    try:
        return repository.approve(request.action_id, actor.user_id if actor else request.approver)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/agent/confirm")
def confirm(request: ConfirmRequest, authorization: str | None = Header(default=None)) -> dict:
    actor = _actor(authorization)
    _authorize(actor, "confirm")
    try:
        return repository.confirm(request.action_id, request.confirmation, actor.user_id if actor else request.operator)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/agent/rollback")
def rollback(request: RollbackRequest, authorization: str | None = Header(default=None)) -> dict:
    actor = _actor(authorization)
    _authorize(actor, "rollback")
    try:
        return repository.rollback(request.action_id, request.reason, actor.user_id if actor else request.operator)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/orders")
def orders(authorization: str | None = Header(default=None)) -> list[dict]:
    _authorize(_actor(authorization), "read")
    return repository.orders()


@app.get("/approvals")
def approvals(authorization: str | None = Header(default=None)) -> list[dict]:
    _authorize(_actor(authorization), "read")
    return repository.pending_actions()


@app.get("/audit")
def audit(authorization: str | None = Header(default=None)) -> list[dict]:
    _authorize(_actor(authorization), "read")
    return repository.audits()


@app.get("/error_reports")
def error_reports(authorization: str | None = Header(default=None)) -> list[dict]:
    _authorize(_actor(authorization), "read")
    return repository.error_reports()
