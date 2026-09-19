#!/usr/bin/env python3
from __future__ import annotations

import json
import unittest

from scripts.policy_path_data import (
    build_tradable_rate_curves,
    parse_asx_cash_futures_html,
    parse_boc_corra_html,
    parse_boc_corra_json,
    parse_cme_sofr_bulletin_text,
    parse_cme_sr3_bulletin_text,
    parse_cme_sr3_html,
    parse_cme_sr3_settlements_json,
    parse_cme_sofr_html,
    parse_cme_sofr_settlements_json,
    parse_esignal_sofr_html,
    parse_mx_expectations_html,
    parse_nyfed_sofr_json,
    parse_rba_f1_csv,
    validate_tradable_rate_curves,
)


class PolicyPathParserTests(unittest.TestCase):
    def test_boc_corra_json(self):
        payload = '{"observations":[{"d":"2026-09-17","AVG.INTWO":{"v":"2.2900"}}]}'
        self.assertEqual(
            parse_boc_corra_json(payload),
            {"rate": 2.29, "as_of": "2026-09-17"},
        )

    def test_boc_corra(self):
        html = """
        <table>
          <tr><th></th><th>2026-09-16</th><th>2026-09-17</th></tr>
          <tr><td>Canadian Overnight Repo Rate Average (CORRA) (%)</td><td>2.2900</td><td>2.2900</td></tr>
        </table>
        """
        self.assertEqual(parse_boc_corra_html(html)["rate"], 2.29)

    def test_mx_corra_futures(self):
        html = """
        <table>
          <tr><th>COA Contract</th><th>Price</th><th>Implied CORRA Rate</th></tr>
          <tr><td>October 2026 (COAV26)</td><td>97.695</td><td>2.305%</td></tr>
          <tr><td>November 2026 (COAX26)</td><td>97.570</td><td>2.430%</td></tr>
        </table>
        <table>
          <tr><th>CRA Contract</th><th>Price</th><th>Implied CORRA Rate</th></tr>
          <tr><td>December 2026 (CRAZ26)</td><td>97.255</td><td>2.745%</td></tr>
          <tr><td>December 2027 (CRAZ27)</td><td>96.480</td><td>3.520%</td></tr>
        </table>
        """
        result = parse_mx_expectations_html(html, benchmark=2.29)
        self.assertEqual(result["1m"][0]["implied_rate"], 2.305)
        self.assertEqual(result["3m"][-1]["change_from_overnight_bps"], 123.0)

    def test_nyfed_sofr(self):
        payload = '{"refRates":[{"type":"SOFR","effectiveDate":"2026-09-18","percentRate":3.75}]}'
        result = parse_nyfed_sofr_json(payload)
        self.assertEqual(result["rate"], 3.75)
        self.assertEqual(result["as_of"], "2026-09-18")

    def test_cme_one_month_sofr_settlement_api(self):
        payload = (
            '{"settlements":['
            '{"month":"SEP 26","settle":"96.2475","volume":"50,352","openInterest":"290,746"},'
            '{"month":"DEC 26","settle":"95.8100","volume":"21,399","openInterest":"150,095"}'
            ']}'
        )
        rows = parse_cme_sofr_settlements_json(payload, benchmark=3.75)
        self.assertEqual(rows[0]["expiry"], "2026-09")
        self.assertEqual(rows[1]["implied_rate"], 4.19)
        self.assertEqual(rows[1]["change_from_overnight_bps"], 44.0)
        self.assertEqual(rows[0]["open_interest"], 290746.0)

    def test_cme_daily_bulletin_sr1(self):
        text = """
SR1 FUT
SEP26 96.250 96.2525 96.2475 96.250 ( 3.75) + 0.0025 ---- 40670 289321 + 6127 97.060 96.145
OCT26 96.090 96.095 96.090 96.090 ( 3.91) UNCH ---- 8479 286856 - 1475 97.060 96.060
DEC26 95.820 95.820 95.795 95.800 ( 4.20) - 0.0100 ---- 9505 153858 + 423 97.025 95.800
TOTAL SR1 FUT 0 127818 1302349 + 11967
"""
        rows = parse_cme_sofr_bulletin_text(text, benchmark=3.85)
        self.assertEqual(rows[0]["expiry"], "2026-09")
        self.assertEqual(rows[1]["implied_rate"], 3.91)
        self.assertEqual(rows[2]["change_from_overnight_bps"], 35.0)

    def test_cme_sr3_quote_page(self):
        html = """
        <table>
          <tr><th>Month</th><th>Options</th><th>Chart</th><th>Last</th><th>Change</th><th>PriorSettle</th><th>Open</th><th>High</th><th>Low</th><th>Volume</th><th>Updated</th></tr>
          <tr><td>DEC 2026<br>SR3Z6</td><td>Opt</td><td>Chart</td><td>95.68</td><td>-0.01</td><td>-</td><td>95.70</td><td>95.705</td><td>95.675</td><td>353,812</td><td>18 Sep 2026</td></tr>
          <tr><td>MAR 2027<br>SR3H7</td><td>Opt</td><td>Chart</td><td>95.42</td><td>-0.03</td><td>-</td><td>95.47</td><td>95.47</td><td>95.41</td><td>371,935</td><td>18 Sep 2026</td></tr>
          <tr><td>APR 2027<br>SR3J7</td><td>Opt</td><td>Chart</td><td>95.30</td><td>-0.02</td><td>-</td><td>95.31</td><td>95.32</td><td>95.29</td><td>10</td><td>18 Sep 2026</td></tr>
        </table>
        """
        rows = parse_cme_sr3_html(html, benchmark=3.85)
        self.assertEqual([r["code"] for r in rows], ["SR3Z6", "SR3H7"])
        self.assertEqual(rows[0]["implied_rate"], 4.32)
        self.assertEqual(rows[1]["volume"], 371935.0)

    def test_cme_sr3_settlement_api(self):
        payload = json.dumps({
            "settlements": [
                {"month": "DEC 26", "settle": "95.7000", "volume": "353812", "openInterest": "1800000"},
                {"month": "MAR 27", "settle": "95.4700", "volume": "371935", "openInterest": "1700000"},
                {"month": "APR 27", "settle": "95.3000", "volume": "10", "openInterest": "100"},
            ]
        })
        rows = parse_cme_sr3_settlements_json(payload, benchmark=3.85)
        self.assertEqual([r["code"] for r in rows], ["SR3Z6", "SR3H7"])
        self.assertEqual(rows[0]["implied_rate"], 4.3)
        self.assertEqual(rows[1]["open_interest"], 1700000.0)

    def test_cme_daily_bulletin_sr3(self):
        text = """
SR3 FUT
DEC26 96.780 96.790 96.770 96.780 ( 3.22) + 0.0050 ---- 250000 1800000 + 1000 97.100 95.900
MAR27 96.650 96.660 96.640 96.650 ( 3.35) UNCH ---- 210000 1700000 - 500 97.000 95.800
TOTAL SR3 FUT 0 460000 3500000 + 500
"""
        rows = parse_cme_sr3_bulletin_text(text, benchmark=3.85)
        self.assertEqual(rows[0]["code"], "SR3Z6")
        self.assertEqual(rows[0]["expiry"], "2026-12")
        self.assertEqual(rows[0]["implied_rate"], 3.22)
        self.assertEqual(rows[1]["change_from_overnight_bps"], -50.0)

    def test_tradable_rate_curve_selection(self):
        policy = {
            "countries": {
                "US": {"status": "ok", "benchmark": {"name": "SOFR", "rate": 3.85}, "contracts_3m": [{"expiry": "2026-12", "code": "SR3Z6", "implied_rate": 3.22}]},
                "CA": {"status": "ok", "benchmark": {"name": "CORRA", "rate": 2.29}, "contracts_3m": [{"expiry": "2026-12", "code": "CRAZ26", "implied_rate": 2.78}]},
                "AU": {"status": "ok", "benchmark": {"name": "AONIA", "rate": 4.35}, "contracts_1m": [{"expiry": "2026-10", "code": None, "implied_rate": 4.40}]},
            },
            "sources": {
                "US_policy": {"tradable_curve_url": "https://example.test/sr3"},
                "CA_policy": {"path_url": "https://example.test/cra"},
                "AU_policy": {"path_url": "https://example.test/ib"},
            },
        }
        curves = build_tradable_rate_curves(policy)
        validate_tradable_rate_curves(curves)
        self.assertEqual(curves["status"], "ok")
        self.assertEqual(curves["curves"]["SOFR"]["product_code"], "SR3")
        self.assertEqual(curves["curves"]["CORRA"]["product_code"], "CRA")
        self.assertEqual(curves["curves"]["AONIA"]["product_code"], "IB")

    def test_esignal_sofr_chain(self):
        html = """
        <table>
          <tr><th>Contract</th><th>Month</th><th>Last</th><th>Change</th></tr>
          <tr><td>ICE ONE MONTH SOFR INDEX FUTURE - ICUS (SR1 V26)</td><td>Oct'26</td><td>96.090 s</td><td>0.00</td></tr>
          <tr><td>ICE ONE MONTH SOFR INDEX FUTURE - ICUS (SR1 Z26)</td><td>Dec'26</td><td>95.800 s</td><td>-0.01</td></tr>
          <tr><td>ICE ONE MONTH SOFR INDEX FUTURE - ICUS (SR1 H27)</td><td>Mar'27</td><td>95.580 s</td><td>-0.02</td></tr>
        </table>
        """
        rows = parse_esignal_sofr_html(html, benchmark=3.85)
        self.assertEqual(rows[0]["expiry"], "2026-10")
        self.assertEqual(rows[1]["implied_rate"], 4.2)
        self.assertEqual(rows[2]["change_from_overnight_bps"], 57.0)

    def test_cme_one_month_sofr(self):
        html = """
        <table>
          <tr><th>Month</th><th>Options</th><th>Chart</th><th>Last</th><th>Change</th><th>Prior Settle</th><th>Open</th><th>High</th><th>Low</th><th>Volume</th></tr>
          <tr><td>SEP 2026 SR1U6</td><td></td><td></td><td>96.2525</td><td>0</td><td>96.25</td><td>96.2</td><td>96.3</td><td>96.2</td><td>40670</td></tr>
          <tr><td>DEC 2026 SR1Z6</td><td></td><td></td><td>95.81</td><td>0</td><td>95.80</td><td>95.8</td><td>95.9</td><td>95.7</td><td>9505</td></tr>
        </table>
        """
        rows = parse_cme_sofr_html(html, benchmark=3.75)
        self.assertEqual(rows[0]["code"], "SR1U6")
        self.assertEqual(rows[1]["implied_rate"], 4.19)
        self.assertEqual(rows[1]["change_from_overnight_bps"], 44.0)

    def test_rba_f1_aonia_ois_and_bill_basis(self):
        csv_text = """F1 INTEREST RATES AND YIELDS – MONEY MARKET
Title,Cash Rate Target,Interbank Overnight Cash Rate,EOD 1-month BABs/NCDs,EOD 3-month BABs/NCDs,EOD 6-month BABs/NCDs,1-month OIS,3-month OIS,6-month OIS
Description,target,aonia,b1,b3,b6,o1,o3,o6
Series ID,FIRMMCRTD,FIRMMCRID,FIRMMBAB30D,FIRMMBAB90D,FIRMMBAB180D,FIRMMOIS1D,FIRMMOIS3D,FIRMMOIS6D
17-Sep-2026,4.35,4.35,4.41,4.68,5.07,4.40,4.62,4.96
"""
        result = parse_rba_f1_csv(csv_text)
        self.assertEqual(result["benchmark"]["rate"], 4.35)
        self.assertEqual(result["ois"]["3m"]["rate"], 4.62)
        self.assertAlmostEqual(result["bank_bill_minus_ois"]["3m"]["bank_bill_minus_ois_bps"], 6.0)

    def test_rba_stale_ois_does_not_create_fake_current_basis(self):
        csv_text = """F1 INTEREST RATES AND YIELDS – MONEY MARKET
Title,Cash Rate Target,Interbank Overnight Cash Rate,EOD 1-month BABs/NCDs,EOD 3-month BABs/NCDs,EOD 6-month BABs/NCDs,1-month OIS,3-month OIS,6-month OIS
Description,target,aonia,b1,b3,b6,o1,o3,o6
Series ID,FIRMMCRTD,FIRMMCRID,FIRMMBAB30D,FIRMMBAB90D,FIRMMBAB180D,FIRMMOIS1D,FIRMMOIS3D,FIRMMOIS6D
01-Dec-2022,2.85,2.85,3.10,3.20,3.30,2.97,3.04,3.22
17-Sep-2026,4.35,4.35,4.41,4.68,5.07,,,
"""
        result = parse_rba_f1_csv(csv_text)
        basis = result["bank_bill_minus_ois"]["3m"]
        self.assertEqual(basis["status"], "unavailable_cross_vintage")
        self.assertIsNone(basis["bank_bill_minus_ois_bps"])
        self.assertEqual(basis["ois_as_of"], "01-Dec-2022")
        self.assertEqual(basis["bank_bill_as_of"], "17-Sep-2026")

    def test_asx_cash_futures(self):
        html = """
        <table>
          <tr><td>IB - 30 Day Interbank Cash Rate (RBA Interbank Overnight Cash)</td></tr>
          <tr><th>Expiry</th><th>Open</th><th>High</th><th>Low</th><th>Last</th><th>Sett</th><th>Sett Chg</th><th>OI</th><th>OI Chg</th><th>Volume</th></tr>
          <tr><td>OCT 2026</td><td>95.50</td><td>95.70</td><td>95.40</td><td>95.60</td><td>95.60</td><td>.01</td><td>12000</td><td>10</td><td>500</td></tr>
          <tr><td>NOV 2026</td><td>95.40</td><td>95.60</td><td>95.30</td><td>95.50</td><td>95.50</td><td>.01</td><td>9000</td><td>5</td><td>350</td></tr>
        </table>
        """
        rows = parse_asx_cash_futures_html(html, benchmark=4.35)
        self.assertEqual(rows[0]["implied_rate"], 4.4)
        self.assertEqual(rows[1]["change_from_overnight_bps"], 15.0)


if __name__ == "__main__":
    unittest.main()
