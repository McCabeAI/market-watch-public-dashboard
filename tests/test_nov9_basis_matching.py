"""Nov 9, 2026 basis join regressions.

Fixtures cite evidence_snapshot.json packet_sha256
36b651b69a9e2951d8f7c97819999a9354668967f97c455af200a46c3662fb11.
"""

from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from scripts.rates.futures_basis import build_futures_basis, remember_basis_snapshot
from scripts.rates.ice_euribor import parse_ice_spread_data, same_label_cross_check

EVIDENCE_PACKET_SHA256 = (
    "36b651b69a9e2951d8f7c97819999a9354668967f97c455af200a46c3662fb11"
)
MONDAY_0537_ET = datetime(2026, 11, 9, 10, 37, tzinfo=timezone.utc)  # 05:37 America/New_York


def _nov9_us_blocks() -> tuple[dict, dict]:
    """ZQ official 2026-11-06 vs SR1 delayed 2026-11-09 (evidence Dec26/Z26)."""
    zq = {
        "status": "ok",
        "freshness": "stale",
        "as_of": "2026-11-06",
        "mark_kind": "official_settlement",
        "source_url": "https://www.cmegroup.com/CmeWS/mvc/Settlements/Futures/Settlements/305/FUT?tradeDate=11/06/2026",
        "rows": [
            {
                "code": "ZQZ26",
                "expiry": "2026-12",
                "price": 95.985,
                "implied_rate": 4.015,
                "observation_date": "2026-11-06",
                "trade_date_verified": True,
                "mark_kind": "official_settlement",
                "reference_start": "2026-12-01",
                "reference_end": "2026-12-31",
            }
        ],
    }
    sr1 = {
        "status": "ok",
        "freshness": "fresh",
        "as_of": "2026-11-09",
        "mark_kind": "delayed_quote",
        "source_url": "https://quotes.esignal.com/esignalprod/quote.action?symbol=SR1",
        "rows": [
            {
                "code": "SR1Z26",
                "expiry": "2026-12",
                "price": 95.96,
                "implied_rate": 4.04,
                "observation_date": "2026-11-09",
                "trade_date_verified": False,
                "mark_kind": "delayed_quote",
            }
        ],
    }
    return zq, sr1


