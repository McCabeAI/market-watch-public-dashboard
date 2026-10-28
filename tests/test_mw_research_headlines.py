"""Research headline selection and rendering (real Oct 27 packet + synthetic mutations)."""

from __future__ import annotations

import copy
import json
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from scripts.market_watch_launch import research_headlines as rh
from scripts.market_watch_launch.publication_release import format_et
from scripts.overnight.accepted_news import effective_public_news_context
from scripts.overnight.news_cluster import _same_event, _stable_id
from scripts.overnight.news_relevance import score_transmission
from scripts.overnight.news_sources import REUTERS_SURFACE
from scripts.overnight.store import OvernightStore

REPO = Path(__file__).resolve().parents[1]
FIXTURE_COMMIT = "e9f757d7d6ae83e6c017fd9f95a1da40addda9ad"
PACKET_SHA = "74b06c13f1215b6521678c764356cae8ae2788e19bad038dad0a79f7e35f2109"
FROZEN_AT = "2026-10-27T05:32:12.602790-04:00"
PREV_AS_OF = "2026-10-26T07:37:10.682323-04:00"

PINNED_ITEMS = [
    ("news:3f5406490f809d1a", "CNBC", "2026-10-27T05:09:01-04:00", "Oil prices seesaw amid renewed diplomatic efforts to end Mideast conflict"),
    ("news:de75f7dc279048ff", "Bank of Japan", "2026-10-27T01:00:00-04:00", "Indicators for Core CPI"),
    (
        "news:0ea2c447c7cee9bf",
        "CNBC",
        "2026-10-26T20:17:44-04:00",
        "Bank of Japan is expected to hold rates this week — but stay hawkish: CNBC survey",
    ),
    (
        "news:8e25112a3bbfefef",
        "Bloomberg",
        "2026-10-26T15:00:00-04:00",
        "BlackRock’s Rieder Spent Weekend Doing Deals in AI Debt Rush",
    ),
    (
        "news:5de8c9d374ec450e",
        "Bloomberg",
        "2026-10-26T13:00:00-04:00",
        "South Korea’s AI Fund Offers ‘Fiscal Dam’ Against Higher Yields",
    ),
    (
        "news:b47f6d29c772ee8c",
        "Reuters",
        "2026-10-26T13:00:00-04:00",
        "Bond market is a buy right now, JP Morgan Asset Management's fixed income head says",
    ),
]
PINNED_REJECTED = {"out_of_window": 5, "unattributed": 13}


def _git_show(path: str) -> bytes:
    return subprocess.check_output(["git", "show", f"{FIXTURE_COMMIT}:{path}"], cwd=REPO)


def _load_fixture() -> tuple[dict, list]:
    if subprocess.run(["git", "cat-file", "-e", f"{FIXTURE_COMMIT}^{{commit}}"], cwd=REPO, check=False).returncode != 0:
        raise unittest.SkipTest(f"fixture commit {FIXTURE_COMMIT} missing")
    snap = json.loads(_git_show("data/overnight/runs/overnight-20261027/reviews/review-001/evidence_snapshot.json"))
    dataset = json.loads(_git_show("data/overnight/runs/overnight-20261026/assembled_dataset.json"))
    ctx = effective_public_news_context(OvernightStore(root=REPO), dataset)
    return snap["families"]["news"], list(ctx.get("news") or [])


def _select(family: dict, accepted=(), **kwargs):
    params = {
        "frozen_at": FROZEN_AT,
        "previous_accepted_as_of": PREV_AS_OF,
        "previous_accepted_items": list(accepted or ()),
        "packet_sha256": PACKET_SHA,
    }
    params.update(kwargs)
    return rh.select_current_headlines(family, **params)


def _one_item_family(family: dict, item: dict) -> dict:
    base = copy.deepcopy(family)
    base["items"] = [copy.deepcopy(item)]
    return base


def _single_edge_item(template: dict, **edge_overrides) -> dict:
    item = copy.deepcopy(template)
    edge = copy.deepcopy(item["source_edges"][0])
    headline = edge_overrides.pop("headline", None)
    edge.update(edge_overrides)
    if headline is not None:
        item["headline"] = headline
        edge["headline"] = headline
    item["source_edges"] = [edge]
    item["id"] = _stable_id(item["source_edges"])
    return item


def _chosen_fields(family: dict, template: dict, *, accepted=()) -> dict:
    out = _select(_one_item_family(family, template), accepted)
    if out.get("counts", {}).get("eligible") != 1 or not out.get("items"):
        raise AssertionError(f"expected one eligible item, got {out}")
    return out["items"][0]


