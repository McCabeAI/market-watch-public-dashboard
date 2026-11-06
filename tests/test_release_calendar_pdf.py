from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.dashboard_repair.pdf_text import (  # noqa: E402
    PdfExtractError,
    body_to_text,
    extract_pdf_text,
)

FIXTURE_PDF = Path(__file__).parent / "fixtures" / "release_calendar" / "pdf" / "sample_schedule.pdf"


class ReleaseCalendarPdfTest(unittest.TestCase):
    def test_body_to_text_and_extract_pdf(self) -> None:
        data = FIXTURE_PDF.read_bytes()
        self.assertTrue(data.startswith(b"%PDF"))

        phrase = "Labour Force Survey November 6, 2026"
        self.assertNotIn(phrase, data.decode("utf-8", "replace"))

        pdf_url = "https://example.test/2026-eng.pdf"
        out = body_to_text(pdf_url, data)
        self.assertIn(phrase, out)

        html = b"<p>8:30 a.m. Eastern</p>"
        self.assertEqual(
            body_to_text("https://example.test/page.html", html),
            '<p>8:30 a.m. Eastern</p>',
        )

        buf = io.StringIO()
        with self.assertRaises(PdfExtractError), redirect_stderr(buf):
            extract_pdf_text(b"%PDF-1.4 not a real pdf")


if __name__ == "__main__":
    unittest.main()
