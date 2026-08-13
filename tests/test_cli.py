import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from cli import _today_range

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAUNCHER = os.path.expanduser("~/.local/bin/divledger")


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.proj = os.path.join(self.tmp, "projects")
        os.makedirs(os.path.join(self.proj, "demo"))
        with open(os.path.join(self.proj, "demo", "s.jsonl"), "w", encoding="utf-8") as f:
            f.write('{"type":"user","uuid":"u1","sessionId":"s1","timestamp":"2026-04-19T00:00:00Z","isSidechain":false,"message":{"role":"user","content":"hi"}}\n')
            f.write('{"type":"assistant","uuid":"a1","parentUuid":"u1","sessionId":"s1","timestamp":"2026-04-19T00:00:01Z","isSidechain":false,"message":{"model":"claude-haiku-4-5","usage":{"input_tokens":1,"output_tokens":1}}}\n')
        self.db = os.path.join(self.tmp, "t.db")

    def _run(self, *args):
        env = {**os.environ, "TOKEN_DASHBOARD_DB": self.db}
        return subprocess.run(
            [sys.executable, "cli.py", *args],
            cwd=ROOT, env=env, capture_output=True, text=True,
        )

    def test_scan_uses_multiple_project_roots_from_env(self):
        win_proj = os.path.join(self.tmp, "windows-projects")
        os.makedirs(os.path.join(win_proj, "D--win-deepseek"))
        with open(os.path.join(win_proj, "D--win-deepseek", "s2.jsonl"), "w", encoding="utf-8") as f:
            f.write(
                '{"type":"assistant","uuid":"deepseek-a","sessionId":"s2",'
                '"timestamp":"2026-04-19T00:00:02Z","isSidechain":false,'
                '"message":{"model":"deepseek-v4-pro","usage":{'
                '"input_tokens":3,"output_tokens":4}}}\n'
            )
        env = {
            **os.environ,
            "TOKEN_DASHBOARD_DB": self.db,
            "TOKDASH_PROJECTS_DIRS": os.pathsep.join([self.proj, win_proj]),
        }
        r = subprocess.run(
            [sys.executable, "cli.py", "scan"],
            cwd=ROOT, env=env, capture_output=True, text=True,
        )

        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("scanned 2 files", r.stdout)
        self.assertIn("3 messages", r.stdout)

    def test_scan_then_today(self):
        r1 = self._run("scan", "--projects-dir", self.proj)
        self.assertEqual(r1.returncode, 0, r1.stderr)
        self.assertIn("scanned", r1.stdout)
        r2 = self._run("today")
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertIn("Divergence Ledger", r2.stdout)

    def test_today_range_uses_beijing_day_boundaries(self):
        beijing = timezone(timedelta(hours=8))
        since, until = _today_range(datetime(2026, 5, 26, 12, 0, tzinfo=beijing))
        self.assertEqual(since, "2026-05-25T16:00:00Z")
        self.assertEqual(until, "2026-05-26T16:00:00Z")

    def test_stats(self):
        self._run("scan", "--projects-dir", self.proj)
        r = self._run("stats")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("all time", r.stdout)

    def test_tips_runs_without_data(self):
        r = self._run("tips")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no suggestions", r.stdout)

    def test_local_health_probe_bypasses_proxy(self):
        with open(LAUNCHER, encoding="utf-8") as f:
            launcher = f.read()
        self.assertIn("curl -fsS --noproxy '*' --max-time 1", launcher)


if __name__ == "__main__":
    unittest.main()