def _eligible_template(family: dict, accepted: list) -> dict:
    out = _select(family, accepted)
    self_assert = out["status"] == "available" and out["items"]
    if not self_assert:
        raise unittest.SkipTest("no eligible template in fixture")
    item_id = out["items"][0]["id"]
    for raw in family["items"]:
        if raw.get("id") == item_id:
            return copy.deepcopy(raw)
    raise AssertionError("template missing")


class RealPacketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.family, cls.accepted = _load_fixture()

    def test_real_packet_pins_kept_headlines_and_rejected_counts(self):
        out = _select(self.family, self.accepted)
        self.assertEqual(out["status"], "available")
        self.assertIsNone(out["reason"])
        self.assertEqual(out["counts"]["rejected"], PINNED_REJECTED)
        self.assertEqual(len(out["items"]), len(PINNED_ITEMS))
        for row, pinned in zip(out["items"], PINNED_ITEMS):
            self.assertEqual((row["id"], row["source_name"], row["published_at"], row["headline"]), pinned)


class SyntheticRejectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.family, cls.accepted = _load_fixture()
        cls.template = _eligible_template(cls.family, cls.accepted)

    def test_edge_and_item_rejection_reasons(self):
        template = self.template

        out = _select(_one_item_family(self.family, _single_edge_item(template, url="http://www.bloomberg.com/x")), self.accepted)
        self.assertEqual(out["counts"]["rejected"].get("unattributed"), 1)

        out = _select(
            _one_item_family(
                self.family,
                _single_edge_item(template, source_name="CNBC", url="https://www.bloomberg.com/news/articles/x"),
            ),
            self.accepted,
        )
        self.assertEqual(out["counts"]["rejected"].get("unattributed"), 1)

        out = _select(_one_item_family(self.family, _single_edge_item(template, source_name="Unknown Publisher")), self.accepted)
        self.assertEqual(out["counts"]["rejected"].get("unattributed"), 1)

        out = _select(
            _one_item_family(
                self.family,
                _single_edge_item(
                    template,
                    source_name="Reuters",
                    url="https://www.reuters.com/world/research-headlines-test",
                    discovery_surface=REUTERS_SURFACE,
                ),
            ),
            self.accepted,
        )
        self.assertEqual(out["counts"]["rejected"].get("rejected_source"), 1)

        out = _select(_one_item_family(self.family, _single_edge_item(template, discovery_surface=None)), self.accepted)
        self.assertEqual(out["counts"]["rejected"].get("unverified_source"), 1)

        for published in (None, "", "2026-10-27T05:00:00"):
            out = _select(_one_item_family(self.family, _single_edge_item(template, published_at=published)), self.accepted)
            self.assertEqual(out["counts"]["rejected"].get("undated"), 1)

        out = _select(_one_item_family(self.family, _single_edge_item(template, published_at="2026-10-27T06:00:00-04:00")), self.accepted)
        self.assertEqual(out["counts"]["rejected"].get("future_dated"), 1)

        out = _select(_one_item_family(self.family, _single_edge_item(template, published_at="2026-10-25T12:00:00-04:00")), self.accepted)
        self.assertEqual(out["counts"]["rejected"].get("out_of_window"), 1)

        item = copy.deepcopy(self.template)
        item["verification_status"] = "unverified"
        out = _select(_one_item_family(self.family, item), self.accepted)
        self.assertEqual(out["counts"]["rejected"].get("unverified"), 1)

        low = _single_edge_item(template)
        low["transmission"] = {**(low.get("transmission") or {}), "disposition": "suppress"}
        out = _select(_one_item_family(self.family, low), self.accepted)
        self.assertEqual(out["counts"]["rejected"].get("low_relevance"), 1)

        item = copy.deepcopy(self.template)
        item["id"] = "news:deadbeefdeadbeef"
        out = _select(_one_item_family(self.family, item), self.accepted)
        self.assertEqual(out["counts"]["rejected"].get("identity_mismatch"), 1)

        item = {"id": "news:bad", "headline": "x", "source_edges": []}
        out = _select(_one_item_family(self.family, item), self.accepted)
        self.assertEqual(out["counts"]["rejected"].get("malformed"), 1)

        a = copy.deepcopy(self.template)
        b = copy.deepcopy(self.template)
        family = _one_item_family(self.family, a)
        family["items"] = [a, b]
        out = _select(family, self.accepted)
        self.assertEqual(out["counts"]["rejected"].get("duplicate"), 1)

        dup = _single_edge_item(
            template,
            headline=self.template["headline"].upper(),
            url="https://www.cnbc.com/duplicate-test-headline",
        )
        family = _one_item_family(self.family, self.template)
        family["items"] = [self.template, dup]
        out = _select(family, self.accepted)
        self.assertEqual(out["counts"]["rejected"].get("duplicate"), 1)

        eligible = [
            copy.deepcopy(raw)
            for raw in self.family["items"]
            if _select(_one_item_family(self.family, raw), []).get("counts", {}).get("eligible") == 1
        ]
        self.assertGreaterEqual(len(eligible), 5)
        family = copy.deepcopy(self.family)
        family["items"] = eligible[:5]
        with mock.patch.object(rh, "MAX_HEADLINES", 3):
            out = _select(family, [])
        self.assertEqual(len(out["items"]), 3)
        self.assertEqual(out["counts"]["rejected"].get("over_cap"), 2)


class AlreadyAcceptedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.family, _ = _load_fixture()
        cls.template = _eligible_template(cls.family, [])

    def _reject_already_accepted(self, accepted_row: dict) -> None:
        out = _select(_one_item_family(self.family, copy.deepcopy(self.template)), [accepted_row])
        self.assertEqual(out["counts"]["rejected"].get("already_accepted"), 1)
        self.assertEqual(out["items"], [])

    def test_already_accepted_by_url(self):
        chosen_url = _chosen_fields(self.family, self.template, accepted=[])["url"]
        self._reject_already_accepted({"url": chosen_url, "headline": "Unrelated accepted headline"})

    def test_already_accepted_by_source_edge_url(self):
        chosen_url = _chosen_fields(self.family, self.template, accepted=[])["url"]
        self._reject_already_accepted({"source_edges": [{"url": chosen_url}]})

    def test_already_accepted_by_same_event_headline(self):
        chosen = _chosen_fields(self.family, self.template, accepted=[])
        near_headline = chosen["headline"] + "."
        self.assertTrue(_same_event(chosen["headline"], near_headline))
        self.assertNotEqual(
            chosen["url"],
            "https://www.cnbc.com/accepted-near-duplicate-headline",
        )
        self._reject_already_accepted(
            {
                "headline": near_headline,
                "url": "https://www.cnbc.com/accepted-near-duplicate-headline",
            }
        )


class LowRelevanceRecomputeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.family, _ = _load_fixture()
        cls.template = _eligible_template(cls.family, [])

    def test_low_relevance_when_recomputed_score_suppresses_frozen_show(self):
        suppress_headline = "Random local sports game tonight"
        scored = score_transmission(suppress_headline, "")
        self.assertIn(scored["disposition"], ("suppress", "hold-for-review"))
        item = _single_edge_item(self.template, headline=suppress_headline, url="https://www.cnbc.com/low-relevance-recompute")
        item["transmission"] = {**(item.get("transmission") or {}), "disposition": "show"}
        out = _select(_one_item_family(self.family, item), [])
        self.assertEqual(out["counts"]["rejected"].get("low_relevance"), 1)
        self.assertEqual(out["items"], [])


class WindowSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.family, _ = _load_fixture()
        cls.template = _eligible_template(cls.family, [])

    def test_no_window_after_previous_acceptance_when_prior_meets_cutoff(self):
        cutoff = self.family["acquisition"]["cutoff"]
        for previous in (cutoff, "2026-10-27T06:00:00-04:00"):
            with self.subTest(previous=previous):
                out = _select(self.family, [], previous_accepted_as_of=previous)
                self.assertEqual((out["status"], out["reason"]), ("empty", "no_window_after_previous_acceptance"))
                self.assertEqual(out["items"], [])

    def test_window_boundary_start_out_cutoff_in(self):
        window = _select(self.family, [])["window"]
        start = window["start"]
        cutoff = window["end"]
        at_start = _select(
            _one_item_family(self.family, _single_edge_item(self.template, published_at=start)),
            [],
        )
        self.assertEqual(at_start["counts"]["rejected"].get("out_of_window"), 1)
        self.assertEqual(at_start["items"], [])
        at_cutoff = _select(
            _one_item_family(self.family, _single_edge_item(self.template, published_at=cutoff)),
            [],
        )
        self.assertEqual(at_cutoff["counts"]["eligible"], 1)
        self.assertEqual(len(at_cutoff["items"]), 1)


class FamilyLevelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.family, cls.accepted = _load_fixture()

    def test_family_unavailable_reasons(self):
        for mutate, reason in (
            (lambda f: None, "news_family_missing"),
            (lambda f: {**f, "status": "stale"}, "news_family_not_fresh"),
            (lambda f: {**f, "acquisition": {"mode": "fixture"}}, "news_acquisition_not_live"),
            (lambda f: {**f, "acquisition": {**f["acquisition"], "cutoff": "bad"}}, "news_cutoff_invalid"),
            (lambda f: {**f, "acquisition": {**f["acquisition"], "cutoff": "2026-10-27T06:00:00-04:00"}}, "news_cutoff_after_freeze"),
            (lambda f: {**f, "acquisition": {**f["acquisition"], "cutoff": "2026-10-26T00:00:00-04:00"}}, "news_cutoff_stale"),
            (lambda f: {**f, "items": "nope"}, "news_items_malformed"),
            (lambda f: {**f, "digest": ""}, "news_family_digest_missing"),
        ):
            with self.subTest(reason=reason):
                payload = mutate(copy.deepcopy(self.family)) if mutate is not None else None
                out = _select(payload, self.accepted)
                self.assertEqual((out["status"], out["reason"]), ("unavailable", reason))

    def test_all_rejected_yields_empty(self):
        family = copy.deepcopy(self.family)
        family["items"] = []
        out = _select(family, self.accepted)
        self.assertEqual((out["status"], out["reason"]), ("empty", "no_eligible_headlines"))


class DeterminismTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.family, cls.accepted = _load_fixture()

    def test_deterministic_and_non_mutating(self):
        before = json.dumps(self.family, sort_keys=True)
        a = _select(self.family, self.accepted)
        after = json.dumps(self.family, sort_keys=True)
        self.assertEqual(before, after)
        b = _select(self.family, self.accepted)
        self.assertEqual(a, b)


class RenderTests(unittest.TestCase):
    def test_render_escapes_query_url_in_href(self):
        news = {"as_of": PREV_AS_OF, "age_label": "21 h before this freeze", "overnight_run_id": "overnight-20261026"}
        url = "https://www.cnbc.com/2026/10/27/story?a=1&b=2"
        panel = rh.render_headlines_panel(
            {
                "status": "available",
                "as_of": FROZEN_AT,
                "packet_sha256": PACKET_SHA,
                "window": {"start": PREV_AS_OF, "end": FROZEN_AT, "basis": "previous_acceptance"},
                "items": [
                    {
                        "id": "news:query",
                        "headline": "Query URL headline",
                        "source_name": "CNBC",
                        "url": url,
                        "published_at": "2026-10-27T04:00:00-04:00",
                        "channel": "global_risk",
                    }
                ],
            },
            previous_news=news,
            panel="news",
            limit=rh.MAX_HEADLINES,
        )
        from scripts.market_watch_launch.publication_release import _esc

        self.assertIn(f'href="{_esc(url)}"', panel)
        self.assertIn("&amp;", panel)

    def test_render_available_empty_unavailable_and_note(self):
        news = {"as_of": PREV_AS_OF, "age_label": "21 h before this freeze", "overnight_run_id": "overnight-20261026"}
        available = {
            "status": "available",
            "as_of": FROZEN_AT,
            "packet_sha256": PACKET_SHA,
            "window": {"start": PREV_AS_OF, "end": FROZEN_AT, "basis": "previous_acceptance"},
            "items": [
                {
                    "id": f"news:{idx:04d}",
                    "headline": "<script>alert(1)</script>" if idx == 0 else f"Headline {idx}",
                    "source_name": "Bloomberg",
                    "url": f"https://www.bloomberg.com/x{idx}",
                    "published_at": f"2026-10-27T0{4-idx}:00:00-04:00",
                    "channel": "global_risk",
                }
                for idx in range(5)
            ],
        }
        front = rh.render_headlines_panel(available, previous_news=news, panel="front", limit=rh.FRONT_HEADLINES)
        self.assertIn('rel="noopener noreferrer"', front)
        self.assertNotIn("<script>", front)
        self.assertIn("1 more under", front)
        empty = rh.render_headlines_panel(
            {"status": "empty", "reason": "no_eligible_headlines", "as_of": FROZEN_AT, "packet_sha256": PACKET_SHA, "window": available["window"], "items": []},
            previous_news=news,
            panel="news",
            limit=rh.MAX_HEADLINES,
        )
        self.assertIn("mw-headlines-empty", empty)
        self.assertIn(format_et(PREV_AS_OF), empty)
        self.assertIn("21 h before this freeze", empty)
        unavailable = rh.render_headlines_panel(
            {"status": "unavailable", "reason": "news_family_not_fresh", "as_of": None, "packet_sha256": PACKET_SHA, "items": []},
            previous_news=news,
            panel="front",
            limit=rh.FRONT_HEADLINES,
        )
        self.assertIn("<b class=\"mw-headlines-title\">Current verified headlines: unavailable</b>", unavailable)
        self.assertNotIn("as of time not recorded", unavailable)
        self.assertIn("failed verification", unavailable)
        self.assertIn('data-current-headlines="unavailable"', unavailable)
        note = rh.render_previous_analysis_note(news)
        self.assertIn("Previous accepted analysis", note)
        self.assertIn("overnight-20261026", note)


if __name__ == "__main__":
    unittest.main()
