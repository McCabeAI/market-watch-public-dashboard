"""Load frozen import-price sensitivity inputs for core PCE (no network)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

_BUNDLE_NAME = "import_price_2026-10-16"
_DEFAULT_BUNDLE_DIR = (
    Path(__file__).resolve().parents[2] / "data" / "core_pce_release" / _BUNDLE_NAME
)

_G0_CONTRACT_FILE = "g0_contract.json"
_PROVENANCE_FILE = "provenance.json"
_PPI_RAW_FILE = "ppi_oneshot_raw_documents.json"
_BLS_API_FILE = "bls_api_air_2026.json"

_PERIOD_TO_BLS = {"2026-09": "M09", "2026-08": "M08"}
_BLS_TO_PERIOD = {v: k for k, v in _PERIOD_TO_BLS.items()}


class ImportPriceSourceError(Exception):
    """Raised when frozen import-price fixtures fail contract or integrity checks."""

    def __init__(self, reason: str, detail: str | None = None) -> None:
        self.reason = reason
        message = reason if detail is None else f"{reason}: {detail}"
        super().__init__(message)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_ppi_raw_documents(raw_documents: list[Any]) -> str:
    payload = json.dumps(raw_documents, sort_keys=True).encode("utf-8")
    return _sha256_bytes(payload)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _period_value(series: dict[str, Any], bls_period: str) -> tuple[str | None, list[Any] | None]:
    for row in series.get("data") or []:
        if row.get("period") == bls_period:
            return str(row.get("value")), row.get("footnotes")
    return None, None


def _footnote_code(footnotes: list[Any] | None) -> str | None:
    if not footnotes:
        return None
    for item in footnotes:
        if isinstance(item, dict) and item.get("code"):
            return str(item["code"])
    return None


def _find_series(api_doc: dict[str, Any], series_id: str) -> dict[str, Any] | None:
    for series in (api_doc.get("Results") or {}).get("series") or []:
        if series.get("seriesID") == series_id:
            return series
    return None


def _verify_sha(
    label: str,
    actual: str,
    expected: str,
) -> None:
    if actual != expected:
        raise ImportPriceSourceError("fixture_sha_mismatch", f"{label} expected {expected} got {actual}")


def load_import_price_bundle(
    bundle_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Load and verify the import-price fixture bundle. Performs no network I/O."""
    root = Path(bundle_dir) if bundle_dir is not None else _DEFAULT_BUNDLE_DIR
    contract_path = root / _G0_CONTRACT_FILE
    provenance_path = root / _PROVENANCE_FILE
    ppi_path = root / _PPI_RAW_FILE
    bls_path = root / _BLS_API_FILE

    for path in (contract_path, provenance_path, ppi_path, bls_path):
        if not path.is_file():
            raise ImportPriceSourceError("fixture_sha_mismatch", f"missing file {path.name}")

    contract = _read_json(contract_path)
    provenance = _read_json(provenance_path)
    ppi_oneshot_raw_documents = _read_json(ppi_path)
    bls_api = _read_json(bls_path)

    ppi_sha = _sha256_ppi_raw_documents(ppi_oneshot_raw_documents)
    bls_sha = _sha256_bytes(bls_path.read_bytes())

    integrity = provenance.get("integrity") or {}
    _verify_sha(
        "ppi_oneshot_raw_documents",
        ppi_sha,
        str(integrity.get("ppi_oneshot_raw_documents_sha256") or ""),
    )
    _verify_sha(
        "bls_api_air_2026",
        bls_sha,
        str(integrity.get("bls_api_air_2026_file_sha256") or ""),
    )

    import_spec = contract.get("import_leg") or {}
    ppi_spec = contract.get("international_ppi_leg") or {}

    target_period = str(import_spec.get("period") or "")
    prior_period = str(import_spec.get("prior_period") or "")
    if target_period != "2026-09":
        raise ImportPriceSourceError("source_period_not_2026-09", target_period)

    import_series_id = str(import_spec.get("series_id") or "")
    ppi_series_id = str(ppi_spec.get("series_id") or "")

    import_series = _find_series(bls_api, import_series_id)
    if import_series is None:
        raise ImportPriceSourceError("missing_import_leg", import_series_id)

    ppi_series = _find_series(bls_api, ppi_series_id)
    if ppi_series is None:
        raise ImportPriceSourceError("missing_international_ppi_leg", ppi_series_id)

    import_index, _ = _period_value(import_series, _PERIOD_TO_BLS[target_period])
    import_prior, _ = _period_value(import_series, _PERIOD_TO_BLS[prior_period])
    if import_index is None:
        raise ImportPriceSourceError("source_period_not_2026-09", "missing EIUIV142 September")
    if import_prior is None:
        raise ImportPriceSourceError("missing_import_leg", "missing EIUIV142 August")

    ppi_index, ppi_footnotes = _period_value(ppi_series, _PERIOD_TO_BLS[target_period])
    ppi_prior, _ = _period_value(ppi_series, _PERIOD_TO_BLS[prior_period])
    if ppi_index is None:
        raise ImportPriceSourceError("source_period_not_2026-09", "missing PCU4811114811112 September")
    if ppi_prior is None:
        raise ImportPriceSourceError("missing_international_ppi_leg", "missing PCU4811114811112 August")

    expected_import_index = str(import_spec.get("index") or "")
    expected_import_prior = str(import_spec.get("prior_index") or "")
    expected_ppi_index = str(ppi_spec.get("index") or "")
    expected_ppi_prior = str(ppi_spec.get("prior_index") or "")
    expected_import_nsa = str(import_spec.get("seasonal_status") or "")
    expected_ppi_nsa = str(ppi_spec.get("seasonal_status") or "")
    expected_footnote = str(ppi_spec.get("footnote_code") or "")

    if import_index != expected_import_index or import_prior != expected_import_prior:
        raise ImportPriceSourceError(
            "missing_import_leg",
            f"index mismatch got {import_index}/{import_prior}",
        )
    if ppi_index != expected_ppi_index or ppi_prior != expected_ppi_prior:
        raise ImportPriceSourceError(
            "missing_international_ppi_leg",
            f"index mismatch got {ppi_index}/{ppi_prior}",
        )
    if expected_import_nsa != "NSA" or expected_ppi_nsa != "NSA":
        raise ImportPriceSourceError("nsa_passed_as_bea_sa", "contract seasonal_status not NSA")

    footnote_code = _footnote_code(ppi_footnotes)
    if footnote_code != expected_footnote:
        raise ImportPriceSourceError(
            "missing_international_ppi_leg",
            f"footnote_code expected {expected_footnote} got {footnote_code}",
        )

    import_leg = {
        "series_id": import_series_id,
        "period": target_period,
        "prior_period": prior_period,
        "index": import_index,
        "prior_index": import_prior,
        "seasonal_status": "NSA",
    }
    ppi_leg = {
        "series_id": ppi_series_id,
        "period": target_period,
        "prior_period": prior_period,
        "index": ppi_index,
        "prior_index": ppi_prior,
        "seasonal_status": "NSA",
        "footnote_code": footnote_code,
    }

    return {
        "import_leg": import_leg,
        "ppi_leg": ppi_leg,
        "ppi_oneshot_raw_documents": ppi_oneshot_raw_documents,
        "provenance": provenance,
    }
