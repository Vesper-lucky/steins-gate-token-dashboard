import os
import sqlite3
import tempfile
import json
from pathlib import Path
import unittest
from token_dashboard.db import init_db, connect, data_quality


class InitDbTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "test.db")

    def test_init_creates_expected_tables(self):
        init_db(self.db_path)
        with sqlite3.connect(self.db_path) as c:
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        expected = {"files", "messages", "tool_calls", "plan", "dismissed_tips"}
        self.assertTrue(expected.issubset(tables), f"Missing: {expected - tables}")

    def test_init_is_idempotent(self):
        init_db(self.db_path)
        init_db(self.db_path)

    def test_connect_returns_row_factory(self):
        init_db(self.db_path)
        with connect(self.db_path) as c:
            r = c.execute("SELECT 1 AS one").fetchone()
        self.assertEqual(r["one"], 1)

    def test_source_tracking_migration_clears_derived_cache(self):
        with sqlite3.connect(self.db_path) as c:
            c.executescript("""
            CREATE TABLE files (
              path TEXT PRIMARY KEY, mtime REAL NOT NULL,
              bytes_read INTEGER NOT NULL, scanned_at REAL NOT NULL
            );
            CREATE TABLE messages (
              uuid TEXT PRIMARY KEY, session_id TEXT NOT NULL,
              project_slug TEXT NOT NULL, type TEXT NOT NULL,
              timestamp TEXT NOT NULL, model TEXT, message_id TEXT
            );
            CREATE TABLE tool_calls (
              id INTEGER PRIMARY KEY AUTOINCREMENT, message_uuid TEXT NOT NULL,
              session_id TEXT NOT NULL, tool_name TEXT NOT NULL, target TEXT
            );
            INSERT INTO files VALUES ('old.jsonl', 1, 10, 1);
            INSERT INTO messages VALUES ('old', 's', 'p', 'assistant', '2026-01-01T00:00:00Z', 'gpt-5.5', 'm');
            INSERT INTO tool_calls (message_uuid, session_id, tool_name, target)
            VALUES ('old', 's', 'Read', 'old.py');
            """)

        init_db(self.db_path)

        with sqlite3.connect(self.db_path) as c:
            file_cols = {row[1] for row in c.execute("PRAGMA table_info(files)")}
            message_cols = {row[1] for row in c.execute("PRAGMA table_info(messages)")}
            self.assertIn("content_sig", file_cols)
            self.assertIn("source_path", message_cols)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM files").fetchone()[0], 0)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM tool_calls").fetchone()[0], 0)

    def test_historical_damaged_lines_are_not_reported_as_read_failures(self):
        init_db(self.db_path)
        bridge = Path(self.tmp) / "bridge"
        bridge.mkdir()
        (bridge / ".codex_bridge_state.json").write_text(json.dumps({
            "quality": {"accepted_events": 0, "damaged_lines": 2, "read_errors": 0}
        }), encoding="utf-8")

        report = data_quality(self.db_path, [bridge])

        self.assertEqual(report["warnings"], [])
        self.assertEqual(report["notices"], ["bridge 已跳过 2 条无法解析的历史日志行"])

    def test_bridge_read_errors_remain_warnings(self):
        init_db(self.db_path)
        bridge = Path(self.tmp) / "bridge"
        bridge.mkdir()
        (bridge / ".codex_bridge_state.json").write_text(json.dumps({
            "quality": {"accepted_events": 0, "damaged_lines": 0, "read_errors": 1}
        }), encoding="utf-8")

        report = data_quality(self.db_path, [bridge])

        self.assertEqual(report["warnings"], ["bridge 读取源日志失败"])
        self.assertEqual(report["notices"], [])


if __name__ == "__main__":
    unittest.main()
