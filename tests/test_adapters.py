import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from erp_agent.adapters import (
    ERPAdapter,
    ERPAdapterError,
    ERPAuthenticationError,
    ERPConflictError,
    ERPUnavailableError,
    HTTPERPAdapter,
    build_erp_adapter,
)
from erp_agent.repository import ERPRepository


class FakeResponse:
    def __init__(self, status_code=200, payload=None, json_error=False):
        self.status_code = status_code
        self.payload = payload
        self.json_error = json_error

    def json(self):
        if self.json_error:
            raise ValueError("not json")
        return self.payload


class ScriptedSession:
    def __init__(self, *events):
        self.events = list(events)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        event = self.events.pop(0)
        if isinstance(event, Exception):
            raise event
        return event


class HTTPERPAdapterTest(unittest.TestCase):
    def adapter(self, *events, **kwargs):
        session = ScriptedSession(*events)
        sleeps = []
        adapter = HTTPERPAdapter(
            "https://erp.example/api",
            token="secret-token",
            timeout=1.5,
            max_retries=kwargs.get("max_retries", 2),
            backoff_seconds=0.1,
            session=session,
            sleeper=sleeps.append,
        )
        return adapter, session, sleeps

    def test_timeout_retries_then_succeeds(self):
        adapter, session, sleeps = self.adapter(
            requests.Timeout(), requests.Timeout(), FakeResponse(payload={"items": [{"material_code": "M1"}]})
        )
        self.assertEqual(adapter.materials()[0]["material_code"], "M1")
        self.assertEqual(len(session.calls), 3)
        self.assertEqual(sleeps, [0.1, 0.2])
        self.assertEqual(session.calls[0]["timeout"], 1.5)
        self.assertEqual(session.calls[0]["headers"]["Authorization"], "Bearer secret-token")

    def test_retryable_http_status_then_succeeds(self):
        adapter, session, sleeps = self.adapter(FakeResponse(503, {}), FakeResponse(200, {"items": []}))
        self.assertEqual(adapter.orders(), [])
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(sleeps, [0.1])

    def test_timeout_exhaustion_maps_to_unavailable(self):
        adapter, _, _ = self.adapter(requests.Timeout(), requests.Timeout(), max_retries=1)
        with self.assertRaises(ERPUnavailableError):
            adapter.audits()

    def test_http_errors_have_stable_types(self):
        adapter, _, _ = self.adapter(FakeResponse(401, {}), max_retries=0)
        with self.assertRaises(ERPAuthenticationError):
            adapter.orders()

        adapter, _, _ = self.adapter(FakeResponse(409, {}), max_retries=0)
        with self.assertRaises(ERPConflictError):
            adapter.orders()

        adapter, _, _ = self.adapter(FakeResponse(418, {}), max_retries=0)
        with self.assertRaises(ERPAdapterError):
            adapter.orders()

    def test_not_found_material_returns_none(self):
        adapter, _, _ = self.adapter(FakeResponse(404, {}), max_retries=0)
        self.assertIsNone(adapter.material("UNKNOWN/1"))

    def test_non_json_response_is_rejected(self):
        adapter, _, _ = self.adapter(FakeResponse(200, json_error=True), max_retries=0)
        with self.assertRaisesRegex(ERPAdapterError, "非 JSON"):
            adapter.orders()

    def test_confirm_sends_idempotency_key(self):
        adapter, session, _ = self.adapter(FakeResponse(200, {"status": "COMMITTED"}))
        result = adapter.confirm("ACT-001", "确认提交", "approver")
        self.assertEqual(result["status"], "COMMITTED")
        call = session.calls[0]
        self.assertTrue(call["url"].endswith("/actions/ACT-001/confirm"))
        self.assertEqual(call["headers"]["Idempotency-Key"], "erp-agent:confirm:ACT-001")

    def test_approve_sends_bound_identity_and_idempotency_key(self):
        adapter, session, _ = self.adapter(FakeResponse(200, {"status": "APPROVED"}))
        result = adapter.approve("ACT-001", "approver-1")
        self.assertEqual(result["status"], "APPROVED")
        call = session.calls[0]
        self.assertEqual(call["json"]["approver"], "approver-1")
        self.assertEqual(call["headers"]["Idempotency-Key"], "erp-agent:approve:ACT-001")

    def test_preview_idempotency_key_is_deterministic(self):
        adapter, session, _ = self.adapter(
            FakeResponse(200, {"action_id": "ACT-1"}),
            FakeResponse(200, {"action_id": "ACT-1"}),
        )
        payload = {"ready": True, "draft": {"total": 12.3}}
        self.assertEqual(adapter.create_pending(payload, "operator"), "ACT-1")
        self.assertEqual(adapter.create_pending(payload, "operator"), "ACT-1")
        first = session.calls[0]["headers"]["Idempotency-Key"]
        second = session.calls[1]["headers"]["Idempotency-Key"]
        self.assertEqual(first, second)


class AdapterFactoryTest(unittest.TestCase):
    def test_sqlite_is_default_and_satisfies_protocol(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"ERP_BACKEND": "sqlite"}, clear=False):
            adapter = build_erp_adapter(Path(tmp))
            self.assertIsInstance(adapter, ERPRepository)
            self.assertIsInstance(adapter, ERPAdapter)

    def test_http_configuration(self):
        env = {
            "ERP_BACKEND": "http",
            "ERP_API_BASE_URL": "https://customer.example/erp",
            "ERP_API_TOKEN": "token",
            "ERP_API_TIMEOUT": "3.5",
            "ERP_API_MAX_RETRIES": "4",
        }
        with patch.dict(os.environ, env, clear=False):
            adapter = build_erp_adapter(Path("."))
        self.assertIsInstance(adapter, HTTPERPAdapter)
        self.assertEqual(adapter.timeout, 3.5)
        self.assertEqual(adapter.max_retries, 4)

    def test_factory_reads_project_env_file(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            (root / ".env").write_text(
                "ERP_BACKEND=http\nERP_API_BASE_URL=https://env-file.example/api\nERP_API_TIMEOUT=2\n",
                encoding="utf-8",
            )
            adapter = build_erp_adapter(root)
        self.assertIsInstance(adapter, HTTPERPAdapter)
        self.assertEqual(adapter.base_url, "https://env-file.example/api")
        self.assertEqual(adapter.timeout, 2.0)

    def test_unknown_backend_is_rejected(self):
        with patch.dict(os.environ, {"ERP_BACKEND": "ftp"}, clear=False):
            with self.assertRaisesRegex(ValueError, "ERP_BACKEND"):
                build_erp_adapter(Path("."))


if __name__ == "__main__":
    unittest.main()
