import json
import tempfile
import unittest
from pathlib import Path

from evals.run_rag_eval import evaluate, write_report
from erp_agent.knowledge import KnowledgeBase


class RagEvaluationTest(unittest.TestCase):
    def test_default_dataset_meets_quality_gate(self):
        result = evaluate()
        self.assertTrue(result["passed"], result["metrics"])
        self.assertGreaterEqual(result["metrics"]["recall_at_3"], 0.9)
        self.assertEqual(result["metrics"]["rejection_accuracy"], 1.0)

    def test_report_and_json_are_reproducible_artifacts(self):
        result = evaluate()
        with tempfile.TemporaryDirectory() as temp_dir:
            results_path = Path(temp_dir) / "results.json"
            report_path = Path(temp_dir) / "report.md"
            write_report(result, results_path, report_path)
            stored = json.loads(results_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["metrics"], result["metrics"])
            self.assertIn("Recall@3", report_path.read_text(encoding="utf-8"))

    def test_out_of_scope_query_returns_no_fake_citation(self):
        root = Path(__file__).resolve().parents[1]
        knowledge = KnowledgeBase(root / "knowledge")
        self.assertEqual(knowledge.search("公司的年假审批制度是什么？"), [])


if __name__ == "__main__":
    unittest.main()
