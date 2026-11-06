"""PDF payload helpers for official economic release calendars."""

from __future__ import annotations

import io
from urllib.parse import urlparse

__all__ = [
    "PdfExtractError",
    "body_to_text",
    "extract_pdf_text",
    "looks_like_pdf",
]


class PdfExtractError(RuntimeError):
    """Raised when a PDF cannot be read or yields no extractable text."""


def looks_like_pdf(payload: bytes, url: str = "", content_type: str = "") -> bool:
    if payload.startswith(b"%PDF"):
        return True
    if urlparse(url).path.lower().endswith(".pdf"):
        return True
    return "pdf" in content_type.lower()


def extract_pdf_text(payload: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise PdfExtractError("pypdf is required to extract PDF text") from exc

    try:
        reader = PdfReader(io.BytesIO(payload))
        parts = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        raise PdfExtractError("payload is not a readable PDF") from exc

    text = "\n".join(parts)
    if not text.strip():
        raise PdfExtractError("PDF contained no extractable text")
    return text


def body_to_text(url: str, payload: bytes, content_type: str = "") -> str:
    if looks_like_pdf(payload, url=url, content_type=content_type):
        return extract_pdf_text(payload)
    return payload.decode("utf-8", "replace")
