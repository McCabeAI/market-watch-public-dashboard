import unittest
from datetime import date

from scripts.canada_housing_data import (
    CanadaHousingError,
    _statcan_rows,
    parse_cmhc_starts,
    parse_statcan_mortgage_dsr,
    parse_statcan_nhpi,
    parse_statcan_permits,
    validate_canada_housing,
)
from scripts.us_housing_data import (
    FEEDS as US_FEEDS,
    parse_fred_csv,
    validate_us_housing,
)


class USHousingTests(unittest.TestCase):
    def test_fred_parser_mixed_frequency(self):
        text = "\n".join([
            "observation_date,HPIPONM226S,HOUST,MORTGAGE30US,MDSP",
            "2025-01-01,400,1400,,5.5",
            "2025-01-02,,,6.5,",
            "2026-01-01,420,1450,,5.8",
            "2026-09-17,,,6.95,",
        ])
        parsed = parse_fred_csv(text)
        self.assertEqual(parsed["HPIPONM226S"][-1], (date(2026, 1, 1), 420.0))
        self.assertEqual(parsed["MORTGAGE30US"][-1], (date(2026, 9, 17), 6.95))

    def test_us_validator(self):
        feeds = {
            name: {"status": "ok", "url": "https://example.test", "as_of": "2026-09-01"}
            for name in US_FEEDS
        }
        validate_us_housing({"country": "US", "status": "ok", "feeds": feeds})


class CanadaHousingTests(unittest.TestCase):
    def test_statcan_nhpi_selector(self):
        rows = [
            {
                "REF_DATE": "2026-07", "GEO": "Canada",
                "New housing price indexes": "Total (house and land)",
                "UOM": "Index, 201612=100", "VALUE": "120.0", "VECTOR": "v1",
            },
            {
                "REF_DATE": "2026-08", "GEO": "Canada",
                "New housing price indexes": "Total (house and land)",
                "UOM": "Index, 201612=100", "VALUE": "119.9", "VECTOR": "v1",
            },
        ]
        parsed = parse_statcan_nhpi(rows)
        self.assertEqual(parsed["reference_period"], "2026-08")
        self.assertEqual(parsed["metrics"]["new_housing_price_index"]["value"], 119.9)

    def test_statcan_permits_selector(self):
        base = {
            "REF_DATE": "2026-07", "GEO": "Canada",
            "Type of work": "Types of work, total",
            "Variables": "Value of permits",
            "Seasonal adjustment, value type": "Seasonally adjusted, current",
            "UOM": "Dollars", "SCALAR_FACTOR": "thousands",
        }
        rows = []
        for building, value in [
            ("Total residential", "7211000"),
            ("Single dwelling building total", "2543000"),
            ("Multiple dwelling building total", "4667000"),
        ]:
            row = dict(base)
            row["Type of building"] = building
            row["VALUE"] = value
            rows.append(row)
        parsed = parse_statcan_permits(rows)
        self.assertEqual(parsed["metrics"]["total_residential_permit_value"]["value"], 7211000.0)
        self.assertEqual(parsed["metrics"]["multiple_dwelling_permit_value"]["scalar_factor"], "thousands")

    def test_statcan_mortgage_dsr_vector(self):
        rows = [
            {
                "REF_DATE": "2026Q1", "GEO": "Canada",
                "Seasonal adjustment": "Seasonally adjusted at annual rates",
                "Debt service indicators": "Mortgage debt service ratio",
                "UOM": "Percent", "VECTOR": "v99451480", "VALUE": "8.1",
            },
            {
                "REF_DATE": "2026Q2", "GEO": "Canada",
                "Seasonal adjustment": "Seasonally adjusted at annual rates",
                "Debt service indicators": "Mortgage debt service ratio",
                "UOM": "Percent", "VECTOR": "v99451480", "VALUE": "8.0",
            },
        ]
        parsed = parse_statcan_mortgage_dsr(rows)
        self.assertEqual(parsed["reference_period"], "2026Q2")
        self.assertEqual(parsed["metrics"]["mortgage_debt_service_ratio_pct"]["value"], 8.0)

    def test_cmhc_parser(self):
        html = """
        <h2>August monthly housing starts key highlights</h2>
        <p>The trend in housing starts was down in August 2026 compared to July, with a decrease of 1.3% to 244,149 units.</p>
        <p>Actual housing starts were down 2% year-over-year in centres with a population of 10,000 or greater. 17,691 units were recorded in August 2026, compared to 18,112 units in August 2025.</p>
        <p>The year-to-date total was 149,542 units, down 4% from the same period in 2025.</p>
        <p>The total monthly standalone seasonally adjusted annualized rate of housing starts for all areas in Canada was flat in August 2026, at 229,046 units compared to 229,360 units in July 2026.</p>
        <p>Date Published: September 16, 2026</p>
        """
        parsed = parse_cmhc_starts(html)
        self.assertEqual(parsed["metrics"]["standalone_monthly_starts_saar"]["value"], 229046.0)
        self.assertEqual(parsed["metrics"]["six_month_start_trend_saar"]["change_mom_pct"], -1.3)

    def test_statcan_selected_csv_reader(self):
        csv_text = "REF_DATE,GEO,VALUE\n2026-08,Canada,1\n"
        calls = []
        def fetch(url):
            calls.append(url)
            return csv_text.encode()

        rows = _statcan_rows("https://example.test/selected.csv", fetch)
        self.assertEqual(rows[0]["GEO"], "Canada")
        self.assertEqual(len(calls), 1)

    def test_canada_validator(self):
        names = {
            "new_home_prices", "construction", "building_permits",
            "mortgage_lending", "mortgage_balances", "mortgage_rates", "mortgage_burden",
        }
        feeds = {name: {"status": "ok", "url": "https://example.test", "as_of": "2026-09-01"} for name in names}
        validate_canada_housing({"country": "CA", "status": "ok", "feeds": feeds})


if __name__ == "__main__":
    unittest.main()
