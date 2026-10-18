"""Live collector and archive tests. HTTP is stubbed with fixture bytes or tiny HTML."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.canadian_cpi_release.cli import main as cli_main
from scripts.canadian_cpi_release.contract import (
    SERIES,
    WEIGHT_TABLE_PID,
    Observation,
    Snapshot,
)
from scripts.canadian_cpi_release.engine import ObsIndex, forecast_release
from scripts.canadian_cpi_release.sources.acquire import (
    FIXTURE_ROOT,
    load_snapshot,
    save_snapshot,
)
from scripts.canadian_cpi_release.sources.acquire import fetch_live as real_fetch_live
from scripts.canadian_cpi_release.sources.cache import SourceError
from scripts.canadian_cpi_release.sources.nrcan import collect_nrcan, periods_after
from scripts.canadian_cpi_release import sources as sources_pkg

FIXTURE_PATH = FIXTURE_ROOT / "snapshot.json"
RAW_DIR = FIXTURE_ROOT / "raw"
SEPT_HEADLINE = 0.1325763171949602
EX_ENERGY_MOM = -0.03422140158634876
TRIM_YOY = 1.845111358920981
MEDIAN_YOY = 1.903946499405218
DATA_URL = "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods"
INFO_URL = "https://www150.statcan.gc.ca/t1/wds/rest/getSeriesInfoFromCubePidCoord"


def _html(rows: list[tuple[str, str]]) -> bytes:
    body = "".join(f"<tr><td>{period}</td><td>{value}</td></tr>" for period, value in rows)
    return f"<table>{body}</table>".encode("utf-8")


def _months(start: str, end: str, value: str = "100.0") -> list[tuple[str, str]]:
    year, month = int(start[:4]), int(start[5:7])
    stop_y, stop_m = int(end[:4]), int(end[5:7])
    rows: list[tuple[str, str]] = []
    while (year, month) <= (stop_y, stop_m):
        rows.append((f"{year:04d}-{month:02d}", value))
        month += 1
        if month == 13:
            month = 1
            year += 1
    return rows


def _nrcan_opener(pages: dict[tuple[int, int], bytes]):
    def opener(url, timeout=120, data=None, content_type=None):
        if data is not None:
            return {"ok": False, "http_status": 404, "body": b"", "url": url, "error": "unexpected post"}
        product = 1 if "productID=1" in url else 7 if "productID=7" in url else 0
        year = int(url.split("priceYear=")[1])
        body = pages.get((product, year))
        if body is None:
            return {"ok": False, "http_status": 404, "body": b"", "url": url, "error": "missing page"}
        return {"ok": True, "http_status": 200, "body": body, "url": url}

    return opener


class NrcanCollectorTests(unittest.TestCase):
    def test_success_keeps_future_rows_out_of_the_target_note(self) -> None:
        pages = {}
        for year in range(2016, 2025):
            end = "2024-12" if year == 2024 else f"{year}-12"
            start = "2016-07" if year == 2016 else f"{year}-01"
            html = _html(_months(start, end, "110.5"))
            pages[(1, year)] = html
            pages[(7, year)] = html
        notes_holder: list[str] = []
        obs, _pages, notes = collect_nrcan(
            opener=_nrcan_opener(pages),
            sleeper=lambda _delay: None,
            retrieved_at="2026-10-18T12:00:00Z",
            through_period="2024-06",
        )
        notes_holder.extend(notes)
        gasoline = [row for row in obs if row.canonical_id == "nrcan_gasoline"]
        self.assertTrue(any(row.period == "2024-06" and row.value == 110.5 for row in gasoline))
        self.assertTrue(any(row.period == "2024-12" for row in gasoline))
        self.assertEqual(periods_after(["2024-06", "2024-12"], "2024-06"), ["2024-12"])
        future_notes = [note for note in notes if "after requested through period 2024-06" in note]
        self.assertEqual(len(future_notes), 2)
        self.assertTrue(all("2024-07=" in note for note in future_notes))
        self.assertNotIn("REQUIRED_END", " ".join(notes))

    def test_missing_target_month_fails_closed(self) -> None:
        pages = {}
        for year in range(2016, 2025):
            start = "2016-07" if year == 2016 else f"{year}-01"
            end = "2024-05" if year == 2024 else f"{year}-12"
            html = _html(_months(start, end, "90.0"))
            pages[(1, year)] = html
            pages[(7, year)] = html
        with self.assertRaises(SourceError) as caught:
            collect_nrcan(
                opener=_nrcan_opener(pages),
                sleeper=lambda _delay: None,
                retrieved_at="2026-10-18T12:00:00Z",
                through_period="2024-06",
            )
        self.assertEqual(caught.exception.code, "nrcan_missing_target_month")
        self.assertIn("nrcan_gasoline", caught.exception.detail)


class FutureFuelGateTests(unittest.TestCase):
    def test_october_fuel_is_not_eligible_for_september(self) -> None:
        obs = Observation(
            canonical_id="nrcan_gasoline",
            period="2026-10",
            value=186.2,
            published_at=None,
            retrieved_at="2026-10-18T12:00:00Z",
            source_hash="abc",
            units="cents_per_litre",
            seasonal_status="NSA",
            source_url="https://example.test/nrcan",
        )
        snap = Snapshot(
            schema_version="canadian_cpi_release_v1",
            retrieved_at="2026-10-18T12:00:00Z",
            observations=[obs],
        )
        index = ObsIndex.build(snap, "2026-10-16", "2026-09")
        self.assertFalse(index.eligible(obs))
        self.assertIsNone(index.get_obs("nrcan_gasoline", "2026-10"))


def _load_vector_objects() -> dict[int, dict]:
    found: dict[int, dict] = {}
    for path in sorted(RAW_DIR.glob("statcan*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for block in payload:
            obj = block["object"]
            found[int(obj["vectorId"])] = obj
    return found


_VECTORS: dict[int, dict] | None = None


def _vectors() -> dict[int, dict]:
    global _VECTORS
    if _VECTORS is None:
        _VECTORS = _load_vector_objects()
    return _VECTORS


def _spec_for(product_id: int, coordinate: str):
    for spec in SERIES:
        if product_id == WEIGHT_TABLE_PID and spec.weight_coordinate == coordinate:
            return spec
        if spec.table_pid == product_id and spec.coordinate == coordinate:
            return spec
    return None


def _fixture_opener(url, timeout=120, data=None, content_type=None):
    if url == INFO_URL:
        requests = json.loads(data.decode("utf-8"))
        body = []
        for req in requests:
            spec = _spec_for(int(req["productId"]), req["coordinate"])
            if spec is None:
                body.append({"status": "FAILED", "object": {}})
                continue
            if int(req["productId"]) == WEIGHT_TABLE_PID:
                vector_id = spec.weight_vector_id
            else:
                vector_id = spec.vector_id
            body.append(
                {
                    "status": "SUCCESS",
                    "object": {
                        "productId": int(req["productId"]),
                        "coordinate": req["coordinate"],
                        "vectorId": vector_id,
                        "SeriesTitleEn": f"Canada;{spec.title}",
                    },
                }
            )
        return {"ok": True, "http_status": 200, "body": json.dumps(body).encode("utf-8"), "url": url}
    if url == DATA_URL:
        requests = json.loads(data.decode("utf-8"))
        vectors = _vectors()
        body = []
        for req in requests:
            obj = vectors[int(req["vectorId"])]
            body.append({"status": "SUCCESS", "object": obj})
        return {"ok": True, "http_status": 200, "body": json.dumps(body).encode("utf-8"), "url": url}
    if "prices_bycity" in url:
        product = "gasoline" if "productID=1" in url else "furnace_oil"
        year = url.split("priceYear=")[1]
        path = RAW_DIR / f"nrcan_nrcan_{product}_{year}.html"
        if not path.is_file():
            return {"ok": False, "http_status": 404, "body": b"", "url": url, "error": "missing html"}
        return {"ok": True, "http_status": 200, "body": path.read_bytes(), "url": url}
    return {"ok": False, "http_status": 404, "body": b"", "url": url, "error": "unexpected url"}


class LiveArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = real_fetch_live(
            "2026-10-18T12:00:00Z",
            opener=_fixture_opener,
            sleeper=lambda _delay: None,
            through_period="2026-09",
        )

    def test_collector_matches_frozen_fixture_values(self) -> None:
        frozen = load_snapshot(FIXTURE_PATH)
        self.assertEqual(
            _point(self.snapshot, "cpi_nsa_all_items", "2026-08"),
            _point(frozen, "cpi_nsa_all_items", "2026-08"),
        )
        self.assertEqual(_point(self.snapshot, "cpi_nsa_all_items", "2026-08"), 169.8)
        self.assertEqual(_point(self.snapshot, "cpi_nsa_all_items", "2025-09"), 164.9)
        self.assertEqual(_point(self.snapshot, "cpi_nsa_gasoline__weight", "2025-01"), 4.01)
        self.assertEqual(_point(self.snapshot, "nrcan_gasoline", "2026-09"), 187.5)
        self.assertEqual(_point(self.snapshot, "nrcan_gasoline", "2026-10"), 186.2)
        self.assertTrue(any("after requested through period 2026-09" in note for note in self.snapshot.notes))
        self.assertIsNone(_point(frozen, "cpi_nsa_all_items", "2026-09"))
        self.assertIsNone(_point(self.snapshot, "cpi_nsa_all_items", "2026-09"))

    def test_cli_archives_raw_hashes_and_replay_matches_september(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)

            def _return_snapshot(*_args, **_kwargs):
                return self.snapshot

            with patch("scripts.canadian_cpi_release.cli.fetch_live", _return_snapshot):
                code = cli_main(
                    [
                        "nowcast",
                        "--release",
                        "2026-09",
                        "--as-of",
                        "2026-10-16",
                        "--out",
                        str(out),
                        "--live",
                    ]
                )
            self.assertEqual(code, 0)
            runs = list((out / "runs").iterdir())
            self.assertEqual(len(runs), 1)
            archive = runs[0]
            snapshot_bytes = (archive / "snapshot.json").read_bytes()
            manifest = json.loads((archive / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["snapshot_sha256"], hashlib.sha256(snapshot_bytes).hexdigest())
            self.assertTrue(archive.name.endswith(manifest["snapshot_sha256"][:12]))
            for rec in manifest["source_records"]:
                raw_path = archive / rec["path"]
                raw = raw_path.read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), rec["sha256"])
                self.assertEqual(len(raw), rec["bytes"])
                self.assertTrue(raw_path.suffix in {".json", ".html"})
            nowcast = json.loads((archive / "nowcast.json").read_text(encoding="utf-8"))
            self.assertAlmostEqual(nowcast["headline_nsa_mom"], SEPT_HEADLINE, places=9)
            self.assertAlmostEqual(nowcast["special_aggregates"]["cpi_nsa_ex_energy"]["nsa_mom"], EX_ENERGY_MOM, places=9)
            self.assertEqual(
                nowcast["special_aggregates"]["cpi_nsa_ex_energy"]["sa_method"],
                "unavailable_no_official_sa",
            )
            self.assertNotAlmostEqual(
                nowcast["special_aggregates"]["cpi_nsa_ex_energy"]["nsa_mom"],
                nowcast["special_aggregates"]["cpi_nsa_ex_food_energy"]["nsa_mom"],
                places=6,
            )
            self.assertAlmostEqual(nowcast["core"]["cpi_trim"]["yoy_forecast"], TRIM_YOY, places=9)
            self.assertAlmostEqual(nowcast["core"]["cpi_median"]["yoy_forecast"], MEDIAN_YOY, places=9)
            self.assertEqual(nowcast["basket_year"], 2025)
            self.assertEqual(nowcast["basket_link"], "2026-04")
            leaves = [row for row in nowcast["contributions"] if row["role"] == "contribution_leaf"]
            self.assertAlmostEqual(
                sum(row["contribution_pp"] for row in leaves),
                nowcast["headline_nsa_mom"],
                places=8,
            )
            self.assertIn("runs/", nowcast["input_archive"]["replay_fixture"])
            raw_digest = hashlib.sha256(next(archive.glob("raw/*.html")).read_bytes()).hexdigest()

            with patch("scripts.canadian_cpi_release.cli.fetch_live", _return_snapshot):
                code_again = cli_main(
                    [
                        "nowcast",
                        "--release",
                        "2026-09",
                        "--as-of",
                        "2026-10-16",
                        "--out",
                        str(out),
                        "--live",
                    ]
                )
            self.assertEqual(code_again, 0)
            self.assertEqual(len(list((out / "runs").iterdir())), 1)
            self.assertEqual(
                hashlib.sha256(next(archive.glob("raw/*.html")).read_bytes()).hexdigest(),
                raw_digest,
            )

            reloaded = load_snapshot(archive / "snapshot.json")
            replay = forecast_release(reloaded, "2026-09", "2026-10-16")
            self.assertEqual(replay.status, "ok")
            self.assertAlmostEqual(replay.headline_nsa_mom, SEPT_HEADLINE, places=9)
            self.assertAlmostEqual(replay.special_aggregates["cpi_nsa_ex_energy"]["nsa_mom"], EX_ENERGY_MOM, places=9)
            self.assertAlmostEqual(replay.core["cpi_trim"]["yoy_forecast"], TRIM_YOY, places=9)
            self.assertAlmostEqual(replay.core["cpi_median"]["yoy_forecast"], MEDIAN_YOY, places=9)

    def test_persistence_failure_does_not_publish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)

            def _return_snapshot(*_args, **_kwargs):
                return self.snapshot

            def _fail(*_args, **_kwargs):
                raise OSError("disk full")

            with patch("scripts.canadian_cpi_release.cli.fetch_live", _return_snapshot):
                with patch("scripts.canadian_cpi_release.cli.save_snapshot", _fail):
                    code = cli_main(
                        [
                            "nowcast",
                            "--release",
                            "2026-09",
                            "--as-of",
                            "2026-10-16",
                            "--out",
                            str(out),
                            "--live",
                        ]
                    )
            self.assertEqual(code, 2)
            self.assertFalse(any(out.rglob("nowcast.json")))

    def test_save_snapshot_refuses_missing_raw_and_conflicts(self) -> None:
        snap = Snapshot(
            schema_version="canadian_cpi_release_v1",
            retrieved_at="2026-10-18T12:00:00Z",
            observations=[],
            source_records=[{"path": "raw/example.json", "sha256": hashlib.sha256(b"{}").hexdigest(), "bytes": 2}],
        )
        saved = dict(sources_pkg.acquire._PENDING_RAW)
        sources_pkg.acquire._PENDING_RAW.clear()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(SourceError) as caught:
                    save_snapshot(snap, Path(tmp) / "run")
                self.assertEqual(caught.exception.code, "archive_raw_missing")
                self.assertFalse((Path(tmp) / "run").exists())
        finally:
            sources_pkg.acquire._PENDING_RAW.clear()
            sources_pkg.acquire._PENDING_RAW.update(saved)

        body = b'{"ok":true}'
        digest = hashlib.sha256(body).hexdigest()
        good = Snapshot(
            schema_version="canadian_cpi_release_v1",
            retrieved_at="2026-10-18T12:00:00Z",
            observations=[],
            source_records=[{"path": "raw/example.json", "sha256": digest, "bytes": len(body), "url": "https://example.test"}],
        )
        good._raw_files = {"raw/example.json": body}
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "run"
            save_snapshot(good, dest)
            original = (dest / "raw" / "example.json").read_bytes()
            (dest / "snapshot.json").write_bytes(b"{}\n")
            with self.assertRaises(SourceError) as caught:
                save_snapshot(good, dest)
            self.assertEqual(caught.exception.code, "archive_conflict")
            self.assertEqual((dest / "raw" / "example.json").read_bytes(), original)


def _point(snapshot: Snapshot, canonical_id: str, period: str) -> float | None:
    for obs in snapshot.observations:
        if obs.canonical_id == canonical_id and obs.period == period:
            return obs.value
    return None


if __name__ == "__main__":
    unittest.main()
