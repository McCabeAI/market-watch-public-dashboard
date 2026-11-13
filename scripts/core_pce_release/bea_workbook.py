"""Parse BEA Section2All_xls.xlsx with stdlib only."""

from __future__ import annotations

import hashlib
import re
import zipfile
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
from xml.etree import ElementTree as ET

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_PERIOD_MONTH = re.compile(r"^(\d{4})M(\d{2})$")
_PERIOD_QUARTER = re.compile(r"^(\d{4})Q([1-4])$")


def workbook_sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _col_letters(cell_ref: str) -> str:
    return "".join(ch for ch in cell_ref if ch.isalpha())


def _col_index(letters: str) -> int:
    index = 0
    for ch in letters:
        index = index * 26 + (ord(ch.upper()) - ord("A") + 1)
    return index - 1


def _parse_shared_strings(data: bytes) -> list[str]:
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return []
    strings: list[str] = []
    for si in root.findall("m:si", _NS):
        parts = [t.text or "" for t in si.findall(".//m:t", _NS)]
        strings.append("".join(parts))
    return strings


def _cell_value(cell: ET.Element, shared: list[str]) -> str | None:
    cell_type = cell.get("t")
    value_el = cell.find("m:v", _NS)
    if value_el is None or value_el.text is None:
        if cell_type == "inlineStr":
            is_el = cell.find("m:is/m:t", _NS)
            if is_el is not None and is_el.text is not None:
                return is_el.text
        return None
    raw = value_el.text
    if cell_type == "s":
        try:
            return shared[int(raw)]
        except (ValueError, IndexError):
            return raw
    if cell_type == "inlineStr":
        return raw
    return raw


def _sheet_rows(sheet_xml: bytes, shared: list[str]) -> dict[int, dict[int, str]]:
    try:
        root = ET.fromstring(sheet_xml)
    except ET.ParseError:
        return {}
    rows: dict[int, dict[int, str]] = {}
    for row in root.findall(".//m:sheetData/m:row", _NS):
        row_num = int(row.get("r", "0"))
        bucket: dict[int, str] = {}
        for cell in row.findall("m:c", _NS):
            ref = cell.get("r") or ""
            letters = _col_letters(ref)
            if not letters:
                continue
            col = _col_index(letters)
            value = _cell_value(cell, shared)
            if value is not None and value != "":
                bucket[col] = value
        if bucket:
            rows[row_num] = bucket
    return rows


def _sheet_path_map(zf: zipfile.ZipFile) -> dict[str, str]:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rid_to_target: dict[str, str] = {}
    for rel in rels:
        if rel.tag.endswith("Relationship"):
            rid_to_target[rel.get("Id", "")] = rel.get("Target", "")
    mapping: dict[str, str] = {}
    for sheet in workbook.findall("m:sheets/m:sheet", _NS):
        name = sheet.get("name")
        rid = sheet.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        if name and rid and rid in rid_to_target:
            target = rid_to_target[rid]
            if not target.startswith("/"):
                target = "xl/" + target.lstrip("/")
            mapping[name] = target
    return mapping


def _month_period(token: str) -> str | None:
    match = _PERIOD_MONTH.match(token.strip())
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2)}"


def _parse_numeric(value: str) -> Decimal | None:
    text = str(value).strip()
    if not text or text in {".", "..", "...", "…", "-", "—", "n/a", "NA"}:
        return None
    try:
        return Decimal(text)
    except Exception:
        return None


