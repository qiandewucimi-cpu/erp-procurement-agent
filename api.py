import json
from pathlib import Path

from fastapi import FastAPI, HTTPException

from erp_agent.agent import PurchasePOAgent
from erp_agent.knowledge import KnowledgeBase
from erp_agent.models import (
    ChatRequest,
    ConfirmRequest,
    DetectRequest,
    PrepareRequest,
    PrepareResponse,
    RollbackRequest,
)
from erp_agent.repository import ERPRepository


BASE_DIR = Path(__file__).resolve().parent
repository = ERPRepository(BASE_DIR / "data" / "demo_erp.db")
agent = PurchasePOAgent(repository, KnowledgeBase(BASE_DIR / "knowledge"), BASE_DIR / "samples")

app = FastAPI(
    title="外贸 ERP 安全操作 Agent",
    version="0.1.0",
    description="基于合成数据演示 BOM → 采购 PO、写前确认、审计与回滚。",
)


@app.get("/health")
def health() -> dict:
    """健康检查，同时回传 LLM 可用性，便于前端显示「模型是否真的在工作」。"""
    return {
        "status": "ok",
        "mode": "synthetic-demo",
        "production_connected": False,
        "llm_enabled": agent.loop.enabled,
        "llm_model": agent.loop.model,
    }


@app.get("/materials")
def materials() -> list[dict]:
    """列出模拟 ERP 的物料档案（编码、名称、供应商、单价、包装费、币种）。"""
    return repository.materials()


@app.get("/samples")
def samples() -> list[str]:
    return sorted(path.name for path in (BASE_DIR / "samples").glob("*.xlsx"))


@app.post("/agent/prepare", response_model=PrepareResponse)
def prepare(request: PrepareRequest) -> PrepareResponse:
    try:
        return agent.prepare(request.task, request.filename, request.content_base64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/agent/detect")
def detect(request: DetectRequest) -> dict:
    """物料错误检测：解析 BOM → 逐行校验 → 生成分级错误报告。

    push=true 时把报告写入推送队列（error_reports 表，模拟推送给录单员），
    之后可通过 GET /error_reports 查看。
    """
    raw = agent.tools.call(
        "detect_material_errors",
        {"filename": request.filename, "min_level": request.min_level, "push": request.push},
    )
    result = json.loads(raw)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "物料错误检测失败"))
    return result


@app.post("/agent/chat")
def chat(request: ChatRequest) -> dict:
    """多轮对话入口：模型通过工具调用循环自主编排采购业务。"""
    try:
        return agent.chat(request.messages, request.session_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/agent/confirm")
def confirm(request: ConfirmRequest) -> dict:
    try:
        return repository.confirm(request.action_id, request.confirmation, request.operator)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/agent/rollback")
def rollback(request: RollbackRequest) -> dict:
    try:
        return repository.rollback(request.action_id, request.reason, request.operator)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/orders")
def orders() -> list[dict]:
    return repository.orders()


@app.get("/audit")
def audit() -> list[dict]:
    return repository.audits()


@app.get("/error_reports")
def error_reports() -> list[dict]:
    return repository.error_reports()

