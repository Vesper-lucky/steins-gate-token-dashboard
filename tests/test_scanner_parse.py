import json
import os
import unittest
from token_dashboard.scanner import parse_record

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name):
    with open(os.path.join(FIXTURES, name)) as f:
        return json.load(f)


class ParseRecordTests(unittest.TestCase):
    def test_parses_assistant_usage(self):
        msg, tools = parse_record(_load("simple_assistant.json"), project_slug="proj-x")
        self.assertEqual(msg["uuid"], "msg-1")
        self.assertEqual(msg["session_id"], "sess-1")
        self.assertEqual(msg["project_slug"], "proj-x")
        self.assertEqual(msg["model"], "claude-opus-4-7")
        self.assertEqual(msg["input_tokens"], 10)
        self.assertEqual(msg["output_tokens"], 5)
        self.assertEqual(msg["cache_read_tokens"], 100)
        self.assertEqual(msg["cache_create_5m_tokens"], 30)
        self.assertEqual(msg["cache_create_1h_tokens"], 20)
        self.assertEqual(msg["is_sidechain"], 0)
        self.assertIsNone(msg["agent_id"])
        self.assertEqual(tools, [])


class ToolExtractionTests(unittest.TestCase):
    def test_extracts_tool_uses(self):
        rec = _load("tool_use_assistant.json")
        msg, tools = parse_record(rec, project_slug="p")
        self.assertEqual(len(tools), 2)
        names = [t["tool_name"] for t in tools]
        self.assertEqual(names, ["Read", "Bash"])
        self.assertEqual(tools[0]["target"], "C:/proj/foo.py")
        self.assertEqual(tools[1]["target"], "npm run lint")
        self.assertIsNotNone(msg["tool_calls_json"])
        parsed = json.loads(msg["tool_calls_json"])
        self.assertEqual(parsed[0]["name"], "Read")
        self.assertEqual(parsed[1]["target"], "npm run lint")


class SidechainTests(unittest.TestCase):
    def test_is_sidechain_flag_propagates(self):
        rec = {
            "type": "assistant", "uuid": "u", "sessionId": "s",
            "timestamp": "t", "isSidechain": True, "agentId": "agent-explore-1",
            "message": {"model": "claude-sonnet-4-6", "usage": {"input_tokens": 1, "output_tokens": 1}},
        }
        msg, _ = parse_record(rec, project_slug="p")
        self.assertEqual(msg["is_sidechain"], 1)
        self.assertEqual(msg["agent_id"], "agent-explore-1")

    def test_tool_result_estimates_tokens(self):
        rec = {
            "type": "user", "uuid": "u2", "sessionId": "s",
            "timestamp": "t", "isSidechain": False,
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "tu1", "content": "x" * 4000, "is_error": False}
            ]},
        }
        msg, tools = parse_record(rec, project_slug="p")
        self.assertEqual(msg["type"], "user")
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["tool_name"], "_tool_result")
        self.assertAlmostEqual(tools[0]["result_tokens"], 1000, delta=10)

    def test_structured_tool_result_is_recursively_estimated(self):
        rec = {
            "type": "user", "uuid": "u3", "sessionId": "s", "timestamp": "t",
            "message": {"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": "tu2",
                "content": {"stdout": "x" * 40, "nested": [{"text": "y" * 20}]},
            }]},
        }
        _, tools = parse_record(rec, project_slug="p")
        self.assertGreaterEqual(tools[0]["result_tokens"], 15)
        self.assertEqual(tools[0]["tool_use_id"], "tu2")
        self.assertTrue(tools[0]["result_estimated"])


if __name__ == "__main__":
    unittest.main()
