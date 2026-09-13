import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

import api as api_module
from erp_agent.adapters import ERPAdapter
from erp_agent.knowledge import KnowledgeBase
from erp_agent.repository import ERPRepository
from erp_agent.security import (
    AccessController,
    Actor,
    AuthenticationRequired,
    PermissionDenied,
)
from erp_agent.tools import ToolRegistry


ROOT = Path(__file__).resolve().parents[1]


class AccessControllerTest(unittest.TestCase):
    def setUp(self):
        self.access = AccessController(
            enabled=True,
            identities={
                "view-token": Actor("viewer-1", "viewer"),
                "op-token": Actor("operator-1", "operator"),
                "approve-token": Actor("approver-1", "approver"),
            },
        )

    def test_missing_and_invalid_credentials_are_rejected(self):
        with self.assertRaises(AuthenticationRequired):
            self.access.authenticate(None)
        with self.assertRaises(AuthenticationRequired):
            self.access.authenticate("Bearer wrong")

    def test_token_binds_identity_and_role(self):
        actor = self.access.authenticate("Bearer op-token")
        self.assertEqual(actor, Actor("operator-1", "operator"))
        self.assertEqual(self.access.actor_for_user_id("operator-1"), actor)

    def test_viewer_cannot_create_and_operator_cannot_approve(self):
        with self.assertRaises(PermissionDenied):
            self.access.authorize(Actor("v", "viewer"), "create_purchase_order")
        with self.assertRaises(PermissionDenied):
            self.access.authorize(Actor("o", "operator"), "approve_action")

    def test_env_configuration_is_validated(self):
        env = {
            "ERP_AUTH_ENABLED": "true",
            "ERP_AUTH_IDENTITIES_JSON": json.dumps({"token": {"user_id": "u1", "role": "viewer"}}),
        }
        with patch.dict(os.environ, env, clear=False):
            access = AccessController.from_env()
        self.assertTrue(access.enabled)
        self.assertEqual(access.authenticate("Bearer token").user_id, "u1")


class ApprovalStateMachineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = ROOT / "data" / "_test_security.db"
        cls.db.unlink(missing_ok=True)
        cls.repo = ERPRepository(cls.db)
        cls.access = AccessController(enabled=True)
        cls.tools = ToolRegistry(
            cls.repo,
            KnowledgeBase(ROOT / "knowledge"),
            ROOT / "samples",
            access_controller=cls.access,
        )

    @classmethod
    def tearDownClass(cls):
        cls.db.unlink(missing_ok=True)

    def setUp(self):
        self.operator = Actor("alice", "operator")
        self.approver = Actor("bob", "approver")
        self.viewer = Actor("carol", "viewer")

    def create_action(self):
        result = json.loads(
            self.tools.call("create_purchase_order", {"filename": "正常示例_BOM.xlsx"}, actor=self.operator)
        )
        self.assertTrue(result["ok"])
        return result["action_id"]

    def test_full_state_machine_and_audit_chain(self):
        action_id = self.create_action()
        pending = {x["action_id"]: x for x in self.repo.pending_actions()}[action_id]
        self.assertEqual(pending["status"], "PENDING_APPROVAL")
        self.assertEqual(pending["requested_by"], "alice")

        approved = json.loads(self.tools.call("approve_action", {"action_id": action_id}, actor=self.approver))
        self.assertEqual(approved["status"], "APPROVED")
        committed = json.loads(
            self.tools.call(
                "confirm_commit",
                {"action_id": action_id, "confirmation": "确认提交", "operator": "spoofed"},
                actor=self.approver,
            )
        )
        self.assertEqual(committed["status"], "COMMITTED")
        pending = {x["action_id"]: x for x in self.repo.pending_actions()}[action_id]
        self.assertEqual(pending["approved_by"], "bob")
        events = [x["event"] for x in reversed(self.repo.audits()) if x["action_id"] == action_id]
        self.assertEqual(events, ["DRAFT_CREATED", "APPROVAL_REQUESTED", "ACTION_APPROVED", "WRITE_COMMITTED"])

    def test_model_supplied_operator_cannot_spoof_identity(self):
        action_id = self.create_action()
        result = json.loads(
            self.tools.call("approve_action", {"action_id": action_id, "operator": "admin"}, actor=self.approver)
        )
        self.assertTrue(result["ok"])
        pending = {x["action_id"]: x for x in self.repo.pending_actions()}[action_id]
        self.assertEqual(pending["approved_by"], "bob")

    def test_requester_cannot_self_approve_even_with_approver_role(self):
        action_id = self.create_action()
        result = json.loads(self.tools.call("approve_action", {"action_id": action_id}, actor=Actor("alice", "approver")))
        self.assertFalse(result["ok"])
        self.assertIn("发起人不能审批", result["error"])

    def test_viewer_cannot_create_or_commit(self):
        create = json.loads(
            self.tools.call("create_purchase_order", {"filename": "正常示例_BOM.xlsx"}, actor=self.viewer)
        )
        self.assertFalse(create["ok"])
        self.assertIn("PermissionDenied", create["error"])

        action_id = self.create_action()
        commit = json.loads(
            self.tools.call("confirm_commit", {"action_id": action_id, "confirmation": "确认提交"}, actor=self.viewer)
        )
        self.assertFalse(commit["ok"])

    def test_sqlite_adapter_still_satisfies_extended_protocol(self):
        self.assertIsInstance(self.repo, ERPAdapter)


class SecuredApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_access = api_module.access
        cls.old_repository = api_module.repository
        cls.old_agent = api_module.agent
        cls.db = ROOT / "data" / f"api_security_{uuid4().hex}.db"
        cls.repo = ERPRepository(cls.db)
        cls.access = AccessController(
            enabled=True,
            identities={
                "viewer": Actor("carol", "viewer"),
                "operator": Actor("alice", "operator"),
                "approver": Actor("bob", "approver"),
            },
        )
        api_module.access = cls.access
        api_module.repository = cls.repo
        api_module.agent = api_module.PurchasePOAgent(
            cls.repo,
            KnowledgeBase(ROOT / "knowledge"),
            ROOT / "samples",
            access_controller=cls.access,
        )
        cls.client = TestClient(api_module.app)

    @classmethod
    def tearDownClass(cls):
        api_module.access = cls.old_access
        api_module.repository = cls.old_repository
        api_module.agent = cls.old_agent
        cls.db.unlink(missing_ok=True)

    @staticmethod
    def headers(token):
        return {"Authorization": f"Bearer {token}"}

    def test_missing_token_is_401_and_viewer_cannot_prepare(self):
        self.assertEqual(self.client.get("/materials").status_code, 401)
        denied = self.client.post(
            "/agent/prepare",
            headers=self.headers("viewer"),
            json={"task": "根据 BOM 生成采购 PO", "filename": "正常示例_BOM.xlsx"},
        )
        self.assertEqual(denied.status_code, 403)

    def test_operator_and_approver_complete_separated_flow(self):
        prepared = self.client.post(
            "/agent/prepare",
            headers=self.headers("operator"),
            json={"task": "根据 BOM 生成采购 PO", "filename": "正常示例_BOM.xlsx"},
        )
        self.assertEqual(prepared.status_code, 200)
        action_id = prepared.json()["action_id"]
        denied = self.client.post(
            "/agent/approve",
            headers=self.headers("operator"),
            json={"action_id": action_id},
        )
        self.assertEqual(denied.status_code, 403)
        approved = self.client.post(
            "/agent/approve",
            headers=self.headers("approver"),
            json={"action_id": action_id},
        )
        self.assertEqual(approved.json()["status"], "APPROVED")
        committed = self.client.post(
            "/agent/confirm",
            headers=self.headers("approver"),
            json={"action_id": action_id, "confirmation": "确认提交"},
        )
        self.assertEqual(committed.json()["status"], "COMMITTED")


if __name__ == "__main__":
    unittest.main()