def _quant_index(value: str) -> str | None:
    number = _parse_numeric(value)
    if number is None:
        return None
    return str(number.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def _quant_millions(value: str) -> str | None:
    number = _parse_numeric(value)
    if number is None:
        return None
    rounded = int(number.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return str(rounded)


def _find_header_row(rows: dict[int, dict[int, str]], *, quarterly: bool) -> tuple[int, dict[int, str]] | None:
    token_re = _PERIOD_QUARTER if quarterly else _PERIOD_MONTH
    for row_num in sorted(rows):
        bucket = rows[row_num]
        for value in bucket.values():
            if token_re.match(str(value).strip()):
                return row_num, bucket
    return None


def _parse_data_sheet(
    rows: dict[int, dict[int, str]],
    *,
    quarterly: bool,
) -> tuple[dict, list[str]]:
    errors: list[str] = []
    header_info = _find_header_row(rows, quarterly=quarterly)
    if header_info is None:
        errors.append("bea_header_not_found")
        return {}, errors
    header_row, header = header_info
    period_by_col: dict[int, str] = {}
    for col, value in header.items():
        token = str(value).strip()
        if quarterly:
            match = _PERIOD_QUARTER.match(token)
            if match:
                period_by_col[col] = f"{match.group(1)}Q{match.group(2)}"
        else:
            period = _month_period(token)
            if period:
                period_by_col[col] = period

    parsed: dict[int, dict] = {}
    for row_num in sorted(rows):
        if row_num <= header_row:
            continue
        bucket = rows[row_num]
        line_raw = bucket.get(0)
        if line_raw is None:
            continue
        try:
            line = int(float(line_raw))
        except (ValueError, TypeError):
            continue
        name = bucket.get(1, "")
        series_code = bucket.get(2, "")
        values: dict[str, str] = {}
        for col, period in period_by_col.items():
            if col not in bucket:
                continue
            raw = bucket[col]
            if quarterly:
                quantized = _quant_millions(raw)
            else:
                quantized = _quant_index(raw)
            if quantized is None:
                continue
            values[period] = quantized
        if not values:
            continue
        if quarterly:
            parsed[line] = {"name": str(name).strip(), "series_code": str(series_code).strip(), "quarters": values}
        else:
            parsed[line] = {"name": str(name).strip(), "series_code": str(series_code).strip(), "indexes": values}
    return parsed, errors


def _find_index_base(rows: dict[int, dict[int, str]]) -> str | None:
    needle = "2017=100"
    for row_num in sorted(rows)[:25]:
        bucket = rows[row_num]
        for value in bucket.values():
            collapsed = re.sub(r"\s+", "", str(value))
            search = 0
            while True:
                idx = collapsed.find(needle, search)
                if idx == -1:
                    break
                end = idx + len(needle)
                if end < len(collapsed) and collapsed[end].isdigit():
                    search = idx + 1
                    continue
                return "2017=100"
    return None


def _metadata_from_sheet(rows: dict[int, dict[int, str]]) -> tuple[str | None, str | None]:
    published: str | None = None
    file_created: str | None = None
    for row_num in sorted(rows)[:12]:
        bucket = rows[row_num]
        for value in bucket.values():
            text = str(value)
            if "Data published" in text:
                published = text.replace("Data published", "").strip().lstrip(":").strip()
            elif "File created" in text:
                file_created = text.replace("File created", "").strip().lstrip(":").strip()
    return published, file_created


def parse_bea_monthly_sheet(body: bytes, sheet_name: str) -> dict:
    """Parse one monthly price-index sheet (e.g. U20404-M or T20804-M)."""
    digest = workbook_sha256(body)
    errors: list[str] = []
    monthly: dict = {}
    published: str | None = None
    file_created: str | None = None
    index_base: str | None = None
    try:
        with zipfile.ZipFile(BytesIO(body)) as zf:
            shared = _parse_shared_strings(zf.read("xl/sharedStrings.xml")) if "xl/sharedStrings.xml" in zf.namelist() else []
            paths = _sheet_path_map(zf)
            if sheet_name not in paths:
                errors.append(f"bea_sheet_missing:{sheet_name}")
            else:
                rows = _sheet_rows(zf.read(paths[sheet_name]), shared)
                pub, created = _metadata_from_sheet(rows)
                published = pub or published
                file_created = created or file_created
                index_base = _find_index_base(rows)
                monthly, parse_errors = _parse_data_sheet(rows, quarterly=False)
                errors.extend(parse_errors)
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        errors.append(f"bea_workbook_unreadable:{type(exc).__name__}")
    return {
        "sha256": digest,
        "published": published,
        "file_created": file_created,
        "index_base": index_base,
        "monthly": monthly,
        "errors": errors,
    }


def parse_bea_workbook(body: bytes) -> dict:
    """Return sha256, published, file_created, monthly, quarterly, errors."""
    digest = workbook_sha256(body)
    errors: list[str] = []
    monthly: dict = {}
    quarterly: dict = {}
    published: str | None = None
    file_created: str | None = None
    index_base: str | None = None
    try:
        with zipfile.ZipFile(BytesIO(body)) as zf:
            shared = _parse_shared_strings(zf.read("xl/sharedStrings.xml")) if "xl/sharedStrings.xml" in zf.namelist() else []
            paths = _sheet_path_map(zf)
            monthly_name = "U20404-M"
            quarterly_name = "U20405-Q"
            if monthly_name not in paths:
                errors.append(f"bea_sheet_missing:{monthly_name}")
            else:
                rows = _sheet_rows(zf.read(paths[monthly_name]), shared)
                pub, created = _metadata_from_sheet(rows)
                published = pub or published
                file_created = created or file_created
                index_base = _find_index_base(rows)
                monthly, parse_errors = _parse_data_sheet(rows, quarterly=False)
                errors.extend(parse_errors)
            if quarterly_name not in paths:
                errors.append(f"bea_sheet_missing:{quarterly_name}")
            else:
                rows = _sheet_rows(zf.read(paths[quarterly_name]), shared)
                quarterly, parse_errors = _parse_data_sheet(rows, quarterly=True)
                errors.extend(parse_errors)
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        errors.append(f"bea_workbook_unreadable:{type(exc).__name__}")
    return {
        "sha256": digest,
        "published": published,
        "file_created": file_created,
        "index_base": index_base,
        "monthly": monthly,
        "quarterly": quarterly,
        "errors": errors,
    }
