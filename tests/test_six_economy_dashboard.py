from __future__ import annotations

import copy
import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

from scripts.apply_six_economy_dashboard import (
    COUNTRY_PAGE_END,
    NZ_CDETAIL_CLOSE,
    apply_six_economy_dashboard,
)
from scripts.apply_temperature_scores import apply_scores
from scripts.dashboard_mini_cards import PLACEHOLDER_VALUES, mini_rows_for_country
from scripts.temperature_level import period_sort_key

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_V3 = Path(__file__).resolve().parent / "fixtures" / "temperature_scores_v3_minimal.json"
_SOURCE_PERIOD = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2]|Q[1-4])$")
_ACTIVITY_SOURCE_PREFERENCE = (
    ("business_surveys", "Business surveys", False),
    ("gdp_domestic_demand", "Domestic demand", True),
)
_INFLATION_LABELS = {"EA": "HICP / core", "JP": "CPI / core"}


def _frozen_mini_country(country: str) -> dict:
    """Synthetic component state. Numbers are not a production vintage."""
    return {
        "countries": {
            country: {
                "Inflation": {
                    "as_of": "2024-06",
                    "component_state": {
                        "headline": {
                            "observed": True,
                            "transform_value": 1.25,
                            "as_of": "2024-06",
                        },
                        "underlying": {
                            "observed": True,
                            "transform_value": 4.5,
                            "as_of": "2024-05",
                        },
                    },
                },
                "Labor": {
                    "as_of": "2024-06",
                    "component_state": {
                        "unemployment": {
                            "observed": True,
                            "transform_value": 6,
                            "as_of": "2024-06",
                        }
                    },
                },
                "Activity": {
                    "as_of": "2024-Q2",
                    "component_state": {
                        "business_surveys": {
                            "observed": True,
                            "transform_value": 49.5,
                            "as_of": "2024-06",
                        },
                        "gdp_domestic_demand": {
                            "observed": True,
                            "transform_value": 9.99,
                            "as_of": "2024-Q2",
                        },
                    },
                },
            }
        }
    }


def _current_activity_source(activity_state: dict) -> tuple[str, str, bool, dict]:
    component_state = activity_state.get("component_state") or {}
    for name, label, percent in _ACTIVITY_SOURCE_PREFERENCE:
        component = component_state.get(name) or {}
        if component.get("observed") and component.get("transform_value") is not None:
            return name, label, percent, component
    raise AssertionError("activity mini row has no observed current source")


def _assert_displays_current_number(test: unittest.TestCase, text: str, value: float, *, percent: bool) -> None:
    if percent:
        test.assertTrue(text.endswith("%"), text)
        test.assertNotIn(" / ", text)
        displayed = float(text[:-1])
    else:
        test.assertFalse(text.endswith("%"), text)
        displayed = float(text)
    test.assertAlmostEqual(displayed, round(float(value), 4), places=4)
    test.assertNotIn(text.strip(), PLACEHOLDER_VALUES)


class _CdetailStackParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stack: list[tuple[str, str | None]] = []
        self.cdetail_parent: dict[str, str | None] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "div":
            return
        classes = dict(attrs).get("class") or ""
        klass = classes if isinstance(classes, str) else " ".join(classes)
        cdetail_key = None
        for token in klass.split():
            if token in {"us", "ca", "au", "nz", "ea", "jp"} and "cdetail" in klass:
                cdetail_key = token
                break
        parent = None
        for entry in reversed(self.stack):
            if entry[1] is not None:
                parent = entry[1]
                break
        if cdetail_key:
            self.cdetail_parent[cdetail_key] = parent
        self.stack.append((tag, cdetail_key))

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self.stack:
            self.stack.pop()


