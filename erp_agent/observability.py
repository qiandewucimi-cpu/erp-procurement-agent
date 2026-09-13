from __future__ import annotations

import json
import logging
import os
import threading
from collections import defaultdict, deque
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Iterator


request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
session_id_var: ContextVar[str | None] = ContextVar("session_id", default=None)
action_id_var: ContextVar[str | None] = ContextVar("action_id", default=None)
actor_id_var: ContextVar[str | None] = ContextVar("actor_id", default=None)

_CONTEXT_VARS = {
    "request_id": request_id_var,
    "session_id": session_id_var,
    "action_id": action_id_var,
    "actor_id": actor_id_var,
}
_SENSITIVE_MARKERS = ("token", "secret", "authorization", "api_key", "password")


def _redact(value: Any, key: str = "") -> Any:
    if any(marker in key.lower() for marker in _SENSITIVE_MARKERS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", record.getMessage()),
            "message": record.getMessage(),
        }
        for name, var in _CONTEXT_VARS.items():
            if value := var.get():
                payload[name] = value
        fields = getattr(record, "fields", None)
        if fields:
            payload.update(_redact(fields))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging() -> None:
    root = logging.getLogger()
    if getattr(root, "_erp_agent_configured", False):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    root._erp_agent_configured = True  # type: ignore[attr-defined]


def log_event(logger: logging.Logger, event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    logger.log(level, event, extra={"event": event, "fields": fields})


@contextmanager
def bind_context(**values: str | None) -> Iterator[None]:
    tokens = []
    for name, value in values.items():
        if value is not None and name in _CONTEXT_VARS:
            tokens.append((_CONTEXT_VARS[name], _CONTEXT_VARS[name].set(value)))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


class MetricsRegistry:
    """线程安全的进程内运行指标；用于 Demo 排障，不替代 Prometheus。"""

    def __init__(self, max_samples: int = 1000):
        self.max_samples = max_samples
        self._lock = threading.Lock()
        self._stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"total": 0, "success": 0, "failure": 0, "durations": deque(maxlen=max_samples)}
        )

    def record(self, operation: str, success: bool, duration_ms: float) -> None:
        with self._lock:
            stat = self._stats[operation]
            stat["total"] += 1
            stat["success" if success else "failure"] += 1
            stat["durations"].append(round(max(0.0, duration_ms), 3))

    def snapshot(self) -> dict:
        with self._lock:
            operations = {}
            for name, stat in sorted(self._stats.items()):
                durations = sorted(stat["durations"])
                p95_index = max(0, int(len(durations) * 0.95) - 1) if durations else 0
                operations[name] = {
                    "total": stat["total"],
                    "success": stat["success"],
                    "failure": stat["failure"],
                    "avg_ms": round(sum(durations) / len(durations), 3) if durations else 0,
                    "p95_ms": durations[p95_index] if durations else 0,
                }
        return {"mode": "in_process_demo", "operations": operations}

    def reset(self) -> None:
        with self._lock:
            self._stats.clear()


METRICS = MetricsRegistry()
