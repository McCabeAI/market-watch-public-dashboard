from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.harvest_nz_pci import (  # noqa: E402
    canonical_pdf_url,
    choose_observations,
    discover_psi_pdf_urls,
    local_cached_pdf,
    parse_headline_reference_period,
    parse_pci_table,
)

FIXTURES = Path(__file__).parent / "fixtures" / "nz_pci"


class HarvestNzPciTest(unittest.TestCase):
    def test_parse_pci_table_july_fixture(self) -> None:
        text = (FIXTURES / "july_2026_pci_table.txt").read_text(encoding="utf-8")
        parsed = parse_pci_table(text)
        self.assertEqual(parsed["2026-07"], 51.1)
        self.assertEqual(parsed["2026-05"], 48.5)
        self.assertEqual(parsed["2026-06"], 51.6)

    def test_parse_headline_reference_period_june_fixture(self) -> None:
        text = (FIXTURES / "june_2026_headline.txt").read_text(encoding="utf-8")
        self.assertEqual(parse_headline_reference_period(text), "2026-06")
        self.assertEqual(parse_pci_table(text)["2026-06"], 51.2)

    def test_choose_observations_prefers_contemporaneous_release(self) -> None:
        parsed = [
            {
                "url": "https://www.bnz.co.nz/assets/markets/research/BNZ-BusinessNZ-PSI-Release-June-2026_web.pdf",
                "release_date": "2026-07-13",
                "headline_reference_period": "2026-06",
                "pci": {"2026-06": 51.2},
                "bytes": b"",
            },
            {
                "url": "https://www.bnz.co.nz/assets/markets/research/BNZ-BusinessNZ-PSI-Release_August-2026_web.pdf",
                "release_date": "2026-09-14",
                "headline_reference_period": "2026-08",
                "pci": {"2026-06": 51.5},
                "bytes": b"",
            },
        ]
        best = choose_observations(parsed, "2026-09-21")
        self.assertEqual(best["2026-06"]["value"], 51.2)
        self.assertTrue(best["2026-06"]["_headline_match"])

    def test_canonical_pdf_url_strips_query(self) -> None:
        href = "/assets/markets/research/BNZ-BusinessNZ-PSI-Release_July-2026_web.pdf?hash=1"
        self.assertTrue(
            canonical_pdf_url(href).endswith("BNZ-BusinessNZ-PSI-Release_July-2026_web.pdf")
        )

    def test_discover_psi_pdf_urls_from_fixture_html(self) -> None:
        html = (FIXTURES / "publications_snippet.html").read_text(encoding="utf-8")

        def fake_fetch(_url, **kwargs):  # noqa: ANN001, ARG001
            return html.encode("utf-8")

        with patch("scripts.harvest_nz_pci.fetch_bytes", fake_fetch):
            urls = discover_psi_pdf_urls()
        self.assertTrue(any("June-2026" in u for u in urls))
        self.assertTrue(any("July-2026" in u for u in urls))

    def test_parse_real_august_2026_psi_pdf(self) -> None:
        from pypdf import PdfReader

        pdf = ROOT / "data" / "temperature_history" / "raw" / "nz" / "bnz_businessnz_psi_pci_2026-08.pdf"
        text = "\n".join((page.extract_text() or "") for page in PdfReader(str(pdf)).pages)
        parsed = parse_pci_table(text)
        self.assertEqual(parsed["2026-08"], 51.6)
        self.assertEqual(parsed["2026-07"], 51.1)
        self.assertEqual(parsed["2026-05"], 48.5)

    def test_local_cache_serves_june_july_august_pdfs(self) -> None:
        from pypdf import PdfReader

        raw = ROOT / "data" / "temperature_history" / "raw" / "nz"
        expected = {
            "https://www.bnz.co.nz/assets/markets/research/BNZ-BusinessNZ-PSI-Release-June-2026_web.pdf": (
                "2026-06",
                51.2,
            ),
            "https://www.bnz.co.nz/assets/markets/research/BNZ-BusinessNZ-PSI-Release_July-2026_web.pdf": (
                "2026-07",
                51.1,
            ),
            "https://www.bnz.co.nz/assets/markets/research/BNZ-BusinessNZ-PSI-Release_August-2026_web.pdf": (
                "2026-08",
                51.6,
            ),
        }
        for url, (period, value) in expected.items():
            data = local_cached_pdf(url, raw)
            self.assertIsNotNone(data, url)
            self.assertEqual(data[:4], b"%PDF")
            text = "\n".join(
                (page.extract_text() or "") for page in PdfReader(io.BytesIO(data)).pages
            )
            self.assertEqual(parse_pci_table(text)[period], value)
