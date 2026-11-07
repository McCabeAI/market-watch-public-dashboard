import unittest

from scripts.fx_technical.learning_ext import (
    classify_signal_vs_execution,
    normalize_technical_setup,
)
from scripts.trading.errors import SchemaError
from scripts.trading.learning import empty_scope, normalize_scope


class NormalizeTechnicalSetupTests(unittest.TestCase):
    def test_none_and_empty_return_none(self):
        self.assertIsNone(normalize_technical_setup(None))
        self.assertIsNone(normalize_technical_setup({}))

    def test_valid_trend_continuation_round_trip(self):
        raw = {
            "setup_class": "trend_continuation",
            "instrument": "eurusd",
            "indicators": ["sma50", "macd"],
            "regime_conflict": None,
            "entry": 1.085,
            "invalidation": 1.075,
            "target": 1.105,
            "expected_horizon": "20D",
            "actual_mark": None,
            "outcome": "open",
            "signal_vs_execution": "not_yet_observed",
            "as_of": "2026-11-07",
        }
        normalized = normalize_technical_setup(raw)
        self.assertEqual(normalized["setup_class"], "trend_continuation")
        self.assertEqual(normalized["instrument"], "EURUSD")
        self.assertEqual(normalized["indicators"], ["sma50", "macd"])
        self.assertEqual(normalized["expected_horizon"], "20D")
        self.assertEqual(normalized["entry"], 1.085)

    def test_no_trade_with_entry_raises(self):
        with self.assertRaises(SchemaError):
            normalize_technical_setup(
                {
                    "setup_class": "no_trade",
                    "instrument": "GBPUSD",
                    "indicators": [],
                    "entry": 1.25,
                }
            )

    def test_bad_setup_class_raises(self):
        with self.assertRaises(SchemaError):
            normalize_technical_setup(
                {
                    "setup_class": "scalp",
                    "instrument": "USDJPY",
                    "expected_horizon": "5D",
                    "entry": 150.0,
                    "invalidation": 149.0,
                    "target": 151.0,
                }
            )


class ClassifySignalVsExecutionTests(unittest.TestCase):
    def test_invalidation_weak_signal(self):
        self.assertEqual(
            classify_signal_vs_execution(
                direction="long_base",
                entry=1.10,
                invalidation=1.08,
                actual_mark=1.07,
                outcome="invalidation",
            ),
            "weak_signal",
        )

    def test_invalidation_bad_execution_wrong_side(self):
        self.assertEqual(
            classify_signal_vs_execution(
                direction="long_base",
                entry=1.10,
                invalidation=1.12,
                actual_mark=1.11,
                outcome="invalidation",
            ),
            "bad_execution",
        )

    def test_expired_breached_bad_execution(self):
        self.assertEqual(
            classify_signal_vs_execution(
                direction="long_base",
                entry=1.10,
                invalidation=1.08,
                actual_mark=1.05,
                outcome="expired_20d",
            ),
            "bad_execution",
        )

    def test_expired_not_breached_weak_signal(self):
        self.assertEqual(
            classify_signal_vs_execution(
                direction="long_base",
                entry=1.10,
                invalidation=1.08,
                actual_mark=1.09,
                outcome="expired_20d",
            ),
            "weak_signal",
        )


class NormalizeScopeTechnicalSetupTests(unittest.TestCase):
    def test_without_technical_setup_stays_none(self):
        scope = normalize_scope({"instruments": ["EURUSD"]})
        self.assertIsNone(scope["technical_setup"])
        self.assertEqual(scope["instruments"], ["EURUSD"])

    def test_with_valid_technical_setup_stored(self):
        scope = normalize_scope(
            {
                "technical_setup": {
                    "setup_class": "breakout",
                    "instrument": "AUDUSD",
                    "indicators": [],
                    "entry": 0.65,
                    "invalidation": 0.64,
                    "target": 0.67,
                    "expected_horizon": "5D",
                }
            }
        )
        self.assertIsNotNone(scope["technical_setup"])
        self.assertEqual(scope["technical_setup"]["setup_class"], "breakout")
        self.assertEqual(scope["technical_setup"]["instrument"], "AUDUSD")

    def test_empty_scope_keys_remain(self):
        base = empty_scope()
        scope = normalize_scope({})
        self.assertEqual(set(base.keys()), set(scope.keys()))
        self.assertIn("technical_setup", scope)
        for key in (
            "instruments",
            "instrument_family",
            "asset_class",
            "countries",
            "currencies",
            "setup_type",
            "market_drivers",
            "catalyst_type",
            "failure_mode",
            "decision_dimension",
        ):
            self.assertEqual(scope[key], base[key])


if __name__ == "__main__":
    unittest.main()
