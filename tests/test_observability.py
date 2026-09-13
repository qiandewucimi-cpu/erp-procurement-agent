import io
import json
import logging
import unittest

from fastapi.testclient import TestClient

import api as api_module
from erp_agent.observability import JsonFormatter, METRICS, MetricsRegistry, bind_context, log_event


class ObservabilityTest(unittest.TestCase):
    def setUp(self):
        METRICS.reset()

    def test_json_formatter_redacts_secrets_and_includes_context(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonFormatter())
        logger = logging.getLogger("test.observability")
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(logging.INFO)

        with bind_context(request_id="REQ-TEST", session_id="SESSION-TEST"):
            log_event(logger, "demo.event", api_token="do-not-print", nested={"password": "hidden"}, count=2)

        payload = json.loads(stream.getvalue())
        self.assertEqual(payload["request_id"], "REQ-TEST")
        self.assertEqual(payload["session_id"], "SESSION-TEST")
        self.assertEqual(payload["api_token"], "[REDACTED]")
        self.assertEqual(payload["nested"]["password"], "[REDACTED]")
        self.assertNotIn("do-not-print", stream.getvalue())
        self.assertNotIn("hidden", stream.getvalue())

    def test_metrics_snapshot_counts_and_percentiles(self):
        registry = MetricsRegistry()
        for duration in (10, 20, 30, 40):
            registry.record("tool.demo", duration != 30, duration)
        stat = registry.snapshot()["operations"]["tool.demo"]
        self.assertEqual(stat["total"], 4)
        self.assertEqual(stat["success"], 3)
        self.assertEqual(stat["failure"], 1)
        self.assertEqual(stat["avg_ms"], 25)
        self.assertEqual(stat["p95_ms"], 30)

    def test_api_returns_request_id_and_exposes_metrics(self):
        client = TestClient(api_module.app)
        response = client.get("/health", headers={"X-Request-ID": "REQ-FROM-CALLER"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Request-ID"], "REQ-FROM-CALLER")

        metrics = client.get("/metrics")
        self.assertEqual(metrics.status_code, 200)
        http_stat = metrics.json()["operations"]["http.request"]
        self.assertGreaterEqual(http_stat["total"], 1)


if __name__ == "__main__":
    unittest.main()
