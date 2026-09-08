from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class ERPRepository:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def session(self):
        """SQLite 的 with 只管事务、不自动 close；这里统一提交并关闭连接。"""
        connection = self.connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.session() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS materials (
                    material_code TEXT PRIMARY KEY,
                    material_name TEXT NOT NULL,
                    supplier_code TEXT NOT NULL,
                    supplier_name TEXT NOT NULL,
                    unit_price REAL NOT NULL,
                    packaging_fee REAL NOT NULL,
                    currency TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pending_actions (
                    action_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    committed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS purchase_orders (
                    po_no TEXT PRIMARY KEY,
                    action_id TEXT UNIQUE NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    rolled_back_at TEXT
                );
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_id TEXT NOT NULL,
                    event TEXT NOT NULL,
                    operator TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS error_reports (
                    report_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    errors_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    pushed_at TEXT
                );
                """
            )
            con.executemany(
                """
                INSERT OR IGNORE INTO materials
                (material_code, material_name, supplier_code, supplier_name,
                 unit_price, packaging_fee, currency)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    ("MAT-FAB-001", "再生涤纶面料", "SUP-001", "示例纺织供应商", 18.60, 0.35, "CNY"),
                    ("MAT-ZIP-002", "尼龙拉链", "SUP-001", "示例纺织供应商", 1.25, 0.08, "CNY"),
                    ("MAT-LBL-003", "洗水唛", "SUP-001", "示例纺织供应商", 0.42, 0.03, "CNY"),
                ],
            )

    def material(self, code: str) -> dict | None:
        with self.session() as con:
            row = con.execute("SELECT * FROM materials WHERE material_code = ?", (code,)).fetchone()
        return dict(row) if row else None

    def create_pending(self, payload: dict, operator: str = "demo_user") -> str:
        action_id = f"ACT-{uuid4().hex[:10].upper()}"
        with self.session() as con:
            con.execute(
                "INSERT INTO pending_actions VALUES (?, 'PREVIEWED', ?, ?, NULL)",
                (action_id, json.dumps(payload, ensure_ascii=False), _now()),
            )
            self._audit(con, action_id, "PREVIEW_CREATED", operator, {"ready": payload["ready"]})
        return action_id

    def confirm(self, action_id: str, confirmation: str, operator: str) -> dict:
        if confirmation != "确认提交":
            raise ValueError("安全校验失败：请输入“确认提交”")
        with self.session() as con:
            row = con.execute("SELECT * FROM pending_actions WHERE action_id = ?", (action_id,)).fetchone()
            if not row:
                raise KeyError("找不到待确认操作")
            payload = json.loads(row["payload_json"])
            if not payload["ready"]:
                raise ValueError("当前草稿存在阻断问题，禁止写入")
            existing = con.execute("SELECT * FROM purchase_orders WHERE action_id = ?", (action_id,)).fetchone()
            if existing:
                return dict(existing) | {"idempotent": True}
            po_no = f"PO-DEMO-{datetime.now().strftime('%Y%m%d')}-{action_id[-4:]}"
            committed = _now()
            con.execute(
                "INSERT INTO purchase_orders VALUES (?, ?, 'COMMITTED', ?, ?, NULL)",
                (po_no, action_id, json.dumps(payload["draft"], ensure_ascii=False), committed),
            )
            con.execute(
                "UPDATE pending_actions SET status='COMMITTED', committed_at=? WHERE action_id=?",
                (committed, action_id),
            )
            self._audit(con, action_id, "WRITE_CONFIRMED", operator, {"po_no": po_no})
        return {"po_no": po_no, "action_id": action_id, "status": "COMMITTED", "idempotent": False}

    def rollback(self, action_id: str, reason: str, operator: str) -> dict:
        with self.session() as con:
            row = con.execute("SELECT * FROM purchase_orders WHERE action_id = ?", (action_id,)).fetchone()
            if not row:
                raise KeyError("找不到已提交的采购 PO")
            if row["status"] == "ROLLED_BACK":
                return {"po_no": row["po_no"], "status": "ROLLED_BACK", "idempotent": True}
            rolled_back = _now()
            con.execute(
                "UPDATE purchase_orders SET status='ROLLED_BACK', rolled_back_at=? WHERE action_id=?",
                (rolled_back, action_id),
            )
            con.execute("UPDATE pending_actions SET status='ROLLED_BACK' WHERE action_id=?", (action_id,))
            self._audit(con, action_id, "WRITE_ROLLED_BACK", operator, {"reason": reason})
        return {"po_no": row["po_no"], "status": "ROLLED_BACK", "idempotent": False}

    @staticmethod
    def _audit(con: sqlite3.Connection, action_id: str, event: str, operator: str, detail: dict) -> None:
        con.execute(
            "INSERT INTO audit_logs(action_id,event,operator,detail_json,created_at) VALUES(?,?,?,?,?)",
            (action_id, event, operator, json.dumps(detail, ensure_ascii=False), _now()),
        )

    def orders(self) -> list[dict]:
        with self.session() as con:
            rows = con.execute("SELECT * FROM purchase_orders ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]

    def audits(self) -> list[dict]:
        with self.session() as con:
            rows = con.execute("SELECT * FROM audit_logs ORDER BY id DESC").fetchall()
        return [dict(row) for row in rows]

    def save_error_report(self, summary: dict, errors: list[dict], operator: str = "demo_user") -> str:
        """把错误报告写入 error_reports 表，模拟推送到录单员的消息队列（outbox）。"""
        report_id = f"ERR-{uuid4().hex[:10].upper()}"
        with self.session() as con:
            con.execute(
                "INSERT INTO error_reports VALUES (?, 'PENDING_PUSH', ?, ?, ?, NULL)",
                (
                    report_id,
                    json.dumps(summary, ensure_ascii=False),
                    json.dumps(errors, ensure_ascii=False),
                    _now(),
                ),
            )
            self._audit(
                con,
                report_id,
                "ERROR_REPORT_CREATED",
                operator,
                {"blocking": summary["blocking"], "warning": summary["warning"]},
            )
        return report_id

    def error_reports(self) -> list[dict]:
        with self.session() as con:
            rows = con.execute("SELECT * FROM error_reports ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]