def _tiny_country_page_fixture() -> str:
    css_label = (
        "#c-us:checked~.app label[for=c-us],#c-ca:checked~.app label[for=c-ca],"
        "#c-au:checked~.app label[for=c-au],#c-nz:checked~.app label[for=c-nz]"
        "{background:var(--navy);color:#fff;border-color:var(--navy)}"
    )
    css_detail = (
        "#c-us:checked~.app .cdetail.us,#c-ca:checked~.app .cdetail.ca,"
        "#c-au:checked~.app .cdetail.au,#c-nz:checked~.app .cdetail.nz{display:block}"
    )
    board_css = ".board{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin-bottom:12px}"
    switch_anchor = (
        '<label for="c-us">United States</label>'
        '<label for="c-ca">Canada</label>'
        '<label for="c-au">Australia</label>'
        '<label for="c-nz">New Zealand</label>'
    )
    nz_jump = '<label class="jump" for="c-nz">Open NZ detail</label>\n</div>\n</div>'
    return f"""<html><style>{css_label}
{css_detail}
{board_css}
</style>
<section class="page country">
<input id="c-nz" name="country" type="radio"/>
<div class="board">{switch_anchor}
<div class="card"><h3>NEW ZEALAND</h3>{nz_jump}
<div class="cdetail us"></div>
<div class="cdetail nz"><span>nz-inner</span>{COUNTRY_PAGE_END}
"""


def _pipeline_html() -> str:
    import base64
    import gzip

    chunks = b"".join(Path(p).read_bytes() for p in sorted(ROOT.glob("payload_v6/part*.b64")))
    html = gzip.decompress(base64.b64decode(chunks)).decode("utf-8")
    css = (ROOT / "patch_v7" / "last24.css").read_text(encoding="utf-8")
    last24 = (ROOT / "patch_v7").glob("last24_*.html")
    last24_html = "".join(Path(p).read_text(encoding="utf-8") for p in sorted(last24))
    anchor = '<div class="stitle">Top Market Drivers</div>'
    html = html.replace("</style>", css + "\n</style>", 1)
    html = html.replace(anchor, "\n" + last24_html + anchor, 1)
    rollup = (ROOT / "patch_v9" / "news_rollup.html").read_text(encoding="utf-8")
    start = '<div class="stitle">Top Market Drivers</div>'
    end = '<div class="x-signal">'
    a = html.index(start)
    b = html.index(end, a)
    html = html[:a] + rollup + html[b:]
    html = apply_six_economy_dashboard(html)
    css_v8 = (ROOT / "patch_v8" / "temp_scores.css").read_text(encoding="utf-8")
    html = html.replace("</style>", css_v8 + "\n</style>", 1)
    for key in ("us", "ca", "au", "nz", "ea", "jp"):
        anchor_tag = f'<div class="cdetail {key}">'
        block = (ROOT / "patch_v8" / f"{key}.html").read_text(encoding="utf-8")
        html = html.replace(anchor_tag, anchor_tag + "\n" + block, 1)
    return html


