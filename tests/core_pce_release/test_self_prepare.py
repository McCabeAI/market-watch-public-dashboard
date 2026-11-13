"""Self-preparing CPI/PPI acquisition."""

from __future__ import annotations

import email.message
import hashlib
import json
import shutil
import tempfile
import unittest
import urllib.error
import zipfile
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from unittest import mock
from urllib.response import addinfourl

from scripts.core_pce_release.acquire import cached_cpi_series, load_registry, priority_ppi_series
from scripts.core_pce_release.bea_workbook import parse_bea_workbook, workbook_sha256
from scripts.core_pce_release.cli import main
from scripts.core_pce_release.oneshot import authorize_release_issue, run_oneshot
from scripts.core_pce_release.preflight import assess_release
from scripts.core_pce_release.release_bundle import INDEX_PATH, resolve_release
from scripts.core_pce_release.self_prepare import (
    BEA_URL,
    FROZEN_CPI_RAW_SHA,
    FROZEN_PCEPILFE_SHA,
    FROZEN_WORKBOOK_SHA,
    PCEPILFE_FETCH_TIMEOUT_SECONDS,
    PCEPILFE_URL,
    OfficialSources,
    build_cpi_packet,
    build_from_recorded_extract,
    fetch_official_sources,
    restore_cpi_packet,
    run_cpi_trigger,
    run_ppi_trigger,
)

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "core_pce_release"
SEPTEMBER_PRE = "0.3688405280179773205064998201"
SEPTEMBER_POST = "0.3674603939775941051607229995"
OCTOBER_PRE = "0.2777814111959602086682108972"
OCTOBER_POST = "0.2976893241979532386598166555"
PPI_POINTS = DATA / "ppi_points_2026-11-13.json"
TEMPLATE = json.loads((DATA / "snapshot_2026-09-30" / "components.json").read_text(encoding="utf-8"))["components"]


def _inline_cell(col: int, row: int, value: str) -> str:
    letters = ""
    c = col
    while True:
        letters = chr(ord("A") + c % 26) + letters
        c = c // 26 - 1
        if c < 0:
            break
    ref = f"{letters}{row}"
    text = value.replace("&", "&amp;").replace("<", "&lt;")
    return f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'


def _inline_num(col: int, row: int, value: str) -> str:
    letters = ""
    c = col
    while True:
        letters = chr(ord("A") + c % 26) + letters
        c = c // 26 - 1
        if c < 0:
            break
    ref = f"{letters}{row}"
    return f'<c r="{ref}"><v>{value}</v></c>'


def _sheet_xml(rows: dict[int, list[tuple[int, str]]]) -> str:
    parts = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>', '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">', "<sheetData>"]
    for row_num in sorted(rows):
        parts.append(f'<row r="{row_num}">')
        for col, value in rows[row_num]:
            if value.replace(".", "", 1).isdigit() and col > 2:
                parts.append(_inline_num(col, row_num, value))
            else:
                parts.append(_inline_cell(col, row_num, value))
        parts.append("</row>")
    parts.extend(["</sheetData>", "</worksheet>"])
    return "".join(parts)


def make_stub_workbook(
    *,
    monthly_through: str,
    quarterly_through: str,
    index_value: str = "100",
    dot_period: str | None = None,
    core_pce_line_levels: dict[str, str] | None = None,
    core_pce_name: str = "PCE excluding food and energy",
    published_text: str = "Data published Oct 29, 2026",
    index_base_text: str = "2017=100",
) -> bytes:
    month_cols: list[str] = []
    year, month = int(monthly_through[:4]), int(monthly_through[5:7])
    start_year = 2025
    if core_pce_line_levels:
        earliest = min(core_pce_line_levels)
        start_year = min(start_year, int(earliest[:4]))
    earliest = min(core_pce_line_levels) if core_pce_line_levels else None
    for y in range(start_year, year + 1):
        if earliest and y == int(earliest[:4]):
            start_m = int(earliest[5:7])
        elif not core_pce_line_levels and y == 2025:
            start_m = 7
        else:
            start_m = 1
        end_m = month if y == year else 12
        for m in range(start_m, end_m + 1):
            month_cols.append(f"{y}M{m:02d}")
    header_row = {8: [(0, "Line"), (1, "Name"), (2, "Code")] + [(col + 3, token) for col, token in enumerate(month_cols)]}
    monthly_rows = dict(header_row)
    monthly_rows[1] = [(3, published_text)]
    monthly_rows[2] = [(3, "File created Oct 28 2026")]
    monthly_rows[3] = [(3, index_base_text)]
    for template_row in TEMPLATE:
        line = int(template_row["line"])
        rnum = 9 + line
        cells = [(0, str(line)), (1, template_row["name"]), (2, template_row.get("bea_series_code") or "X")]
        for col_offset, token in enumerate(month_cols):
            period = f"{token[:4]}-{token[5:7]}"
            if period >= "2026-07" and period <= monthly_through:
                value = "..." if dot_period and period == dot_period else index_value
                cells.append((col_offset + 3, value))
        monthly_rows[rnum] = cells
    if core_pce_line_levels is not None:
        rnum = 9 + 374
        cells = [(0, "374"), (1, core_pce_name), (2, "DPCCRG")]
        for col_offset, token in enumerate(month_cols):
            period = f"{token[:4]}-{token[5:7]}"
            if period in core_pce_line_levels:
                cells.append((col_offset + 3, core_pce_line_levels[period]))
        monthly_rows[rnum] = cells
    q_year = int(quarterly_through[:4])
    qn = int(quarterly_through[-1])
    quarters = [f"{q_year - 1}Q4"] + [f"{q_year}Q{i}" for i in range(1, qn + 1)]
    q_header = {8: [(0, "Line"), (1, "Name"), (2, "Code")] + [(col + 3, token) for col, token in enumerate(quarters)]}
    quarterly_rows = dict(q_header)
    signed = sum(int(row["sign"]) for row in TEMPLATE)
    official = signed * 1000
    def _quarterly_line(line: int, name: str, code: str = "X") -> None:
        rnum = 9 + line
        cells = [(0, str(line)), (1, name), (2, code)]
        for col_offset, token in enumerate(quarters):
            value = str(official) if line == 374 else "1000"
            cells.append((col_offset + 3, value))
        quarterly_rows[rnum] = cells

    for template_row in TEMPLATE:
        _quarterly_line(int(template_row["line"]), template_row["name"], template_row.get("bea_series_code") or "X")
    if 374 not in {int(row["line"]) for row in TEMPLATE}:
        _quarterly_line(374, "Personal consumption expenditures", "DPCCRG")
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            "</Types>",
        )
        zf.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/></Relationships>')
        zf.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="U20404-M" sheetId="1" r:id="rId1"/><sheet name="U20405-Q" sheetId="2" r:id="rId2"/></sheets></workbook>',
        )
        zf.writestr("xl/worksheets/sheet1.xml", _sheet_xml(monthly_rows))
        zf.writestr("xl/worksheets/sheet2.xml", _sheet_xml(quarterly_rows))
    return buffer.getvalue()


