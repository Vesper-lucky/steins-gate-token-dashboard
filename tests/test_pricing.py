import os
import unittest

from token_dashboard.pricing import load_pricing, cost_for, format_for_user

PRICING = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "pricing.json"))


class CostTests(unittest.TestCase):
    def setUp(self):
        self.p = load_pricing(PRICING)

    def _u(self, **kw):
        base = {
            "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
            "cache_create_5m_tokens": 0, "cache_create_1h_tokens": 0,
        }
        base.update(kw)
        return base

    def test_gpt_5_6_model_prices(self):
        expected = {
            "gpt-5.6-sol": (5.00, 30.00),
            "gpt-5.6-terra": (2.00, 12.00),
            "gpt-5.6-luna": (0.20, 1.20),
        }
        for model, (input_price, output_price) in expected.items():
            with self.subTest(model=model):
                c = cost_for(
                    model,
                    self._u(input_tokens=100_000, output_tokens=100_000),
                    self.p,
                )
                self.assertAlmostEqual(c["breakdown"]["input"], input_price / 10, places=6)
                self.assertAlmostEqual(c["breakdown"]["output"], output_price / 10, places=6)
                self.assertFalse(c["estimated"])

    def test_terra_and_luna_prices_switch_at_exact_cutoff(self):
        expected = {
            "gpt-5.6-terra": {
                "old": (2.50, 15.00, 0.25, 3.125, 3.125),
                "new": (2.00, 12.00, 0.20, 2.50, 2.50),
            },
            "gpt-5.6-luna": {
                "old": (1.00, 6.00, 0.10, 1.25, 1.25),
                "new": (0.20, 1.20, 0.02, 0.25, 0.25),
            },
        }
        usage = self._u(
            input_tokens=10_000,
            output_tokens=10_000,
            cache_read_tokens=10_000,
            cache_create_5m_tokens=10_000,
            cache_create_1h_tokens=10_000,
        )
        keys = ("input", "output", "cache_read", "cache_create_5m", "cache_create_1h")
        for model, prices in expected.items():
            with self.subTest(model=model, period="old"):
                old = cost_for(model, usage, self.p, at="2026-07-30T16:59:59Z")
                self.assertEqual(
                    old["breakdown"],
                    {key: price / 100 for key, price in zip(keys, prices["old"])},
                )
            with self.subTest(model=model, period="new"):
                new = cost_for(model, usage, self.p, at="2026-07-30T17:00:00Z")
                self.assertEqual(
                    new["breakdown"],
                    {key: price / 100 for key, price in zip(keys, prices["new"])},
                )

    def test_missing_or_invalid_timestamp_uses_current_prices(self):
        usage = self._u(input_tokens=100_000)
        self.assertEqual(cost_for("gpt-5.6-terra", usage, self.p)["usd"], 0.2)
        self.assertEqual(
            cost_for("gpt-5.6-terra", usage, self.p, at="not-a-time")["usd"],
            0.2,
        )

    def test_gpt_5_6_cache_write_and_read_prices(self):
        c = cost_for(
            "gpt-5.6-sol",
            self._u(cache_read_tokens=100_000, cache_create_5m_tokens=100_000),
            self.p,
        )
        self.assertAlmostEqual(c["breakdown"]["cache_read"], 0.05, places=6)
        self.assertAlmostEqual(c["breakdown"]["cache_create_5m"], 0.625, places=6)

    def test_gpt_5_4_all_token_bucket_prices(self):
        c = cost_for(
            "gpt-5.4",
            self._u(
                input_tokens=1_000_000,
                output_tokens=1_000_000,
                cache_read_tokens=1_000_000,
                cache_create_5m_tokens=1_000_000,
                cache_create_1h_tokens=1_000_000,
            ),
            self.p,
        )
        self.assertEqual(c["breakdown"], {
            "input": 2.5,
            "output": 15.0,
            "cache_read": 0.25,
            "cache_create_5m": 2.5,
            "cache_create_1h": 2.5,
        })
        self.assertEqual(c["usd"], 22.75)

    def test_gpt_5_6_long_context_multipliers_stack_with_cache(self):
        c = cost_for(
            "gpt-5.6-sol",
            self._u(
                input_tokens=100_000,
                output_tokens=100_000,
                cache_read_tokens=100_000,
                cache_create_5m_tokens=100_000,
            ),
            self.p,
        )
        self.assertAlmostEqual(c["breakdown"]["input"], 1.0, places=6)
        self.assertAlmostEqual(c["breakdown"]["output"], 4.5, places=6)
        self.assertAlmostEqual(c["breakdown"]["cache_read"], 0.1, places=6)
        self.assertAlmostEqual(c["breakdown"]["cache_create_5m"], 1.25, places=6)

    def test_gpt_5_6_exactly_272k_input_uses_standard_prices(self):
        c = cost_for("gpt-5.6-sol", self._u(input_tokens=272_000), self.p)
        self.assertAlmostEqual(c["usd"], 1.36, places=6)

    def test_claude_models_are_no_longer_priced(self):
        c = cost_for("claude-opus-4-7", self._u(input_tokens=1_000_000), self.p)
        self.assertIsNone(c["usd"])
        self.assertTrue(c["estimated"])

    def test_unknown_unparseable_returns_none(self):
        c = cost_for("custom-local-model", self._u(input_tokens=9999), self.p)
        self.assertIsNone(c["usd"])

    def test_cache_read_cheaper_than_input(self):
        c_in = cost_for("gpt-5.6-sol", self._u(input_tokens=100_000), self.p)
        c_cr = cost_for("gpt-5.6-sol", self._u(cache_read_tokens=100_000), self.p)
        self.assertLess(c_cr["usd"], c_in["usd"])

    def test_deepseek_v4_pro_usd_pricing(self):
        c = cost_for(
            "deepseek-v4-pro",
            self._u(
                input_tokens=1_000_000,
                cache_read_tokens=1_000_000,
                output_tokens=1_000_000,
            ),
            self.p,
        )
        self.assertAlmostEqual(c["breakdown"]["input"], 0.435, places=6)
        self.assertAlmostEqual(c["breakdown"]["cache_read"], 0.003625, places=6)
        self.assertAlmostEqual(c["breakdown"]["output"], 0.87, places=6)
        self.assertAlmostEqual(c["usd"], 1.308625, places=6)
        self.assertFalse(c["estimated"])

    def test_deepseek_chat_alias_uses_v4_flash_pricing(self):
        c = cost_for(
            "deepseek-chat",
            self._u(input_tokens=1_000_000, output_tokens=1_000_000),
            self.p,
        )
        self.assertAlmostEqual(c["breakdown"]["input"], 0.14, places=6)
        self.assertAlmostEqual(c["breakdown"]["output"], 0.28, places=6)


class PlanFormatTests(unittest.TestCase):
    def setUp(self):
        self.p = load_pricing(PRICING)

    def test_api_plan_returns_raw(self):
        out = format_for_user(12.34, "api", self.p)
        self.assertEqual(out["display_usd"], 12.34)
        self.assertIsNone(out["subscription_usd"])

    def test_pro_plan_returns_subscription_subtitle(self):
        out = format_for_user(12.34, "pro", self.p)
        self.assertEqual(out["subscription_usd"], 20)
        self.assertIn("Pro", out["subtitle"])


if __name__ == "__main__":
    unittest.main()