class SixEconomyDashboardTest(unittest.TestCase):
    def test_cdetail_insertion_after_nz_close_on_tiny_fixture(self) -> None:
        html = apply_six_economy_dashboard(_tiny_country_page_fixture())
        self.assertRegex(
            html,
            r'<div class="cdetail nz"><span>nz-inner</span></div>\s*<div class="cdetail ea">',
        )
        self.assertNotIn(
            '<div class="cdetail nz"><span>nz-inner</span><div class="cdetail ea">',
            html,
        )

    def test_ea_jp_cdetail_are_siblings_not_inside_nz(self) -> None:
        html = _pipeline_html()
        parser = _CdetailStackParser()
        parser.feed(html)
        self.assertIsNone(parser.cdetail_parent.get("ea"))
        self.assertIsNone(parser.cdetail_parent.get("jp"))
        self.assertIsNone(parser.cdetail_parent.get("us"))
        self.assertNotEqual(parser.cdetail_parent.get("ea"), "nz")
        self.assertNotEqual(parser.cdetail_parent.get("jp"), "nz")

    def test_four_drawers_per_country_block(self) -> None:
        html = _pipeline_html()
        state = json.loads(FIXTURE_V3.read_text(encoding="utf-8"))
        html = apply_scores(html, state)
        self.assertEqual(html.count('class="temp-dimension score-detail"'), 24)
        for key in ("us", "ca", "au", "nz", "ea", "jp"):
            anchor = f'<div class="cdetail {key}">'
            start = html.index(anchor)
            later = [
                html.find(f'<div class="cdetail {other}">', start + len(anchor))
                for other in ("us", "ca", "au", "nz", "ea", "jp")
                if other != key
            ]
            end = min(i for i in later if i != -1) if any(i != -1 for i in later) else len(html)
            block = html[start:end]
            self.assertEqual(block.count('class="temp-dimension score-detail"'), 4)

    def test_ea_jp_mini_values_not_placeholders_from_fixture(self) -> None:
        html = _pipeline_html()
        state = json.loads(FIXTURE_V3.read_text(encoding="utf-8"))
        out = apply_scores(html, state)
        for heading in ("EURO AREA", "JAPAN"):
            match = re.search(
                rf"<h3>{heading}</h3>.*?<div class=\"mini\">(.*?)</div>\s*<label class=\"jump\"",
                out,
                flags=re.S,
            )
            self.assertIsNotNone(match, heading)
            for value in re.findall(r"<b>([^<]*)</b>", match.group(1)):
                self.assertNotIn(value.strip(), PLACEHOLDER_VALUES, msg=heading)

    def test_jp_rendered_detail_does_not_carry_new_zealand_prototype_evidence(self) -> None:
        html = _pipeline_html()
        state = json.loads(FIXTURE_V3.read_text(encoding="utf-8"))
        html = apply_scores(html, state)
        start = html.index('<div class="cdetail jp">')
        end = html.find('</section>', start)
        block = html[start:end]
        self.assertNotIn("Stats NZ", block)
        self.assertNotIn("ANZ source", block)
        self.assertNotIn(">98.0<", block)
        self.assertIn("stale prototype evidence is intentionally suppressed", block)

    def test_mini_rows_mapping_fixture(self) -> None:
        state = json.loads(FIXTURE_V3.read_text(encoding="utf-8"))
        ea_rows = dict(mini_rows_for_country(state, "EA"))
        self.assertEqual(ea_rows["HICP / core"], "3.2% / 2.4%")
        self.assertEqual(ea_rows["Unemployment"], "6.4%")
        self.assertEqual(ea_rows["Business surveys"], "51.3333")
        jp_rows = dict(mini_rows_for_country(state, "JP"))
        self.assertEqual(jp_rows["CPI / core"], "2% / 1.7%")
        self.assertEqual(jp_rows["Unemployment"], "2.4%")
        self.assertEqual(jp_rows["Domestic demand"], "1.65%")

    def test_mini_rows_mapping_frozen_synthetic(self) -> None:
        """Exact mini-card strings come from frozen inputs, not the live vintage."""
        for country, inflation_label in _INFLATION_LABELS.items():
            rows = dict(mini_rows_for_country(_frozen_mini_country(country), country))
            self.assertEqual(rows[inflation_label], "1.25% / 4.5%")
            self.assertEqual(rows["Unemployment"], "6%")
            self.assertEqual(rows["Business surveys"], "49.5")
            self.assertNotIn("Domestic demand", rows)
            self.assertNotIn("9.99", rows["Business surveys"])

        fallback = _frozen_mini_country("EA")
        surveys = fallback["countries"]["EA"]["Activity"]["component_state"]["business_surveys"]
        surveys["observed"] = False
        fallback_rows = dict(mini_rows_for_country(fallback, "EA"))
        self.assertEqual(fallback_rows["Domestic demand"], "9.99%")
        self.assertNotIn("Business surveys", fallback_rows)

        missing = _frozen_mini_country("EA")
        missing["countries"]["EA"]["Inflation"]["component_state"]["headline"]["observed"] = False
        with self.assertRaises(ValueError):
            mini_rows_for_country(missing, "EA")

    def test_mini_rows_mapping_live_state(self) -> None:
        """Live EA/JP cards follow the current observed source, whatever the vintage prints."""
        from scripts.apply_temperature_scores import load_state

        state = load_state()
        for country, inflation_label in _INFLATION_LABELS.items():
            block = state["countries"][country]
            rows = mini_rows_for_country(state, country)
            self.assertEqual(len(rows), 3)
            labels = [label for label, _ in rows]
            values = dict(rows)

            inflation = block["Inflation"]
            headline = inflation["component_state"]["headline"]
            underlying = inflation["component_state"]["underlying"]
            self._assert_current_source(headline, inflation["as_of"], f"{country} headline")
            self._assert_current_source(underlying, inflation["as_of"], f"{country} underlying")
            left, right = values[inflation_label].split(" / ")
            self.assertEqual(labels[0], inflation_label)
            _assert_displays_current_number(self, left, headline["transform_value"], percent=True)
            _assert_displays_current_number(self, right, underlying["transform_value"], percent=True)

            labor = block["Labor"]
            unemployment = labor["component_state"]["unemployment"]
            self._assert_current_source(unemployment, labor["as_of"], f"{country} unemployment")
            self.assertEqual(labels[1], "Unemployment")
            _assert_displays_current_number(
                self,
                values["Unemployment"],
                unemployment["transform_value"],
                percent=True,
            )

            activity_name, activity_label, activity_percent, activity = _current_activity_source(
                block["Activity"]
            )
            self._assert_current_source(activity, block["Activity"]["as_of"], f"{country} {activity_name}")
            self.assertEqual(labels[2], activity_label)
            _assert_displays_current_number(
                self,
                values[activity_label],
                activity["transform_value"],
                percent=activity_percent,
            )
            for value in values.values():
                self.assertNotIn(value.strip(), PLACEHOLDER_VALUES)

        ea_headline = state["countries"]["EA"]["Inflation"]["component_state"]["headline"]
        sentinel = round(float(ea_headline["transform_value"]) + 10.0, 4)
        probed = copy.deepcopy(state)
        probed["countries"]["EA"]["Inflation"]["component_state"]["headline"]["transform_value"] = sentinel
        probed_rows = dict(mini_rows_for_country(probed, "EA"))
        live_rows = dict(mini_rows_for_country(state, "EA"))
        self.assertNotEqual(probed_rows["HICP / core"], live_rows["HICP / core"])
        probed_headline, _probed_underlying = probed_rows["HICP / core"].split(" / ")
        _assert_displays_current_number(self, probed_headline, sentinel, percent=True)

        activity_state = state["countries"]["EA"]["Activity"]["component_state"]
        surveys = activity_state.get("business_surveys") or {}
        gdp = activity_state.get("gdp_domestic_demand") or {}
        if (
            surveys.get("observed")
            and surveys.get("transform_value") is not None
            and gdp.get("observed")
            and gdp.get("transform_value") is not None
        ):
            surveys_off = copy.deepcopy(state)
            surveys_off["countries"]["EA"]["Activity"]["component_state"]["business_surveys"]["observed"] = False
            fallback_rows = dict(mini_rows_for_country(surveys_off, "EA"))
            self.assertIn("Domestic demand", fallback_rows)
            self.assertNotIn("Business surveys", fallback_rows)
            _assert_displays_current_number(
                self,
                fallback_rows["Domestic demand"],
                gdp["transform_value"],
                percent=True,
            )

    def _assert_current_source(self, component: dict, dimension_as_of: str, label: str) -> None:
        self.assertTrue(component.get("observed"), label)
        as_of = component.get("as_of")
        self.assertIsInstance(as_of, str, label)
        self.assertRegex(as_of, _SOURCE_PERIOD, label)
        self.assertRegex(str(dimension_as_of), _SOURCE_PERIOD, label)
        self.assertLessEqual(period_sort_key(as_of), period_sort_key(str(dimension_as_of)), label)
        self.assertIsNotNone(component.get("transform_value"), label)


if __name__ == "__main__":
    unittest.main()