def make_stub_survey_workbook(
    *,
    monthly_through: str,
    core_pce_line_levels: dict[str, str],
    published_text: str = "Data published Oct 29, 2026",
    core_pce_name: str = "PCE excluding food and energy",
) -> bytes:
    month_cols: list[str] = []
    year, month = int(monthly_through[:4]), int(monthly_through[5:7])
    start_year = int(min(core_pce_line_levels)[:4])
    for y in range(start_year, year + 1):
        start_m = int(min(core_pce_line_levels)[5:7]) if y == start_year else 1
        end_m = month if y == year else 12
        for m in range(start_m, end_m + 1):
            month_cols.append(f"{y}M{m:02d}")
    header_row = {8: [(0, "Line"), (1, "Name"), (2, "Code")] + [(col + 3, token) for col, token in enumerate(month_cols)]}
    monthly_rows = dict(header_row)
    monthly_rows[1] = [(3, published_text)]
    monthly_rows[3] = [(3, "2017=100")]
    rnum = 9 + 25
    cells = [(0, "25"), (1, core_pce_name), (2, "DPCCRG")]
    for col_offset, token in enumerate(month_cols):
        period = f"{token[:4]}-{token[5:7]}"
        if period in core_pce_line_levels:
            cells.append((col_offset + 3, core_pce_line_levels[period]))
    monthly_rows[rnum] = cells
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            "</Types>",
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>",
        )
        zf.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="T20804-M" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        zf.writestr("xl/worksheets/sheet1.xml", _sheet_xml(monthly_rows))
    return buffer.getvalue()


def _bea_core_levels_through(anchor: str, value_at_anchor: str = "131.000") -> dict[str, str]:
    levels: dict[str, str] = {}
    period = "2025-10"
    level = Decimal("125.000")
    while period <= anchor:
        levels[period] = value_at_anchor if period == anchor else format(level, "f")
        level += Decimal("0.100")
        y, m = int(period[:4]), int(period[5:7])
        m += 1
        if m > 12:
            y += 1
            m = 1
        period = f"{y:04d}-{m:02d}"
    return levels


def _pcepilfe_csv(through: str) -> str:
    lines = ["observation_date,PCEPILFE"]
    period = "2025-10"
    level = Decimal("125")
    while period <= through:
        lines.append(f"{period}-01,{format(level, 'f')}")
        level += Decimal("0.1")
        y, m = int(period[:4]), int(period[5:7])
        m += 1
        if m > 12:
            y += 1
            m = 1
        period = f"{y:04d}-{m:02d}"
    return "\n".join(lines) + "\n"


def _cpi_points(release: str, anchor: str, *, bump: dict[str, str] | None = None) -> dict:
    registry = load_registry()
    points: dict[str, dict[str, str]] = {}
    for series_id in cached_cpi_series(registry):
        row = {anchor: "100.0", release: "100.2"}
        if bump and series_id in bump:
            row[release] = bump[series_id]
        points[series_id] = row
    return points


def _november_sources() -> OfficialSources:
    workbook = make_stub_workbook(monthly_through="2026-10", quarterly_through="2026Q4", index_value="100")
    return OfficialSources(
        retrieved_at="2026-11-13T12:00:00+00:00",
        bea_url="https://example/bea",
        bea_body=workbook,
        bea_error=None,
        crosswalk_url="https://example/crosswalk",
        crosswalk_body=None,
        crosswalk_error="http_404",
        pcepilfe_url="https://example/pcepilfe",
        pcepilfe_csv=_pcepilfe_csv("2026-10"),
        pcepilfe_error=None,
        cpi_points=_cpi_points("2026-11", "2026-10"),
        cpi_error=None,
        cpi_requests_made=4,
        cpi_raw_sha256=hashlib.sha256(b"nov-cpi").hexdigest(),
        ppi_fetched=None,
        ppi_error=None,
    )


class BeaWorkbookTests(unittest.TestCase):
    def test_parser_unit(self) -> None:
        workbook = make_stub_workbook(monthly_through="2026-08", quarterly_through="2026Q3")
        parsed = parse_bea_workbook(workbook)
        self.assertNotIn("bea_sheet_missing:U20404-M", parsed.get("errors") or [])
        self.assertIn(7, parsed["monthly"])
        self.assertEqual(parsed["monthly"][7]["indexes"].get("2026-08"), "100.000")
        self.assertIn(374, parsed["quarterly"])
        empty = BytesIO()
        with zipfile.ZipFile(empty, "w"):
            pass
        bad = empty.getvalue()
        bad_parsed = parse_bea_workbook(bad)
        self.assertTrue(bad_parsed.get("errors"))

    def test_non_numeric_period_cell_is_skipped(self) -> None:
        workbook = make_stub_workbook(monthly_through="2026-08", quarterly_through="2026Q3")
        parsed = parse_bea_workbook(workbook)
        self.assertIsInstance(parsed, dict)
        dot_workbook = make_stub_workbook(monthly_through="2026-08", quarterly_through="2026Q3", dot_period="2026-08")
        dot_parsed = parse_bea_workbook(dot_workbook)
        self.assertIsInstance(dot_parsed, dict)
        self.assertNotIn("2026-08", dot_parsed["monthly"].get(7, {}).get("indexes", {}))

    def test_official_section2_workbook_when_present(self) -> None:
        official = Path("/tmp/bea-inspect/Section2All_xls.xlsx")
        if not official.is_file():
            self.skipTest("official workbook not mounted")
        parsed = parse_bea_workbook(official.read_bytes())
        self.assertIsInstance(parsed, dict)
        errors = parsed.get("errors") or []
        self.assertFalse(any(err.startswith("bea_workbook_unreadable") for err in errors))
        self.assertEqual(parsed["monthly"][7]["indexes"].get("2026-09"), "122.761")
        self.assertEqual(parsed["quarterly"][374]["quarters"].get("2026Q3"), "19859826")
        self.assertEqual(parsed["quarterly"][7]["quarters"].get("2026Q3"), "28927")
        self.assertNotIn("2026-10", parsed["monthly"][7]["indexes"])


class SelfPrepareTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_future_month_without_index_row(self) -> None:
        self.assertIsNone(resolve_release("2026-11"))
        index_before = INDEX_PATH.read_bytes()
        out = self.tempdir / "cpi"
        code, comment = run_cpi_trigger("2026-11", out, _november_sources(), packet_store=self.tempdir / "store")
        self.assertEqual(code, 0)
        self.assertIn("post_cpi_pre_ppi", comment)
        self.assertIn("origin: acquired", comment)
        self.assertIn("central_mom_percent", comment)
        self.assertNotIn(SEPTEMBER_PRE, comment)
        self.assertNotIn(OCTOBER_PRE, comment)
        self.assertEqual(INDEX_PATH.read_bytes(), index_before)
        components = json.loads((out / "cpi_packet" / "snapshot" / "components.json").read_text(encoding="utf-8"))[
            "components"
        ]
        line7 = next(row for row in components if row["line"] == 7)
        self.assertNotEqual(line7["weight_share"], "0.001456558582134606818811000660")
        self.assertNotEqual(line7["weight_share"], "0.001581703475160996735502700524")
        bundle = build_cpi_packet("2026-11", _november_sources(), self.tempdir / "packet2")
        report = assess_release("2026-11", bundle=bundle)
        self.assertEqual(report["status"], "READY")
        self.assertIn("ppi_not_yet_applied", report["awaiting"])

    def test_missing_source_not_ready(self) -> None:
        sources = _november_sources()
        sources = OfficialSources(**{**sources.__dict__, "bea_body": None, "bea_error": "transport_error"})
        out = self.tempdir / "not-ready"
        code, comment = run_cpi_trigger("2026-11", out, sources)
        self.assertEqual(code, 0)
        self.assertIn("NOT READY", comment)
        self.assertIn("bea_workbook", comment)
        self.assertNotIn(SEPTEMBER_PRE, comment)
        self.assertNotIn(OCTOBER_PRE, comment)

    def test_october_recorded_vintage(self) -> None:
        sources = OfficialSources(
            retrieved_at="2026-11-13T12:00:00+00:00",
            bea_url="https://apps.bea.gov/national/Release/XLS/Underlying/Section2All_xls.xlsx",
            bea_body=b"unused",
            bea_error=None,
            crosswalk_url="https://example",
            crosswalk_body=None,
            crosswalk_error=None,
            pcepilfe_url="https://example",
            pcepilfe_csv="observation_date,PCEPILFE\n",
            pcepilfe_error=None,
            cpi_points={},
            cpi_error=None,
            cpi_requests_made=0,
            cpi_raw_sha256=FROZEN_CPI_RAW_SHA,
            ppi_fetched=None,
            ppi_error=None,
        )
        sources.pcepilfe_csv = Path.read_text(DATA / "snapshot_2026-10-29" / "pcepilfe.csv", encoding="utf-8")
        # sha alignment via frozen shortcut hashes
        with mock.patch("scripts.core_pce_release.self_prepare._body_sha256", return_value=FROZEN_WORKBOOK_SHA), mock.patch(
            "scripts.core_pce_release.self_prepare._csv_sha256", return_value=FROZEN_PCEPILFE_SHA
        ):
            out = self.tempdir / "oct-cpi"
            code, comment = run_cpi_trigger("2026-10", out, sources, packet_store=self.tempdir / "store")
        self.assertEqual(code, 0)
        detailed = json.loads((out / "detailed.json").read_text(encoding="utf-8"))
        self.assertEqual(detailed["central_mom_percent"], OCTOBER_PRE)
        ppi_out = self.tempdir / "oct-ppi"
        run_ppi_trigger(
            "2026-10",
            ppi_out,
            sources=sources,
            packet_store=self.tempdir / "store",
            ppi_points_path=PPI_POINTS,
        )
        audit = json.loads((ppi_out / "audit.json").read_text(encoding="utf-8"))
        self.assertEqual(audit["revised"]["central_mom_percent"], OCTOBER_POST)
        ppi_out2 = self.tempdir / "oct-ppi-2"
        run_ppi_trigger("2026-10", ppi_out2, packet_store=self.tempdir / "store", ppi_points_path=PPI_POINTS)
        audit2 = json.loads((ppi_out2 / "audit.json").read_text(encoding="utf-8"))
        self.assertEqual(audit2["revised"]["central_mom_percent"], OCTOBER_POST)
        detailed = json.loads((ppi_out / "detailed.json").read_text(encoding="utf-8"))
        touched = {row["line"]: row for row in detailed["components"]}
        for line in (184, 185, 186):
            self.assertEqual(touched[line]["seasonal_status_output"], "modeled_not_bea_sa")

    def test_revision_vs_frozen(self) -> None:
        history = json.loads((DATA / "snapshot_2026-10-29" / "bea_component_history.json").read_text(encoding="utf-8"))
        components = json.loads((DATA / "snapshot_2026-10-29" / "components.json").read_text(encoding="utf-8"))[
            "components"
        ]
        cpi_cache = json.loads((DATA / "cpi_cache_2026-11-10.json").read_text(encoding="utf-8"))
        manifest = json.loads((DATA / "snapshot_2026-10-29" / "manifest.json").read_text(encoding="utf-8"))
        pcepilfe = Path.read_text(DATA / "snapshot_2026-10-29" / "pcepilfe.csv", encoding="utf-8")
        bundle = build_from_recorded_extract(
            "2026-10",
            history,
            components,
            pcepilfe,
            cpi_cache,
            {"origin": "acquired", "manifest": manifest, "source_audit": {}},
            self.tempdir / "oct-recorded",
        )
        out = self.tempdir / "recorded-ppi"
        run_oneshot(out, release="2026-10", bundle=bundle, ppi_points_path=PPI_POINTS)
        audit = json.loads((out / "audit.json").read_text(encoding="utf-8"))
        self.assertEqual(audit["offline_baseline"]["central_mom_percent"], OCTOBER_PRE)
        self.assertEqual(audit["revised"]["central_mom_percent"], OCTOBER_POST)
        mutated = json.loads(json.dumps(cpi_cache))
        usable = [
            row for row in load_registry()["verified"] if row.get("usable_as_pce_rate") and row.get("source_family") == "CPI"
        ]
        series_id = usable[0]["series_id"]
        mutated["points"][series_id]["2026-10"] = str(Decimal(mutated["points"][series_id]["2026-10"]) + Decimal("1"))
        build_from_recorded_extract(
            "2026-10",
            history,
            components,
            pcepilfe,
            mutated,
            {
                "origin": "acquired",
                "manifest": manifest,
                "source_audit": {},
            },
            self.tempdir / "revision",
        )
        audit = json.loads((self.tempdir / "revision" / "source_audit.json").read_text(encoding="utf-8"))
        self.assertEqual(audit.get("revision_vs_frozen_reference"), OCTOBER_PRE)
        packet = json.loads((self.tempdir / "revision" / "frozen_cpi_packet.json").read_text(encoding="utf-8"))
        self.assertNotEqual(packet.get("central_mom_percent"), OCTOBER_PRE)

    def test_partial_ppi(self) -> None:
        sources = _november_sources()
        store = self.tempdir / "store"
        run_cpi_trigger("2026-11", self.tempdir / "cpi", sources, packet_store=store)
        registry = load_registry()
        priority = priority_ppi_series(registry)
        points = {series_id: {"2026-10": "100", "2026-11": "101"} for series_id in priority}
        points[priority[0]]["2026-11"] = "102"
        for series_id in priority[1:]:
            points[series_id].pop("2026-11", None)
        baseline_path = store / "2026-11" / "frozen_cpi_packet.json"
        baseline_central = json.loads(baseline_path.read_text(encoding="utf-8"))["central_mom_percent"]
        ppi_fetched = {
            "points": points,
            "requests_made": 1,
            "errors": [],
            "raw_documents": [{"status": "REQUEST_SUCCEEDED", "message": [], "Results": {"series": []}}],
            "footnotes": {},
            "latest": {},
            "key_present": False,
        }
        out = self.tempdir / "partial"
        with mock.patch("scripts.core_pce_release.oneshot.fetch_series", return_value=ppi_fetched):
            run_ppi_trigger("2026-11", out, packet_store=store, ppi_points_path=None)
        comment = (out / "comment.md").read_text(encoding="utf-8")
        self.assertIn("series_not_yet_available:", comment)
        self.assertNotIn("series_not_yet_available: none", comment)
        audit = json.loads((out / "audit.json").read_text(encoding="utf-8"))
        self.assertNotEqual(audit["revised"].get("central_mom_percent"), baseline_central)
        self.assertGreater(len(audit["series"].get("fresh") or []), 0)
        self.assertGreater(len(audit["series"].get("not_yet_available") or []), 0)
        detailed = json.loads((out / "detailed.json").read_text(encoding="utf-8"))
        for row in detailed.get("components") or []:
            if row.get("seasonal_status_output") == "modeled_not_bea_sa":
                self.assertNotEqual(row.get("seasonal_status_output"), "BEA_SA")

    def test_target_mismatch(self) -> None:
        sources = _november_sources()
        build_cpi_packet("2026-11", sources, self.tempdir / "nov-packet")
        bad_points = json.loads(PPI_POINTS.read_text(encoding="utf-8"))
        bad_points["release"] = "2026-10"
        bad_path = self.tempdir / "bad-ppi.json"
        bad_path.write_text(json.dumps(bad_points), encoding="utf-8")
        out = self.tempdir / "mismatch"
        result = run_oneshot(
            out,
            release="2026-11",
            bundle=_bundle_from_store("2026-11", self.tempdir / "nov-packet"),
            ppi_points_path=bad_path,
        )
        self.assertEqual(result.get("reason"), "ppi_points_unreadable")
        comment = (out / "comment.md").read_text(encoding="utf-8")
        self.assertNotIn(OCTOBER_POST, comment)
        self.assertNotIn(SEPTEMBER_POST, comment)

    def test_vintage_reprojection_comment(self) -> None:
        sources = _november_sources()
        run_cpi_trigger("2026-11", self.tempdir / "cpi", sources, packet_store=self.tempdir / "frozen-packet")
        fresh = _november_sources()
        fresh.cpi_raw_sha256 = hashlib.sha256(b"other-cpi").hexdigest()
        bump_id = [row["series_id"] for row in load_registry()["verified"] if row.get("usable_as_pce_rate")][0]
        fresh.cpi_points = _cpi_points("2026-11", "2026-10", bump={bump_id: "110.0"})
        out = self.tempdir / "reproj"
        run_ppi_trigger(
            "2026-11",
            out,
            sources=fresh,
            packet_store=self.tempdir / "frozen-packet",
        )
        comment = (out / "comment.md").read_text(encoding="utf-8")
        self.assertIn("cpi_time_baseline", comment)
        self.assertIn("reprojected_baseline", comment)

    def test_authorize_and_dispatch(self) -> None:
        bot = authorize_release_issue(
            title="[run-cpi] 2026-11",
            author_login="dependabot[bot]",
            author_type="User",
            sender_login="dependabot[bot]",
            sender_type="User",
            permission="write",
        )
        self.assertFalse(bot["authorized"])
        human = authorize_release_issue(
            title="[run-cpi] 2026-11",
            author_login="alice",
            author_type="User",
            sender_login="alice",
            sender_type="User",
            permission="write",
        )
        self.assertTrue(human["authorized"])
        out = self.tempdir / "dispatch"
        with mock.patch(
            "scripts.core_pce_release.cli.fetch_official_sources",
            return_value=_november_sources(),
        ):
            with mock.patch.dict("os.environ", {"ISSUE_TITLE": "[run-cpi] 2026-11"}, clear=False):
                code = main(["dispatch-issue", "--out", str(out)])
        self.assertEqual(code, 0)
        comment = (out / "comment.md").read_text(encoding="utf-8")
        self.assertIn("central_mom_percent", comment)
        index_before = INDEX_PATH.read_bytes()
        with mock.patch(
            "scripts.core_pce_release.cli.fetch_official_sources",
            return_value=_november_sources(),
        ):
            with mock.patch.dict("os.environ", {"ISSUE_TITLE": "[run-ppi] 2026-11"}, clear=False):
                main(["dispatch-issue", "--out", str(out / "ppi")])
        self.assertEqual(INDEX_PATH.read_bytes(), index_before)
        with mock.patch.dict("os.environ", {"ISSUE_TITLE": "hello"}, clear=False):
            self.assertEqual(main(["dispatch-issue", "--out", str(out / "bad")]), 2)


class RestoreCpiPacketTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_restore_uses_name_query_and_redirect_without_auth(self) -> None:
        token = "ghp_test_secret_must_not_leak"
        zip_buffer = BytesIO()
        frozen_doc = {"release": "2026-11", "status": "READY", "source_audit_sha256": "abc"}
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("frozen_cpi_packet.json", json.dumps(frozen_doc))
        zip_bytes = zip_buffer.getvalue()
        blob_url = "https://storage.example/packet.zip"
        calls: list[tuple[str, dict[str, str]]] = []

        def fake_opener(request, timeout=None):
            url = request.full_url
            headers = {key.lower(): value for key, value in request.header_items()}
            calls.append((url, headers))
            if "/actions/artifacts?" in url:
                self.assertIn("name=core-pce-cpi-packet-2026-11", url)
                payload = json.dumps(
                    {
                        "artifacts": [
                            {
                                "name": "core-pce-cpi-packet-2026-11",
                                "archive_download_url": "https://api.github.com/repos/o/r/actions/artifacts/99/zip",
                                "created_at": "2026-11-13T12:00:00Z",
                            }
                        ]
                    }
                ).encode()
                return addinfourl(BytesIO(payload), {}, url, 200)
            if url.endswith("/zip"):
                self.assertIn("authorization", headers)
                redirect_headers = email.message.Message()
                redirect_headers["Location"] = blob_url
                raise urllib.error.HTTPError(url, 302, "Found", redirect_headers, None)
            if url == blob_url:
                self.assertNotIn("authorization", headers)
                return addinfourl(BytesIO(zip_bytes), {}, url, 200)
            raise AssertionError(f"unexpected url {url}")

        env = {
            "ISSUE_TITLE": "[run-ppi] 2026-11",
            "GITHUB_REPOSITORY": "owner/repo",
            "GH_TOKEN": token,
        }
        code = restore_cpi_packet(self.tempdir, env=env, opener=fake_opener)
        self.assertEqual(code, 0)
        restore_meta = json.loads((self.tempdir / "packet_restore.json").read_text(encoding="utf-8"))
        self.assertEqual(restore_meta["status"], "restored")
        self.assertNotIn(token, (self.tempdir / "packet_restore.json").read_text(encoding="utf-8"))
        frozen = json.loads((self.tempdir / "cpi_packet" / "frozen_cpi_packet.json").read_text(encoding="utf-8"))
        self.assertEqual(frozen["release"], "2026-11")
        self.assertEqual(len([call for call in calls if call[0].endswith("/zip")]), 1)
        blob_headers = next(headers for url, headers in calls if url == blob_url)
        self.assertNotIn("authorization", blob_headers)


