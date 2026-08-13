import os
import shutil
import sqlite3
import tempfile
import unittest

from token_dashboard.db import init_db, model_breakdown, overview_totals
from token_dashboard.scanner import scan_dir, scan_roots

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


class WalkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "t.db")
        self.proj_root = os.path.join(self.tmp, "projects")
        proj_dir = os.path.join(self.proj_root, "C--work-sample")
        os.makedirs(proj_dir)
        shutil.copy(
            os.path.join(FIXTURE_DIR, "sample_session.jsonl"),
            os.path.join(proj_dir, "s1.jsonl"),
        )
        init_db(self.db)

    def test_scan_writes_messages_and_tools(self):
        n = scan_dir(self.proj_root, self.db)
        self.assertEqual(n["messages"], 3)
        self.assertEqual(n["tools"], 2)  # 1 tool_use + 1 tool_result
        with sqlite3.connect(self.db) as c:
            row = c.execute("SELECT project_slug FROM messages WHERE uuid='u1'").fetchone()
        self.assertEqual(row[0], "C--work-sample")

    def test_rescan_skips_unchanged_files(self):
        n1 = scan_dir(self.proj_root, self.db)
        n2 = scan_dir(self.proj_root, self.db)
        self.assertEqual(n1["messages"], 3)
        self.assertEqual(n2["messages"], 0)

    def test_rescan_picks_up_appended_lines(self):
        scan_dir(self.proj_root, self.db)
        path = os.path.join(self.proj_root, "C--work-sample", "s1.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            f.write('{"type":"assistant","uuid":"a2","sessionId":"s1","timestamp":"2026-04-10T00:00:03Z","isSidechain":false,"message":{"model":"claude-haiku-4-5","usage":{"input_tokens":1,"output_tokens":1}}}\n')
        n2 = scan_dir(self.proj_root, self.db)
        self.assertEqual(n2["messages"], 1)

    def test_scan_roots_combines_wsl_and_windows_sources(self):
        win_root = os.path.join(self.tmp, "windows-projects")
        os.makedirs(os.path.join(win_root, "D--win-deepseek"))
        with open(os.path.join(win_root, "D--win-deepseek", "s2.jsonl"), "w", encoding="utf-8") as f:
            f.write(
                '{"type":"assistant","uuid":"deepseek-a","sessionId":"s2",'
                '"timestamp":"2026-04-10T00:00:04Z","isSidechain":false,'
                '"message":{"model":"deepseek-v4-pro","usage":{'
                '"input_tokens":7,"output_tokens":11}}}\n'
            )

        n = scan_roots([self.proj_root, win_root], self.db)

        self.assertEqual(n["roots"], 2)
        self.assertEqual(n["messages"], 4)
        totals = overview_totals(self.db)
        self.assertEqual(totals["sessions"], 2)
        models = {r["model"]: r for r in model_breakdown(self.db)}
        self.assertIn("deepseek-v4-pro", models)
        self.assertEqual(models["deepseek-v4-pro"]["input_tokens"], 7)
        self.assertEqual(models["deepseek-v4-pro"]["output_tokens"], 11)


if __name__ == "__main__":
    unittest.main()