class Nov9BasisMatchingTests(unittest.TestCase):
    def test_us_session_mismatch_is_explained_not_current(self) -> None:
        zq, sr1 = _nov9_us_blocks()
        basis = build_futures_basis(
            zq_block=zq,
            sr1_block=sr1,
            euribor_block={"status": "unavailable"},
            esr_block={"status": "unavailable"},
            now=MONDAY_0537_ET,
        )
        us = basis["curves"]["US_EFFR_MINUS_SOFR"]
        dec = next(p for p in us["points"] if p["expiry"] == "2026-12")
        self.assertIsNone(dec["basis_bp"])
        self.assertEqual(dec["status"], "unavailable")
        self.assertFalse(dec["execution_eligible"])
        self.assertEqual(
            dec["reason"],
            "session mismatch ZQ 2026-11-06 vs SR1 2026-11-09; not represented as current",
        )
        self.assertNotIn("current", {p.get("status") for p in us["points"]})

    def test_us_history_returns_latest_matching_historical(self) -> None:
        zq, sr1 = _nov9_us_blocks()
        history = remember_basis_snapshot(
            None,
            {
                "definition_id": "us_effr_minus_sofr_monthly_v1",
                "points": [
                    {
                        "expiry": "2026-12",
                        "observation_date": "2026-11-06",
                        "basis_bp": -1.0,
                        "status": "current",
                        "zq_code": "ZQZ26",
                        "sr1_code": "SR1Z26",
                        "zq_mark_kind": "official_settlement",
                        "sr1_mark_kind": "official_settlement",
                    }
                ],
            },
        )
        basis = build_futures_basis(
            zq_block=zq,
            sr1_block=sr1,
            euribor_block=None,
            esr_block=None,
            history=history,
            now=MONDAY_0537_ET,
        )
        dec = next(p for p in basis["curves"]["US_EFFR_MINUS_SOFR"]["points"] if p["expiry"] == "2026-12")
        lm = dec["latest_matching"]
        self.assertEqual(lm["status"], "latest_matching_historical")
        self.assertEqual(lm["observation_date"], "2026-11-06")
        self.assertEqual(lm["definition_id"], "us_effr_minus_sofr_monthly_v1")
        self.assertEqual(lm["zq_session"], "2026-11-06")
        self.assertEqual(lm["sr1_session"], "2026-11-06")
        self.assertAlmostEqual(lm["basis_bp"], -1.0, places=6)
        self.assertFalse(lm["execution_eligible"])

    def test_eus_friday_official_on_monday_before_drop_is_latest_available(self) -> None:
        eus_rows = [
            {
                "code": "EUSZ26",
                "expiry": "2026-12",
                "basis_bp": 17.0,
                "settlement": 0.17,
                "observation_date": "2026-11-06",
                "mark_kind": "official_settlement",
                "trade_date_verified": True,
                "period_note": "SER-9059 spread economics",
            }
        ]
        curve = build_futures_basis(
            zq_block=None,
            sr1_block=None,
            euribor_block=None,
            esr_block=None,
            eus_block={"rows": eus_rows, "freshness": "stale", "as_of": "2026-11-06"},
            now=MONDAY_0537_ET,
        )["curves"]["EA_CME_EUS"]
        dec = next(p for p in curve["points"] if p["expiry"] == "2026-12")
        self.assertEqual(dec["status"], "latest_available_official")
        self.assertEqual(dec["observation_date"], "2026-11-06")
        self.assertAlmostEqual(dec["basis_bp"], 17.0, places=6)
        self.assertNotEqual(dec["status"], "current")
        self.assertNotEqual(dec["status"], "stale")
        self.assertEqual(curve["status"], "ok")

    def test_ice_direct_last_is_indicative_not_official(self) -> None:
        i_row = {
            "market_strip": "Dec26",
            "code": "IZ26",
            "price": 97.145,
            "quote_time": "11/09/2026 10:42 AM GMT",
            "observation_date": "2026-11-09",
            "mark_kind": "delayed_last",
            "ltd": "2026-12-14",
        }
        er3 = {
            "market_strip": "Dec26",
            "code": "ER3Z26",
            "price": 97.3425,
            "quote_time": "11/09/2026 10:43 AM GMT",
            "observation_date": "2026-11-09",
            "mark_kind": "delayed_last",
        }
        direct = parse_ice_spread_data(
            [{"marketStrip": "Dec26", "lastPrice": 0.1975, "volume": 1, "lastTime": "11/09/2026 10:43 AM GMT"}],
            source_url="https://www.ice.com/example",
            retrieved_at="2026-11-09T10:43:00+00:00",
        )
        cross = same_label_cross_check([i_row], [er3], {"Dec26": {"ltd": "2027-03-16"}}, direct)
        point = cross["points"][0]
        self.assertEqual(point["direct_kind"], "delayed_last")
        self.assertEqual(point["direct_quote_time"], "11/09/2026 10:43 AM GMT")
        self.assertIn("not an official spread settlement", point["reason"])
        self.assertFalse(point["execution_eligible"])

    def test_euribor_estr_proxy_unavailable_when_quote_kinds_differ(self) -> None:
        euribor = {
            "status": "ok",
            "freshness": "fresh",
            "mark_kind": "delayed_last",
            "rows": [
                {
                    "code": "IZ26",
                    "expiry": "2026-12",
                    "price": 97.23,
                    "implied_rate": 2.77,
                    "observation_date": "2026-11-09",
                    "mark_kind": "delayed_last",
                    "trade_date_verified": True,
                    "eligible_for_basis": True,
                    "fixing_date": "2026-12-14",
                    "reference_start": "2026-12-16",
                    "reference_end": "2027-03-16",
                }
            ],
        }
        esr = {
            "status": "ok",
            "freshness": "fresh",
            "mark_kind": "official_settlement",
            "rows": [
                {
                    "code": "ESRZ6",
                    "expiry": "2026-12",
                    "price": 98.0,
                    "implied_rate": 2.0,
                    "observation_date": "2026-11-06",
                    "reference_start": "2026-12-16",
                    "reference_end": "2027-03-17",
                }
            ],
        }
        eu = build_futures_basis(zq_block=None, sr1_block=None, euribor_block=euribor, esr_block=esr, now=date(2026, 11, 9))[
            "curves"
        ]["EA_EURIBOR_MINUS_ESTR"]
        point = next(p for p in eu["points"] if p["expiry"] == "2026-12")
        self.assertIsNone(point["basis_bp"])
        self.assertIn("quote kinds differ", point["reason"])

    def test_five_day_change_unavailable_when_prior_status_differs(self) -> None:
        history = {
            "version": 1,
            "definitions": {
                "us_effr_minus_sofr_monthly_v1": {
                    "2026-11-01": {
                        "2026-12": {
                            "basis_bp": 2.0,
                            "status": "latest_matching_historical",
                            "zq_mark_kind": "official_settlement",
                            "sr1_mark_kind": "delayed_quote",
                        }
                    }
                }
            },
        }
        zq = {
            "freshness": "fresh",
            "mark_kind": "official_settlement",
            "rows": [
                {
                    "code": "ZQZ26",
                    "expiry": "2026-12",
                    "price": 96.0,
                    "implied_rate": 4.0,
                    "observation_date": "2026-11-06",
                    "trade_date_verified": True,
                }
            ],
        }
        sr1 = {
            "freshness": "fresh",
            "mark_kind": "official_settlement",
            "rows": [
                {
                    "code": "SR1Z26",
                    "expiry": "2026-12",
                    "price": 96.05,
                    "implied_rate": 3.95,
                    "observation_date": "2026-11-06",
                    "trade_date_verified": True,
                }
            ],
        }
        change = build_futures_basis(zq_block=zq, sr1_block=sr1, euribor_block=None, esr_block=None, history=history)[
            "curves"
        ]["US_EFFR_MINUS_SOFR"]["points"][0]["changes"]["5d"]
        self.assertEqual(change["status"], "unavailable")
        self.assertIn("does not match", change["reason"])


if __name__ == "__main__":
    unittest.main()