OFFICIAL_UNDERLYING_INDEX_BASE = (
    "Index numbers, 2017=100; quarters and months are seasonally adjusted"
)


class PcepilfeFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def _sources_jan2027(
        self,
        *,
        pcepilfe_csv: str | None = None,
        pcepilfe_error: str | None = "transport_error",
        core_levels: dict[str, str] | None = None,
        survey_body: bytes | None = None,
        survey_error: str | None = None,
        workbook_monthly_through: str = "2026-12",
    ) -> OfficialSources:
        core_levels = core_levels or _bea_core_levels_through("2026-12", "131.000")
        workbook = make_stub_workbook(
            monthly_through=workbook_monthly_through,
            quarterly_through="2026Q4",
            core_pce_line_levels=core_levels,
        )
        return OfficialSources(
            retrieved_at="2027-01-13T12:00:00+00:00",
            bea_url=BEA_URL,
            bea_body=workbook,
            bea_error=None,
            crosswalk_url="https://example/crosswalk",
            crosswalk_body=None,
            crosswalk_error="http_404",
            pcepilfe_url=PCEPILFE_URL,
            pcepilfe_csv=pcepilfe_csv,
            pcepilfe_error=pcepilfe_error if pcepilfe_csv is None else None,
            cpi_points=_cpi_points("2027-01", "2026-12"),
            cpi_error=None,
            cpi_requests_made=4,
            cpi_raw_sha256=hashlib.sha256(b"jan27-cpi").hexdigest(),
            ppi_fetched=None,
            ppi_error=None,
            survey_body=survey_body,
            survey_error=survey_error,
        )

    def test_official_index_base_sentence_accepts_dccrg(self) -> None:
        core_levels = _bea_core_levels_through("2026-12", "131.000")
        workbook = make_stub_workbook(
            monthly_through="2026-12",
            quarterly_through="2026Q4",
            core_pce_line_levels=core_levels,
            index_base_text=OFFICIAL_UNDERLYING_INDEX_BASE,
        )
        parsed = parse_bea_workbook(workbook)
        self.assertEqual(parsed["index_base"], "2017=100")
        sources = OfficialSources(
            retrieved_at="2027-01-13T12:00:00+00:00",
            bea_url=BEA_URL,
            bea_body=workbook,
            bea_error=None,
            crosswalk_url="https://example/crosswalk",
            crosswalk_body=None,
            crosswalk_error="http_404",
            pcepilfe_url=PCEPILFE_URL,
            pcepilfe_csv=None,
            pcepilfe_error="transport_error",
            cpi_points=_cpi_points("2027-01", "2026-12"),
            cpi_error=None,
            cpi_requests_made=4,
            cpi_raw_sha256=hashlib.sha256(b"jan-official-base").hexdigest(),
            ppi_fetched=None,
            ppi_error=None,
        )
        dest = self.tempdir / "official-base"
        bundle = build_cpi_packet("2027-01", sources, dest)
        self.assertEqual(bundle["status"], "READY")
        audit = json.loads((dest / "source_audit.json").read_text(encoding="utf-8"))
        pcepilfe = next(row for row in audit["sources"] if row["name"] == "pcepilfe")
        self.assertEqual(pcepilfe["provenance"], "bea_underlying_u20404_m")
        out = self.tempdir / "official-cpi"
        code, comment = run_cpi_trigger("2027-01", out, sources)
        self.assertEqual(code, 0)
        self.assertIn("pcepilfe_provenance: bea_underlying_u20404_m", comment)
        self.assertIn("bea_series DPCCRG", comment)

    def test_rejects_2012_index_base_only(self) -> None:
        workbook = make_stub_workbook(
            monthly_through="2026-12",
            quarterly_through="2026Q4",
            core_pce_line_levels=_bea_core_levels_through("2026-12"),
            index_base_text="Index numbers, 2012=100; seasonally adjusted",
        )
        parsed = parse_bea_workbook(workbook)
        self.assertIsNone(parsed["index_base"])
        sources = OfficialSources(
            retrieved_at="2027-01-13T12:00:00+00:00",
            bea_url=BEA_URL,
            bea_body=workbook,
            bea_error=None,
            crosswalk_url="https://example/crosswalk",
            crosswalk_body=None,
            crosswalk_error="http_404",
            pcepilfe_url=PCEPILFE_URL,
            pcepilfe_csv=None,
            pcepilfe_error="transport_error",
            cpi_points=_cpi_points("2027-01", "2026-12"),
            cpi_error=None,
            cpi_requests_made=4,
            cpi_raw_sha256=hashlib.sha256(b"bad-base").hexdigest(),
            ppi_fetched=None,
            ppi_error=None,
        )
        bundle = build_cpi_packet("2027-01", sources, self.tempdir / "bad-base")
        self.assertEqual(bundle["status"], "NOT READY")
        audit = json.loads((self.tempdir / "bad-base" / "source_audit.json").read_text(encoding="utf-8"))
        underlying = next(row for row in audit["missing"] if row["name"] == "bea_underlying_u20404_m")
        self.assertEqual(underlying["error"], "underlying_index_base")

    def test_fred_timeout_uses_underlying(self) -> None:
        index_before = INDEX_PATH.read_bytes()
        sources = self._sources_jan2027()
        out = self.tempdir / "jan-cpi"
        code, comment = run_cpi_trigger("2027-01", out, sources, packet_store=self.tempdir / "store")
        self.assertEqual(code, 0)
        self.assertIn("READY", comment)
        self.assertNotIn(SEPTEMBER_PRE, comment)
        self.assertNotIn(OCTOBER_PRE, comment)
        self.assertEqual(INDEX_PATH.read_bytes(), index_before)
        audit = json.loads((out / "source_audit.json").read_text(encoding="utf-8"))
        pcepilfe = next(row for row in audit["sources"] if row["name"] == "pcepilfe")
        self.assertEqual(pcepilfe["provenance"], "bea_underlying_u20404_m")
        self.assertEqual(pcepilfe["series"], "PCEPILFE")
        self.assertEqual(pcepilfe["bea_series_code"], "DPCCRG")
        self.assertEqual(pcepilfe["url"], BEA_URL)
        self.assertEqual(pcepilfe["anchor_period"], "2026-12")
        self.assertEqual(pcepilfe["period"], "2026-12")
        manifest = json.loads((out / "cpi_packet" / "snapshot" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["pcepilfe"]["provenance"], "bea_underlying_u20404_m")
        anchor_line = [
            line
            for line in out.joinpath("cpi_packet/snapshot/pcepilfe.csv").read_text(encoding="utf-8").splitlines()
            if line.startswith("2026-12")
        ]
        self.assertEqual(anchor_line, ["2026-12-01,131.000"])

    def test_fred_anchor_used_unchanged_with_conflicting_bea(self) -> None:
        fred_csv = _pcepilfe_csv("2026-12")
        levels = _bea_core_levels_through("2026-12", "999.000")
        sources = self._sources_jan2027(pcepilfe_csv=fred_csv, pcepilfe_error=None, core_levels=levels)
        dest = self.tempdir / "fred-packet"
        bundle = build_cpi_packet("2027-01", sources, dest)
        self.assertEqual(bundle["status"], "READY")
        manifest = json.loads((dest / "snapshot" / "manifest.json").read_text(encoding="utf-8"))
        self.assertNotEqual(manifest["pcepilfe"].get("provenance"), "bea_underlying_u20404_m")
        audit = json.loads((dest / "source_audit.json").read_text(encoding="utf-8"))
        pcepilfe = next(row for row in audit["sources"] if row["name"] == "pcepilfe")
        self.assertEqual(pcepilfe["url"], PCEPILFE_URL)
        snapshot_anchor = [
            line.split(",")[1]
            for line in (dest / "snapshot" / "pcepilfe.csv").read_text(encoding="utf-8").splitlines()
            if line.startswith("2026-12")
        ][0]
        fred_anchor = [line.split(",")[1] for line in fred_csv.splitlines() if line.startswith("2026-12")][0]
        self.assertEqual(snapshot_anchor, fred_anchor)

    def test_stale_fred_uses_bea_overlap_month(self) -> None:
        stale_csv = _pcepilfe_csv("2026-11")
        levels = _bea_core_levels_through("2026-12", "131.000")
        levels["2026-11"] = "127.999"
        sources = self._sources_jan2027(pcepilfe_csv=stale_csv, pcepilfe_error=None, core_levels=levels)
        bundle = build_cpi_packet("2027-01", sources, self.tempdir / "stale")
        self.assertEqual(bundle["status"], "READY")
        audit = json.loads((self.tempdir / "stale" / "source_audit.json").read_text(encoding="utf-8"))
        pcepilfe = next(row for row in audit["sources"] if row["name"] == "pcepilfe")
        self.assertEqual(pcepilfe["fred_attempt"]["error"], "stale_anchor")
        text = (self.tempdir / "stale" / "snapshot" / "pcepilfe.csv").read_text(encoding="utf-8")
        self.assertIn("2026-11-01,127.999", text)
        self.assertIn("2026-12-01,131.000", text)

    def test_both_sources_fail_not_ready(self) -> None:
        workbook = make_stub_workbook(monthly_through="2026-12", quarterly_through="2026Q4", core_pce_name="Wrong name")
        sources = OfficialSources(
            retrieved_at="2027-01-13T12:00:00+00:00",
            bea_url=BEA_URL,
            bea_body=workbook,
            bea_error=None,
            crosswalk_url="https://example/crosswalk",
            crosswalk_body=None,
            crosswalk_error="http_404",
            pcepilfe_url=PCEPILFE_URL,
            pcepilfe_csv=None,
            pcepilfe_error="transport_error",
            cpi_points=_cpi_points("2027-01", "2026-12"),
            cpi_error=None,
            cpi_requests_made=4,
            cpi_raw_sha256=hashlib.sha256(b"x").hexdigest(),
            ppi_fetched=None,
            ppi_error=None,
            survey_body=None,
            survey_error="transport_error",
        )
        out = self.tempdir / "not-ready"
        code, comment = run_cpi_trigger("2027-01", out, sources)
        self.assertEqual(code, 0)
        self.assertIn("NOT READY", comment)
        self.assertIn(PCEPILFE_URL, comment)
        self.assertIn(BEA_URL, comment)
        self.assertNotIn(SEPTEMBER_PRE, comment)
        self.assertNotIn(OCTOBER_PRE, comment)
        audit = json.loads((out / "source_audit.json").read_text(encoding="utf-8"))
        self.assertTrue(any(row.get("name") == "pcepilfe" for row in audit["missing"]))

    def test_snapshot_validation_quantize(self) -> None:
        official_text = Path.read_text(DATA / "snapshot_2026-10-29" / "pcepilfe.csv", encoding="utf-8")
        levels: dict[str, str] = {}
        for line in official_text.strip().splitlines()[1:]:
            period, value = line.split(",")
            if period[:7] > "2026-09":
                continue
            levels[period[:7]] = value
        levels["1959-08"] = "130.90199999999999"
        levels["1959-09"] = "15.696999999999999"
        workbook = make_stub_workbook(
            monthly_through="2026-09",
            quarterly_through="2026Q3",
            core_pce_line_levels=levels,
        )
        parsed = parse_bea_workbook(workbook)
        row = parsed["monthly"][374]
        self.assertEqual(parsed.get("index_base"), "2017=100")
        self.assertEqual(row["indexes"]["1959-08"], "130.902")
        self.assertEqual(row["indexes"]["1959-09"], "15.697")
        for period, expected in levels.items():
            if period in {"1959-08", "1959-09"}:
                continue
            self.assertEqual(row["indexes"].get(period), expected)

    def test_survey_fallback_when_underlying_identity_fails(self) -> None:
        survey_levels = _bea_core_levels_through("2026-12", "132.000")
        survey = make_stub_survey_workbook(monthly_through="2026-12", core_pce_line_levels=survey_levels)
        workbook = make_stub_workbook(
            monthly_through="2026-12",
            quarterly_through="2026Q4",
            core_pce_line_levels=_bea_core_levels_through("2026-12"),
            core_pce_name="Not core PCE",
        )
        sources = OfficialSources(
            retrieved_at="2027-01-13T12:00:00+00:00",
            bea_url=BEA_URL,
            bea_body=workbook,
            bea_error=None,
            crosswalk_url="https://example/crosswalk",
            crosswalk_body=None,
            crosswalk_error="http_404",
            pcepilfe_url=PCEPILFE_URL,
            pcepilfe_csv=None,
            pcepilfe_error="transport_error",
            cpi_points=_cpi_points("2027-01", "2026-12"),
            cpi_error=None,
            cpi_requests_made=4,
            cpi_raw_sha256=hashlib.sha256(b"x").hexdigest(),
            ppi_fetched=None,
            ppi_error=None,
            survey_body=survey,
            survey_error=None,
        )
        bundle = build_cpi_packet("2027-01", sources, self.tempdir / "survey")
        self.assertEqual(bundle["status"], "READY")
        audit = json.loads((self.tempdir / "survey" / "source_audit.json").read_text(encoding="utf-8"))
        pcepilfe = next(row for row in audit["sources"] if row["name"] == "pcepilfe")
        self.assertEqual(pcepilfe["provenance"], "bea_survey_t20804_m")
        self.assertIn("2026-12-01,132.000", (self.tempdir / "survey" / "snapshot" / "pcepilfe.csv").read_text(encoding="utf-8"))

    def test_survey_vintage_mismatch_not_ready(self) -> None:
        survey = make_stub_survey_workbook(
            monthly_through="2026-12",
            core_pce_line_levels=_bea_core_levels_through("2026-12", "132.000"),
            published_text="Data published Nov 26, 2026",
        )
        workbook = make_stub_workbook(
            monthly_through="2026-12",
            quarterly_through="2026Q4",
            core_pce_line_levels=_bea_core_levels_through("2026-12"),
            core_pce_name="Wrong underlying label",
        )
        sources = OfficialSources(
            retrieved_at="2027-01-13T12:00:00+00:00",
            bea_url=BEA_URL,
            bea_body=workbook,
            bea_error=None,
            crosswalk_url="https://example/crosswalk",
            crosswalk_body=None,
            crosswalk_error="http_404",
            pcepilfe_url=PCEPILFE_URL,
            pcepilfe_csv=None,
            pcepilfe_error="transport_error",
            cpi_points=_cpi_points("2027-01", "2026-12"),
            cpi_error=None,
            cpi_requests_made=4,
            cpi_raw_sha256=hashlib.sha256(b"x").hexdigest(),
            ppi_fetched=None,
            ppi_error=None,
            survey_body=survey,
            survey_error=None,
        )
        bundle = build_cpi_packet("2027-01", sources, self.tempdir / "mismatch")
        self.assertEqual(bundle["status"], "NOT READY")
        self.assertIn("survey_vintage_mismatch", bundle["problems"])

    def test_ppi_uses_cpi_time_bea_baseline(self) -> None:
        sources = self._sources_jan2027()
        store = self.tempdir / "store"
        run_cpi_trigger("2027-01", self.tempdir / "cpi", sources, packet_store=store)
        baseline_path = store / "2027-01" / "frozen_cpi_packet.json"
        baseline_central = json.loads(baseline_path.read_text(encoding="utf-8"))["central_mom_percent"]
        registry = load_registry()
        priority = priority_ppi_series(registry)
        points = {series_id: {"2026-11": "100", "2026-12": "101"} for series_id in priority}
        points[priority[0]]["2026-12"] = "102"
        for series_id in priority[1:]:
            points[series_id].pop("2026-12", None)
        ppi_fetched = {
            "points": points,
            "requests_made": 1,
            "errors": [],
            "raw_documents": [{"status": "REQUEST_SUCCEEDED"}],
            "footnotes": {},
            "latest": {},
            "key_present": False,
        }
        fresh_csv_lines = []
        for line in _pcepilfe_csv("2026-12").splitlines():
            if line.startswith("2026-12-01,"):
                fresh_csv_lines.append("2026-12-01,999.999")
            else:
                fresh_csv_lines.append(line)
        fresh = self._sources_jan2027(pcepilfe_csv="\n".join(fresh_csv_lines) + "\n", pcepilfe_error=None)
        out = self.tempdir / "ppi"
        with mock.patch("scripts.core_pce_release.oneshot.fetch_series", return_value=ppi_fetched):
            run_ppi_trigger("2027-01", out, sources=fresh, packet_store=store, ppi_points_path=None)
        comment = (out / "comment.md").read_text(encoding="utf-8")
        self.assertNotIn("vintage_check_unavailable", comment)
        self.assertNotIn(SEPTEMBER_PRE, comment)
        self.assertNotIn(OCTOBER_PRE, comment)
        audit = json.loads((out / "audit.json").read_text(encoding="utf-8"))
        self.assertEqual(audit["offline_baseline"]["central_mom_percent"], baseline_central)

    def test_ppi_not_ready_without_packet_and_sources(self) -> None:
        sources = self._sources_jan2027()
        sources = OfficialSources(**{**sources.__dict__, "bea_body": None, "bea_error": "transport_error"})
        out = self.tempdir / "ppi-nopacket"
        run_ppi_trigger("2027-01", out, sources=sources, packet_store=None)
        comment = (out / "comment.md").read_text(encoding="utf-8")
        self.assertIn("NOT READY", comment)

    @mock.patch("scripts.core_pce_release.self_prepare.fetch_series")
    def test_fetch_official_sources_survey_only_when_needed(self, fetch_series_mock) -> None:
        fetch_series_mock.return_value = {
            "points": _cpi_points("2027-01", "2026-12"),
            "requests_made": 1,
            "errors": [],
            "raw_documents": [],
        }
        core_levels = _bea_core_levels_through("2026-12")
        workbook = make_stub_workbook(
            monthly_through="2026-12",
            quarterly_through="2026Q4",
            core_pce_line_levels=core_levels,
        )
        calls: list[tuple[str, float]] = []

        def transport(url: str, *, timeout: float):
            calls.append((url, timeout))
            if "fred" in url:
                raise TimeoutError
            if "Underlying" in url:
                return workbook, None
            if "Survey" in url:
                return b"survey-called", None
            if "FAQ521" in url or "crosswalk" in url:
                return None, "http_404"
            raise AssertionError(url)

        sources = fetch_official_sources("2027-01", transport=transport)
        self.assertIsNone(sources.survey_body)
        self.assertFalse(any("Survey" in url for url, _ in calls))

        bad_workbook = make_stub_workbook(monthly_through="2026-12", quarterly_through="2026Q4", core_pce_name="Wrong")
        calls.clear()

        def transport2(url: str, *, timeout: float):
            calls.append((url, timeout))
            if "fred" in url:
                return None, "transport_error"
            if "Underlying" in url:
                return bad_workbook, None
            if "Survey" in url:
                return b"survey", None
            if "FAQ521" in url or "crosswalk" in url:
                return None, "http_404"
            raise AssertionError(url)

        sources2 = fetch_official_sources("2027-01", transport=transport2)
        self.assertEqual(sources2.survey_body, b"survey")
        fred_timeouts = [timeout for url, timeout in calls if "fred" in url]
        self.assertEqual(fred_timeouts, [PCEPILFE_FETCH_TIMEOUT_SECONDS])


def _bundle_from_store(release: str, packet_dir: Path) -> dict:
    from scripts.core_pce_release.history import shift_month

    return {
        "release": release,
        "anchor_period": shift_month(release, -1),
        "snapshot_dir": packet_dir / "snapshot",
        "cpi_cache": packet_dir / "cpi_cache.json",
        "ppi_points": None,
        "registry": DATA / "series_registry.json",
        "component_history": packet_dir / "snapshot" / "bea_component_history.json",
        "reference": None,
        "locked_regression": False,
        "origin": "acquired",
        "status": "READY",
        "problems": [],
    }


if __name__ == "__main__":
    unittest.main()
