import unittest
from unittest.mock import patch

from erp_agent.llm import IntentClassifier, _extract_json


class IntentClassifierTest(unittest.TestCase):
    def test_disabled_falls_back_to_rules(self):
        classifier = IntentClassifier(base_url="", model="qwen2:1.5b")
        intent = classifier.classify("请根据 BOM 生成采购 PO")
        self.assertEqual(intent.source, "fallback")
        self.assertEqual(intent.action, "generate_purchase_po")

    def test_fallback_detects_query_intent(self):
        classifier = IntentClassifier(base_url="")
        intent = classifier.classify("我只想查询物料价格，不要生成单据")
        self.assertEqual(intent.action, "query_materials")
        self.assertEqual(intent.source, "fallback")

    def test_llm_happy_path(self):
        classifier = IntentClassifier(base_url="http://127.0.0.1:11434/v1", model="qwen2:1.5b", api_key="")
        fake_response = {"choices": [{"message": {"content": '{"action": "generate_purchase_po", "reason": "生成采购单"}'}}]}
        with patch("requests.post") as post:
            post.return_value.raise_for_status.return_value = None
            post.return_value.json.return_value = fake_response
            intent = classifier.classify("根据 BOM 生成采购 PO 并校验")
        self.assertEqual(intent.source, "llm")
        self.assertEqual(intent.action, "generate_purchase_po")
        self.assertEqual(intent.model, "qwen2:1.5b")

    def test_llm_markdown_fence_is_parsed(self):
        classifier = IntentClassifier(base_url="http://x/v1", model="m")
        fake_response = {"choices": [{"message": {"content": "```json\n{\"action\": \"query_materials\", \"reason\": \"查价\"}\n```"}}]}
        with patch("requests.post") as post:
            post.return_value.raise_for_status.return_value = None
            post.return_value.json.return_value = fake_response
            intent = classifier.classify("查一下价格")
        self.assertEqual(intent.action, "query_materials")

    def test_llm_invalid_action_falls_back(self):
        # 白名单外的动作（如 delete_all）必须回退，防止幻觉引入越权意图。
        classifier = IntentClassifier(base_url="http://x/v1", model="m")
        fake_response = {"choices": [{"message": {"content": '{"action": "delete_all", "reason": "x"}'}}]}
        with patch("requests.post") as post:
            post.return_value.raise_for_status.return_value = None
            post.return_value.json.return_value = fake_response
            intent = classifier.classify("全部删掉")
        self.assertEqual(intent.source, "fallback")

    def test_llm_chinese_alias_is_normalized(self):
        # 小模型常输出中文枚举，归一化层应映射回白名单而非回退。
        classifier = IntentClassifier(base_url="http://x/v1", model="m")
        fake_response = {"choices": [{"message": {"content": '{"action": "生成采购PO"}'}}]}
        with patch("requests.post") as post:
            post.return_value.raise_for_status.return_value = None
            post.return_value.json.return_value = fake_response
            intent = classifier.classify("帮我生成采购 PO")
        self.assertEqual(intent.source, "llm")
        self.assertEqual(intent.action, "generate_purchase_po")

    def test_llm_unknown_falls_back(self):
        # 模型返回 unknown 表示放弃判断，应交给确定性规则兜底。
        classifier = IntentClassifier(base_url="http://x/v1", model="m")
        fake_response = {"choices": [{"message": {"content": '{"action": "unknown", "reason": "不确定"}'}}]}
        with patch("requests.post") as post:
            post.return_value.raise_for_status.return_value = None
            post.return_value.json.return_value = fake_response
            intent = classifier.classify("帮我生成采购 PO")
        self.assertEqual(intent.source, "fallback")
        self.assertEqual(intent.action, "generate_purchase_po")

    def test_llm_network_error_falls_back(self):
        classifier = IntentClassifier(base_url="http://x/v1", model="m", timeout=1)
        with patch("requests.post", side_effect=Exception("boom")):
            intent = classifier.classify("生成采购 PO")
        self.assertEqual(intent.source, "fallback")


class ExtractJsonTest(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(_extract_json('{"action": "a"}')["action"], "a")

    def test_fenced_json(self):
        self.assertEqual(_extract_json('```json\n{"action": "b"}\n```')["action"], "b")

    def test_json_with_noise(self):
        self.assertEqual(_extract_json('结果是 {"action": "c"} 以上')["action"], "c")

    def test_invalid_returns_none(self):
        self.assertIsNone(_extract_json("不是 json"))


if __name__ == "__main__":
    unittest.main()
