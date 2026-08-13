import http.server
import json
import os
import socket
import sqlite3
import tempfile
import threading
import unittest
import urllib.request
from datetime import datetime, timezone

from token_dashboard.db import init_db
from token_dashboard.server import build_handler


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "t.db")
        self.projects_dir = os.path.join(self.tmp, "projects")
        os.makedirs(self.projects_dir)
        init_db(self.db)
        with sqlite3.connect(self.db) as c:
            c.execute("INSERT INTO messages (uuid, parent_uuid, session_id, project_slug, type, timestamp, model, input_tokens, output_tokens, cache_read_tokens, cache_create_5m_tokens, cache_create_1h_tokens, prompt_text, prompt_chars) VALUES ('u',NULL,'s','p','user','2026-04-19T00:00:00Z',NULL,0,0,0,0,0,'hi',2)")
            c.execute("INSERT INTO messages (uuid, parent_uuid, session_id, project_slug, type, timestamp, model, input_tokens, output_tokens, cache_read_tokens, cache_create_5m_tokens, cache_create_1h_tokens) VALUES ('a','u','s','p','assistant','2026-04-19T00:00:01Z','claude-haiku-4-5',1,1,0,0,0)")
            c.commit()
        self.port = _free_port()
        H = build_handler(self.db, projects_dir=self.projects_dir)
        self.httpd = http.server.HTTPServer(("127.0.0.1", self.port), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()

    def _get(self, path):
        return urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}").read()

    def test_index_html(self):
        body = self._get("/")
        self.assertIn("Token 消耗看板".encode("utf-8"), body)

    def test_health_json(self):
        body = json.loads(self._get("/api/health"))
        self.assertEqual(body, {"ok": True, "product": "Divergence Ledger"})

    def test_overview_json(self):
        body = json.loads(self._get("/api/overview"))
        self.assertIn("sessions", body)
        self.assertEqual(body["sessions"], 1)

    def test_token_duo_json_returns_confirmed_total(self):
        body = json.loads(self._get("/api/token-duo"))
        self.assertEqual(body, {
            "total_tokens": 2,
            "refreshed": False,
            "scan": None,
        })

    def test_token_duo_refresh_scans_new_jsonl_before_returning_total(self):
        project_dir = os.path.join(self.projects_dir, "C--work-sample")
        os.makedirs(project_dir)
        path = os.path.join(project_dir, "s-refresh.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(
                '{"type":"assistant","uuid":"refresh-a","sessionId":"refresh-session",'
                '"timestamp":"2026-04-20T00:00:01Z","isSidechain":false,'
                '"message":{"model":"claude-haiku-4-5","usage":{'
                '"input_tokens":11,"output_tokens":7,"cache_read_input_tokens":13,'
                '"cache_creation":{"ephemeral_5m_input_tokens":17,'
                '"ephemeral_1h_input_tokens":0}}}}\n'
            )

        body = json.loads(self._get("/api/token-duo?refresh=1"))

        self.assertEqual(body["total_tokens"], 50)
        self.assertTrue(body["refreshed"])
        self.assertEqual(body["scan"]["messages"], 1)

    def test_prompts_json(self):
        body = json.loads(self._get("/api/prompts?limit=10"))
        self.assertIsInstance(body, list)

    def test_projects_json(self):
        body = json.loads(self._get("/api/projects"))
        self.assertIsInstance(body, list)
        self.assertEqual(body[0]["project_slug"], "p")

    def test_projects_json_includes_total_tokens_and_cost(self):
        with sqlite3.connect(self.db) as c:
            c.execute("""
                INSERT INTO messages (
                  uuid, parent_uuid, session_id, project_slug, type, timestamp, model,
                  input_tokens, output_tokens, cache_read_tokens,
                  cache_create_5m_tokens, cache_create_1h_tokens
                ) VALUES (
                  'priced-a', NULL, 'priced-session', 'priced', 'assistant',
                  '2026-04-20T03:00:00Z', 'gpt-5.4',
                  1000000, 1000000, 1000000, 1000000, 1000000
                )
            """)
            c.commit()

        rows = json.loads(self._get("/api/projects"))
        by_slug = {r["project_slug"]: r for r in rows}
        self.assertEqual(by_slug["priced"]["total_tokens"], 5000000)
        self.assertAlmostEqual(by_slug["priced"]["cost_usd"], 22.75, places=4)

    def test_overview_long_context_pricing_is_applied_per_request(self):
        with sqlite3.connect(self.db) as c:
            c.executemany("""
                INSERT INTO messages (
                  uuid, session_id, project_slug, type, timestamp, model,
                  input_tokens, output_tokens, cache_read_tokens,
                  cache_create_5m_tokens, cache_create_1h_tokens
                ) VALUES (?, ?, 'long-context', 'assistant', ?, 'gpt-5.6-sol',
                          ?, 100000, 0, 0, 0)
            """, [
                ("standard-1", "standard-1", "2026-04-20T03:00:00Z", 200_000),
                ("standard-2", "standard-2", "2026-04-20T03:01:00Z", 200_000),
                ("long-1", "long-1", "2026-04-20T03:02:00Z", 300_000),
            ])
            c.commit()

        body = json.loads(self._get("/api/overview"))

        # 2 standard calls: 2 * ($1 input + $3 output)
        # 1 long call: $3 input (2x) + $4.50 output (1.5x)
        self.assertAlmostEqual(body["cost_usd"], 15.5, places=4)

    def test_historical_prices_apply_across_cost_endpoints(self):
        with sqlite3.connect(self.db) as c:
            c.executescript("""
                INSERT INTO messages (
                  uuid, session_id, project_slug, type, timestamp, model,
                  input_tokens, output_tokens, cache_read_tokens,
                  cache_create_5m_tokens, cache_create_1h_tokens,
                  prompt_text, prompt_chars
                ) VALUES
                ('price-u-old', 'price-old', 'historical', 'user',
                 '2026-07-30T16:59:58Z', NULL, 0, 0, 0, 0, 0, 'old', 3),
                ('price-a-old', 'price-old', 'historical', 'assistant',
                 '2026-07-30T16:59:59Z', 'gpt-5.6-terra',
                 0, 100000, 100000, 0, 0, NULL, NULL),
                ('price-u-new', 'price-new', 'historical', 'user',
                 '2026-07-30T16:59:59Z', NULL, 0, 0, 0, 0, 0, 'new', 3),
                ('price-a-new', 'price-new', 'historical', 'assistant',
                 '2026-07-30T17:00:00Z', 'gpt-5.6-terra',
                 0, 100000, 100000, 0, 0, NULL, NULL);

                UPDATE messages SET parent_uuid='price-u-old'
                 WHERE uuid='price-a-old';
                UPDATE messages SET parent_uuid='price-u-new'
                 WHERE uuid='price-a-new';
            """)
            c.commit()

        overview = json.loads(self._get(
            "/api/overview?since=2026-07-30T16%3A00%3A00Z"
            "&until=2026-07-30T18%3A00%3A00Z"
        ))
        self.assertAlmostEqual(overview["cost_usd"], 2.745, places=4)

        daily = json.loads(self._get(
            "/api/daily?since=2026-07-30T16%3A00%3A00Z"
            "&until=2026-07-30T18%3A00%3A00Z"
        ))
        self.assertEqual(len(daily), 1)
        self.assertEqual(daily[0]["day"], "2026-07-31")
        self.assertAlmostEqual(daily[0]["usage_cost_usd"], 2.745, places=4)
        self.assertEqual(len(daily[0]["models"]), 1)
        self.assertAlmostEqual(daily[0]["models"][0]["cost_usd"], 2.745, places=4)

        projects = json.loads(self._get(
            "/api/projects?since=2026-07-30T16%3A00%3A00Z"
            "&until=2026-07-30T18%3A00%3A00Z"
        ))
        historical = next(row for row in projects if row["project_slug"] == "historical")
        self.assertAlmostEqual(historical["cost_usd"], 2.745, places=4)

        models = json.loads(self._get(
            "/api/by-model?since=2026-07-30T16%3A00%3A00Z"
            "&until=2026-07-30T18%3A00%3A00Z"
        ))
        terra = [row for row in models if row["model"] == "gpt-5.6-terra"]
        self.assertEqual(len(terra), 1)
        self.assertAlmostEqual(terra[0]["cost_usd"], 2.745, places=4)

        prompts = json.loads(self._get("/api/prompts?limit=100&sort=recent"))
        by_prompt = {row["prompt_text"]: row for row in prompts}
        self.assertAlmostEqual(by_prompt["old"]["estimated_cost_usd"], 1.525, places=4)
        self.assertAlmostEqual(by_prompt["new"]["estimated_cost_usd"], 1.22, places=4)

    def test_daily_json_adds_period_usage_and_cache_read_costs(self):
        with sqlite3.connect(self.db) as c:
            c.execute("""
                INSERT INTO messages (
                  uuid, parent_uuid, session_id, project_slug, type, timestamp, model,
                  input_tokens, output_tokens, cache_read_tokens,
                  cache_create_5m_tokens, cache_create_1h_tokens
                ) VALUES (
                  'cost-a', NULL, 'cost-session', 'p', 'assistant',
                  '2026-04-20T03:00:00Z', 'gpt-5.4',
                  1000000, 1000000, 1000000, 1000000, 0
                )
            """)
            c.commit()

        rows = json.loads(self._get(
            "/api/daily?since=2026-04-20T00%3A00%3A00Z&until=2026-04-21T00%3A00%3A00Z"
        ))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["usage_tokens"], 4000000)
        self.assertAlmostEqual(rows[0]["input_cost_usd"], 2.5, places=4)
        self.assertAlmostEqual(rows[0]["output_cost_usd"], 15.0, places=4)
        self.assertAlmostEqual(rows[0]["cache_create_cost_usd"], 2.5, places=4)
        self.assertAlmostEqual(rows[0]["usage_cost_usd"], 20.25, places=4)
        self.assertAlmostEqual(rows[0]["cache_read_cost_usd"], 0.25, places=4)

    def test_daily_json_adds_model_usage_and_cost_details(self):
        with sqlite3.connect(self.db) as c:
            c.executescript("""
                INSERT INTO messages (
                  uuid, parent_uuid, session_id, project_slug, type, timestamp, model,
                  input_tokens, output_tokens, cache_read_tokens,
                  cache_create_5m_tokens, cache_create_1h_tokens
                ) VALUES
                (
                  'daily-deepseek', NULL, 'deepseek-session', 'p', 'assistant',
                  '2026-04-21T03:00:00Z', 'deepseek-v4-pro',
                  1000000, 1000000, 1000000, 1000000, 0
                ),
                (
                  'daily-claude', NULL, 'claude-session', 'p', 'assistant',
                  '2026-04-21T04:00:00Z', 'claude-haiku-4-5',
                  10, 20, 30, 40, 50
                )
            """)
            c.commit()

        rows = json.loads(self._get(
            "/api/daily?since=2026-04-21T00%3A00%3A00Z&until=2026-04-22T00%3A00%3A00Z"
        ))

        self.assertEqual(len(rows), 1)
        models = {m["model"]: m for m in rows[0]["models"]}
        self.assertEqual(models["deepseek-v4-pro"]["input_tokens"], 1000000)
        self.assertEqual(models["deepseek-v4-pro"]["cache_create_tokens"], 1000000)
        self.assertEqual(models["deepseek-v4-pro"]["cache_read_tokens"], 1000000)
        self.assertEqual(models["deepseek-v4-pro"]["output_tokens"], 1000000)
        self.assertEqual(models["deepseek-v4-pro"]["total_tokens"], 4000000)
        self.assertAlmostEqual(models["deepseek-v4-pro"]["cost_usd"], 1.743625, places=6)
        self.assertEqual(models["claude-haiku-4-5"]["total_tokens"], 150)

    def test_today_hourly_json_adds_model_usage_and_cost_details(self):
        now = datetime.now(timezone.utc).replace(minute=0, second=1, microsecond=0)
        expected_hour = (now.hour + 8) % 24
        timestamp = now.isoformat().replace("+00:00", "Z")
        with sqlite3.connect(self.db) as c:
            c.execute("""
                INSERT INTO messages (
                  uuid, parent_uuid, session_id, project_slug, type, timestamp, model,
                  input_tokens, output_tokens, cache_read_tokens,
                  cache_create_5m_tokens, cache_create_1h_tokens
                ) VALUES (
                  'hourly-deepseek', NULL, 'deepseek-hourly-session', 'p', 'assistant',
                  ?, 'deepseek-v4-pro',
                  1000000, 1000000, 1000000, 1000000, 0
                )
            """, (timestamp,))
            c.commit()

        rows = json.loads(self._get("/api/today-hourly"))
        hour_row = rows[expected_hour]
        models = {m["model"]: m for m in hour_row["models"]}

        self.assertEqual(hour_row["hour_index"], expected_hour)
        self.assertEqual(models["deepseek-v4-pro"]["total_tokens"], 4000000)
        self.assertAlmostEqual(models["deepseek-v4-pro"]["cost_usd"], 1.743625, places=6)

    def test_plan_json(self):
        body = json.loads(self._get("/api/plan"))
        self.assertIn("plan", body)
        self.assertIn("pricing", body)

    def test_head_returns_200_not_501(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/", method="HEAD")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.read(), b"")

    def test_head_api_endpoint(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/overview", method="HEAD")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.read(), b"")


if __name__ == "__main__":
    unittest.main()
