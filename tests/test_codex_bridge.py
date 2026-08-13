import json
import tempfile
import unittest
from pathlib import Path

from codex_bridge import BRIDGE_FORMAT_VERSION, convert_file, sync_once


class CodexBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "sessions"
        self.out = Path(self.tmp.name) / "out"
        self.root.mkdir()
        self.source = self.root / "rollout-test.jsonl"
        events = [
            {"type": "session_meta", "payload": {"id": "s1", "cwd": "/home/example/project-a"}},
            {"type": "turn_context", "payload": {"model": "gpt-5.5"}},
            {
                "timestamp": "2026-06-09T00:00:00Z",
                "payload": {
                    "info": {
                        "last_token_usage": {
                            "input_tokens": 100,
                            "cached_input_tokens": 40,
                            "output_tokens": 10,
                        }
                    }
                },
            },
        ]
        with self.source.open("w", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event))
                handle.write("\n")

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, path, events):
        with path.open("w", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event) + "\n")

    @staticmethod
    def _token(ts, last, total):
        return {
            "type": "event_msg", "timestamp": ts,
            "payload": {"type": "token_count", "info": {
                "last_token_usage": last, "total_token_usage": total,
            }},
        }

    def test_sync_once_skips_unchanged_sources(self):
        first = sync_once(self.out, [self.root])
        self.assertEqual(first["sessions"], 1)
        self.assertEqual(first["records"], 1)
        self.assertEqual(first["skipped"], 0)

        second = sync_once(self.out, [self.root])
        self.assertEqual(second["sessions"], 1)
        self.assertEqual(second["records"], 1)
        self.assertEqual(second["skipped"], 1)
        self.assertTrue((self.out / ".codex_bridge_state.json").is_file())

    def test_custom_exec_wrapper_records_nested_tools_and_skill(self):
        events = [
            {"type": "session_meta", "payload": {"id": "s2", "cwd": "/tmp/project"}},
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "name": "exec",
                    "call_id": "custom-1",
                    "input": (
                        "const a = await tools.exec_command({cmd:'date'});\n"
                        "const b = await tools.apply_patch(patch);\n"
                        "const skill = '/tmp/skills/investigate/SKILL.md';"
                    ),
                },
            },
            {
                "type": "event_msg",
                "timestamp": "2026-08-12T00:00:00Z",
                "payload": {
                    "info": {
                        "last_token_usage": {
                            "input_tokens": 100,
                            "cached_input_tokens": 40,
                            "output_tokens": 10,
                        }
                    }
                },
            },
        ]
        with self.source.open("w", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event) + "\n")

        _, _, records = convert_file(self.source)
        content = records[-1]["message"]["content"]
        self.assertEqual(
            [item["name"] for item in content if item["type"] == "tool_use"],
            ["Bash", "Edit", "Skill"],
        )
        self.assertEqual(content[-1]["input"], {"skill": "investigate"})

    def test_custom_calls_ignore_js_text_and_support_direct_tools(self):
        events = [
            {"type": "session_meta", "payload": {"id": "s3", "cwd": "/tmp/project"}},
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "name": "exec",
                    "call_id": "custom-1",
                    "input": (
                        "const a = await tools.exec_command({cmd:'rg \"tools.fake()\" .'});\n"
                        "// tools.commented_out();\n"
                        "const label = 'tools.also_fake(';\n"
                        "/* tools.block_comment() */\n"
                        "await tools.update_plan({plan: []});"
                    ),
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "name": "apply_patch",
                    "call_id": "custom-2",
                    "input": "*** Begin Patch\n*** Update File: app.py\n@@\n-old\n+new\n*** End Patch",
                },
            },
            {
                "type": "event_msg",
                "timestamp": "2026-08-12T00:00:00Z",
                "payload": {
                    "info": {
                        "last_token_usage": {
                            "input_tokens": 100,
                            "cached_input_tokens": 40,
                            "output_tokens": 10,
                        }
                    }
                },
            },
        ]
        with self.source.open("w", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event) + "\n")

        _, _, records = convert_file(self.source)
        content = records[-1]["message"]["content"]
        tools = [item for item in content if item["type"] == "tool_use"]

        self.assertEqual([item["name"] for item in tools], ["Bash", "update_plan", "Edit"])
        self.assertEqual(tools[-1]["input"], {"file_path": "app.py"})

    def test_format_version_change_rebuilds_unchanged_sources(self):
        sync_once(self.out, [self.root])
        state_path = self.out / ".codex_bridge_state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["version"] = BRIDGE_FORMAT_VERSION - 1
        state_path.write_text(json.dumps(state), encoding="utf-8")

        rebuilt = sync_once(self.out, [self.root])

        self.assertEqual(rebuilt["skipped"], 0)
        current = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(current["version"], BRIDGE_FORMAT_VERSION)

    def test_cumulative_state_dedup_epochs_and_exact_buckets(self):
        base = {
            "input_tokens": 100, "cached_input_tokens": 20,
            "cache_write_input_tokens": 10, "output_tokens": 5,
            "reasoning_output_tokens": 2, "total_tokens": 105,
        }
        events = [
            {"type": "session_meta", "payload": {"id": "state", "cwd": "/tmp/p"}},
            {"type": "turn_context", "payload": {"model": "gpt-5.6-terra"}},
            {"type": "event_msg", "timestamp": "2026-08-12T00:00:00Z", "payload": {
                "type": "user_message", "client_id": "prompt-1", "message": "private text"}},
            self._token("2026-08-12T00:00:01Z", base, base),
            self._token("2026-08-12T00:00:02Z", base, base),
            self._token("2026-08-12T00:00:03Z", base, {
                **base, "input_tokens": 200, "cached_input_tokens": 40,
                "cache_write_input_tokens": 20, "output_tokens": 10,
                "reasoning_output_tokens": 4, "total_tokens": 210,
            }),
            self._token("2026-08-12T00:00:04Z", {
                **base, "input_tokens": 50, "cached_input_tokens": 10,
                "cache_write_input_tokens": 5,
            }, {
                **base, "input_tokens": 50, "cached_input_tokens": 10,
                "cache_write_input_tokens": 5, "total_tokens": 55,
            }),
            self._token("2026-08-12T00:00:05Z", {
                "input_tokens": 0, "cached_input_tokens": 0,
                "cache_write_input_tokens": 0, "output_tokens": 0,
                "reasoning_output_tokens": 0, "total_tokens": 999,
            }, {
                **base, "input_tokens": 150, "cached_input_tokens": 30,
                "cache_write_input_tokens": 15, "total_tokens": 160,
            }),
        ]
        self._write(self.source, events)

        _, _, records = convert_file(self.source)
        users = [record for record in records if record["type"] == "user"]
        calls = [record for record in records if record["type"] == "assistant"]

        self.assertEqual(len(users), 1)
        self.assertEqual(users[0]["message"]["content"], "[prompt omitted by divergence-ledger]")
        self.assertEqual(users[0]["message"]["prompt_chars"], len("private text"))
        self.assertEqual(len(calls), 3)
        usage = calls[0]["message"]["usage"]
        self.assertEqual(usage["input_tokens"], 70)
        self.assertEqual(usage["cache_read_input_tokens"], 20)
        self.assertEqual(usage["cache_creation"]["ephemeral_5m_input_tokens"], 10)
        self.assertEqual(usage["output_tokens"], 5)
        self.assertEqual(usage["reasoning_output_tokens"], 2)
        self.assertEqual(
            usage["input_tokens"] + usage["cache_read_input_tokens"]
            + usage["cache_creation"]["ephemeral_5m_input_tokens"],
            usage["original_input_tokens"],
        )
        self.assertNotEqual(calls[0]["eventKey"], calls[1]["eventKey"])
        self.assertIn("usage:1:", calls[2]["eventKey"])

    def test_legacy_input_uses_compatibility_cache_write_bucket(self):
        _, _, records = convert_file(self.source)
        usage = records[-1]["message"]["usage"]
        self.assertEqual(usage["input_tokens"], 0)
        self.assertEqual(usage["cache_read_input_tokens"], 40)
        self.assertEqual(usage["cache_creation"]["ephemeral_5m_input_tokens"], 60)

    def test_eof_tool_and_structured_result_are_flushed(self):
        events = [
            {"type": "session_meta", "payload": {"id": "eof", "cwd": "/tmp/p"}},
            {"type": "response_item", "timestamp": "2026-08-12T01:00:00Z", "payload": {
                "type": "function_call", "name": "read_file", "arguments": '{"path":"a.txt"}',
                "call_id": "call-eof"}},
            {"type": "response_item", "timestamp": "2026-08-12T01:00:01Z", "payload": {
                "type": "function_call_output", "call_id": "call-eof",
                "output": {"text": "abcdefgh", "nested": ["ijkl"]}}},
        ]
        self._write(self.source, events)

        _, _, records = convert_file(self.source)
        self.assertEqual(len(records), 1)
        content = records[0]["message"]["content"]
        self.assertEqual(content[0]["id"], "call-eof")
        self.assertEqual(content[1]["tool_use_id"], "call-eof")
        self.assertGreater(content[1]["result_tokens"], 0)
        self.assertTrue(content[1]["result_estimated"])
        self.assertEqual(records[0]["timestamp"], "2026-08-12T01:00:01Z")

    def test_thread_family_merges_child_copy_and_avoids_target_collision(self):
        root = self.root / "root.jsonl"
        child = self.root / "child.jsonl"
        common_last = {"input_tokens": 10, "cached_input_tokens": 2, "output_tokens": 1}
        common_total = {**common_last, "total_tokens": 11}
        self._write(root, [
            {"type": "session_meta", "payload": {"id": "root", "cwd": "/tmp/p"}},
            self._token("2026-08-12T02:00:00Z", common_last, common_total),
        ])
        self._write(child, [
            {"type": "session_meta", "payload": {
                "id": "child", "parent_thread_id": "root", "agent_role": "worker", "cwd": "/tmp/p"}},
            self._token("2026-08-12T02:00:00Z", common_last, common_total),
            self._token("2026-08-12T02:00:01Z", common_last, {
                **common_total, "input_tokens": 20, "cached_input_tokens": 4, "total_tokens": 22}),
        ])
        self.source.unlink()

        summary = sync_once(self.out, [self.root])
        derived = list(self.out.rglob("*.jsonl"))
        state = json.loads((self.out / ".codex_bridge_state.json").read_text(encoding="utf-8"))

        self.assertEqual(summary["sessions"], 1)
        self.assertEqual(len(derived), 1)
        rows = [json.loads(line) for line in derived[0].read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0]["isSubagent"])
        self.assertEqual(rows[0]["sessionId"], "child")
        self.assertEqual(rows[0]["rootSessionId"], "root")
        targets = {item["target"] for item in state["sources"].values()}
        self.assertEqual(len(targets), 1)
        self.assertGreaterEqual(state["quality"]["duplicate_events"], 1)


if __name__ == "__main__":
    unittest.main()
