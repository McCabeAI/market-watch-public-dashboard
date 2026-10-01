"""Tests for EA country HICP national flash + Eurostat final reconciliation."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.macro_ingestion.adapters import ea as ea_adapter
from scripts.macro_ingestion.canonical_bridge import merge_scored_points
from scripts.macro_ingestion.contract import load_catalog
from scripts.macro_ingestion.ea_country_hicp import (
    append_ranked_country_hicp,
    discover_destatis_press_url,
    fetch_national_hicp_points,
    discover_insee_statistic_id,
    discover_ine_portugal_flash_url,
    discover_ine_spain_press_url,
    discover_istat_provisional_url,
    parse_destatis_hicp_press,
    parse_insee_press_page,
    parse_ine_portugal_ihpc_press,
    parse_ine_spain_ipca_press,
    parse_istat_ipca_press,
    reconcile_country_hicp_points,
    select_current_rows,
    vintage_rank,
)
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ea"
HICP_DE_FIXTURE = FIXTURES / "eurostat_hicp_de.json"


class TestEaCountryHicpReconcile(unittest.TestCase):
    def test_national_leads_then_eurostat_final_for_prior_month(self) -> None:
        euro = [
            {
                "period": "2026-09",
                "value": 2.0,
                "transformation": "yoy_pct",
                "revision_status": "final",
                "vintage": "eurostat_final",
                "source_url": "https://ec.europa.eu/eurostat/x",
                "publisher": "Eurostat",
            }
        ]
        national = [
            {
                "period": "2026-10",
                "value": 9.5,
                "transformation": "yoy_pct",
                "revision_status": "preliminary",
                "vintage": "national_preliminary",
                "source_url": "https://national.example/flash",
                "publisher": "Destatis",
            }
        ]
        out = reconcile_country_hicp_points(euro, national)
        by_period = {p["period"]: p for p in out}
        self.assertEqual(by_period["2026-10"]["value"], 9.5)
        self.assertEqual(by_period["2026-10"]["vintage"], "national_preliminary")
        self.assertEqual(by_period["2026-09"]["vintage"], "eurostat_final")

    def test_eurostat_wins_same_period_different_value(self) -> None:
        euro = [
            {
                "period": "2026-10",
                "value": 8.0,
                "transformation": "yoy_pct",
                "revision_status": "final",
                "vintage": "eurostat_final",
                "source_url": "https://ec.europa.eu/eurostat/x",
                "publisher": "Eurostat",
            }
        ]
        national = [
            {
                "period": "2026-10",
                "value": 9.5,
                "transformation": "yoy_pct",
                "revision_status": "preliminary",
                "vintage": "national_preliminary",
                "source_url": "https://national.example/flash",
                "publisher": "Destatis",
            }
        ]
        out = reconcile_country_hicp_points(euro, national)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["value"], 8.0)
        self.assertEqual(out[0]["vintage"], "eurostat_final")

    def test_same_value_rewrites_to_eurostat_final(self) -> None:
        euro = [
            {
                "period": "2026-10",
                "value": 9.5,
                "transformation": "yoy_pct",
                "revision_status": "final",
                "vintage": "eurostat_final",
                "source_url": "https://ec.europa.eu/eurostat/x",
                "publisher": "Eurostat",
            }
        ]
        national = [
            {
                "period": "2026-10",
                "value": 9.5,
                "transformation": "yoy_pct",
                "revision_status": "preliminary",
                "vintage": "national_preliminary",
                "source_url": "https://national.example/flash",
                "publisher": "Destatis",
            }
        ]
        out = reconcile_country_hicp_points(euro, national)
        self.assertEqual(out[0]["vintage"], "eurostat_final")


class TestEaCountryHicpStore(unittest.TestCase):
    def test_select_current_and_append_ranked(self) -> None:
        store = {"country": "EA", "observations": []}
        series_id = "PRC_HICP_MINR.M.RCH_A.TOTAL.DE"
        append_ranked_country_hicp(
            store,
            series_id=series_id,
            period="2026-10",
            transformation="yoy_pct",
            value=9.5,
            raw_sha256="a",
            retrieved_at="2026-10-01T10:00:00Z",
            vintage="national_preliminary",
            revision_status="preliminary",
            source_url="https://national.example/p",
            derivation={"publisher": "Destatis"},
        )
        append_ranked_country_hicp(
            store,
            series_id=series_id,
            period="2026-10",
            transformation="yoy_pct",
            value=8.0,
            raw_sha256="b",
            retrieved_at="2026-10-02T10:00:00Z",
            vintage="eurostat_final",
            revision_status="final",
            source_url="https://ec.europa.eu/eurostat/x",
            derivation={"publisher": "Eurostat"},
        )
        rows = [r for r in store["observations"] if r["period"] == "2026-10"]
        current = select_current_rows(rows)
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["vintage"], "eurostat_final")
        skipped = append_ranked_country_hicp(
            store,
            series_id=series_id,
            period="2026-10",
            transformation="yoy_pct",
            value=9.9,
            raw_sha256="c",
            retrieved_at="2026-10-03T10:00:00Z",
            vintage="national_preliminary",
            revision_status="preliminary",
            source_url="https://national.example/new",
        )
        self.assertTrue(skipped.duplicate)

    def test_upgrade_in_place_same_value(self) -> None:
        store = {"country": "EA", "observations": []}
        series_id = "PRC_HICP_MINR.M.RCH_A.TOTAL.FR"
        append_ranked_country_hicp(
            store,
            series_id=series_id,
            period="2026-11",
            transformation="yoy_pct",
            value=9.5,
            raw_sha256="a",
            retrieved_at="2026-11-01T10:00:00Z",
            vintage="national_preliminary",
            revision_status="preliminary",
            source_url="https://national.example/p",
            derivation={"publisher": "INSEE"},
        )
        upgraded = append_ranked_country_hicp(
            store,
            series_id=series_id,
            period="2026-11",
            transformation="yoy_pct",
            value=9.5,
            raw_sha256="b",
            retrieved_at="2026-11-02T10:00:00Z",
            vintage="eurostat_final",
            revision_status="final",
            source_url="https://ec.europa.eu/eurostat/x",
            derivation={"publisher": "Eurostat"},
        )
        self.assertTrue(upgraded.upgraded)
        period_rows = [r for r in store["observations"] if r["period"] == "2026-11"]
        self.assertEqual(len(period_rows), 1)
        self.assertEqual(period_rows[0]["vintage"], "eurostat_final")

    def test_equal_rank_value_change_appends(self) -> None:
        store = {"country": "EA", "observations": []}
        series_id = "PRC_HICP_MINR.M.RCH_A.TOTAL.ES"
        append_ranked_country_hicp(
            store,
            series_id=series_id,
            period="2026-10",
            transformation="yoy_pct",
            value=1.0,
            raw_sha256="a",
            retrieved_at="2026-10-01T10:00:00Z",
            vintage="eurostat_final",
            revision_status="final",
            source_url="https://ec.europa.eu/eurostat/x",
        )
        revised = append_ranked_country_hicp(
            store,
            series_id=series_id,
            period="2026-10",
            transformation="yoy_pct",
            value=1.4,
            raw_sha256="b",
            retrieved_at="2026-10-20T10:00:00Z",
            vintage="eurostat_final",
            revision_status="final",
            source_url="https://ec.europa.eu/eurostat/x",
        )
        self.assertTrue(revised.appended)
        current = select_current_rows(
            [r for r in store["observations"] if r["period"] == "2026-10"]
        )
        self.assertEqual(len(current), 1)
        self.assertAlmostEqual(current[0]["value"], 1.4)


class TestEaCountryHicpParsers(unittest.TestCase):
    def test_destatis_hicp_not_cpi(self) -> None:
        html = """
        <p>Verbraucherpreisindex, Oktober 2026: 1,1 % zum Vorjahresmonat (vorläufig)</p>
        <p>Harmonisierter Verbraucherpreisindex, Oktober 2026: 9,5 % zum Vorjahresmonat (vorläufig)</p>
        """
        row = parse_destatis_hicp_press(html.encode(), "https://destatis.example/p")
        self.assertIsNotNone(row)
        self.assertAlmostEqual(row["value"], 9.5)

    def test_insee_ensemble_ipch_last_cell(self) -> None:
        html = """
        <p>Comparaison août 2026</p>
        <title>Indicateur des prix à la consommation provisoires — octobre 2026</title>
        <meta name="description" content="résultats provisoires" />
        <p>Les résultats définitifs seront publiés le 15 novembre 2026.</p>
        <table><tr><th>Ensemble IPCH**</th><td>10&nbsp;000</td><td>0,1</td><td>9,5</td></tr></table>
        <p>Sur un an, l'indice des prix à la consommation harmonisé augmenterait de 9,5 %.</p>
        """
        row = parse_insee_press_page(html.encode(), "https://insee.example/s")
        self.assertIsNotNone(row)
        self.assertAlmostEqual(row["value"], 9.5)
        self.assertEqual(row["period"], "2026-10")
        self.assertEqual(row["vintage"], "national_preliminary")

    def test_istat_ipca_annual_not_monthly(self) -> None:
        html = (
            "L'indice armonizzato dei prezzi al consumo (IPCA) registra una variazione del "
            "0,3% rispetto al mese precedente e del 9,5% su base annua."
        )
        row = parse_istat_ipca_press(
            html.encode(),
            "https://www.istat.it/comunicato-stampa/prezzi-al-consumo-dati-provvisori-ottobre-2026/",
        )
        self.assertIsNotNone(row)
        self.assertAlmostEqual(row["value"], 9.5)

    def test_spain_ipca_adelantado_not_ipc(self) -> None:
        html = """
        <p>La variación anual del IPC se sitúa en el 1,0%.</p>
        <p>La variación anual del indicador adelantado del IPCA es del 9,5%</p>
        """
        row = parse_ine_spain_ipca_press(
            html.encode(),
            "https://www.ine.es/dyngs/Prensa/es/adIPC1026.htm",
        )
        self.assertIsNotNone(row)
        self.assertAlmostEqual(row["value"], 9.5)
        self.assertEqual(row["period"], "2026-10")

    def test_portugal_ihpc_entities(self) -> None:
        html = """
        <h1>IPC: 9,5%</h1>
        <p>O &Iacute;ndice Harmonizado de Pre&ccedil;os no Consumidor (IHPC) registar&aacute;
        uma varia&ccedil;&atilde;o hom&oacute;loga de 9,5% em Outubro de 2026.</p>
        """
        row = parse_ine_portugal_ihpc_press(html.encode(), "https://ine.pt/x")
        self.assertIsNotNone(row)
        self.assertAlmostEqual(row["value"], 9.5)
        self.assertEqual(row["period"], "2026-10")

    def test_portugal_period_follows_ihpc_sentence_not_dateline(self) -> None:
        html = """
        <p>1 de outubro de 2026</p>
        <p>O Índice Harmonizado de Preços no Consumidor (IHPC) terá registado
        uma variação homóloga de 9,5% em setembro de 2026.</p>
        """
        row = parse_ine_portugal_ihpc_press(html.encode(), "https://ine.pt/x")
        self.assertIsNotNone(row)
        self.assertEqual(row["period"], "2026-09")
        self.assertEqual(row["vintage"], "national_preliminary")

    def test_portugal_headline_month_when_sentence_has_no_year(self) -> None:
        html = """
        <b>Estimativa Rápida</b>
        <div>Taxa de variação homóloga do IPC terá aumentado para 1,0% - Setembro de 2026</div>
        <p>O Índice Harmonizado de Preços no Consumidor (IHPC) português terá registado
        uma variação homóloga de 9,5% (valor idêntico em agosto).</p>
        """
        row = parse_ine_portugal_ihpc_press(html.encode(), "https://ine.pt/x")
        self.assertIsNotNone(row)
        self.assertAlmostEqual(row["value"], 9.5)
        self.assertEqual(row["period"], "2026-09")
        self.assertEqual(row["vintage"], "national_preliminary")


class TestEaCountryHicpDiscovery(unittest.TestCase):
    def test_destatis_latest_pd(self) -> None:
        listing = """
        <a href="/Pressemitteilungen/2026/09/PD01_99_611.html">old</a>
        <a href="/Pressemitteilungen/2026/10/PD01_100_611.html">new</a>
        """
        url = discover_destatis_press_url(listing.encode())
        self.assertIn("PD01_100_611", url or "")

    def test_spain_latest_mmyy(self) -> None:
        listing = """
        <a href="/dyngs/Prensa/es/adIPC0926.htm">sep</a>
        <a href="/dyngs/Prensa/es/adIPC1026.htm">oct</a>
        """
        url = discover_ine_spain_press_url(listing.encode())
        self.assertIn("adIPC1026", url or "")

    def test_istat_first_provisional(self) -> None:
        listing = """
        <a href="https://www.istat.it/comunicato-stampa/prezzi-al-consumo-dati-provvisori-ottobre-2026/">flash</a>
        <a href="/comunicato-stampa/prezzi-al-consumo-dati-provvisori-settembre-2026/">older</a>
        <a href="/comunicato-stampa/prezzi-al-consumo-settembre-2026/">final</a>
        """
        url = discover_istat_provisional_url(listing.encode())
        self.assertIn("dati-provvisori-ottobre", url or "")
        self.assertTrue((url or "").startswith("https://www.istat.it/"))

    def test_portugal_estimativa_rapida(self) -> None:
        listing = """
        <a href="/xportal/xmain?DESTAQUESdest_boui=111&amp;DESTAQUESmodo=2">Taxa de variação homóloga do IPC terá aumentado para 1,0%</a> - Outubro de 2026
        <a href="/xportal/xmain?DESTAQUESdest_boui=222&amp;DESTAQUESmodo=2">Taxa de variação homóloga do IPC aumentou para 1,0%</a> - Setembro de 2026
        <div DESTAQUESdest_boui="333">Estimativa Rápida IHPC</div>
        """
        url = discover_ine_portugal_flash_url(listing.encode())
        self.assertIn("111", url or "")

    def test_france_empty_solr_does_not_recurse(self) -> None:
        calls = {"n": 0}

        def opener(url: str, *, timeout: float = 20, data: bytes | None = None):
            calls["n"] += 1
            if data is not None:
                body = b'{"documents":[{"title":"Produit interieur brut","id":"1"}]}'
            else:
                body = b"<html><title>pas de prix</title></html>"
            return {"ok": True, "http_status": 200, "body": body, "error": None, "url": url}

        points, err = fetch_national_hicp_points("FR", opener=opener, timeout=5)
        self.assertEqual(points, [])
        self.assertIsNotNone(err)
        self.assertLess(calls["n"], 12)

    def test_insee_solr_filter(self) -> None:
        payload = {
            "documents": [
                {"title": "Autre publication", "id": "1"},
                {"title": "Indicateur des prix à la consommation — octobre", "id": "99999"},
            ]
        }
        doc_id = discover_insee_statistic_id(json.dumps(payload).encode())
        self.assertEqual(doc_id, "99999")


class TestEaCountryHicpAdapter(unittest.TestCase):
    def test_adapter_merges_national_flash_with_eurostat(self) -> None:
        euro_body = HICP_DE_FIXTURE.read_bytes()
        national_html = (
            b"<p>Harmonisierter Verbraucherpreisindex, Oktober 2026: "
            b"9,5 % zum Vorjahresmonat (vorl\xc3\xa4ufig)</p>"
        )
        spec = next(r for r in load_catalog()["series"] if r["id"] == "EA.Inflation.hicp_de")

        listing = (
            b'<a href="/Pressemitteilungen/2026/10/PD01_1_611.html">press</a>'
        )
        press = national_html

        def opener(url: str, *, timeout: float = 20):
            if "eurostat" in url:
                return {"ok": True, "http_status": 200, "body": euro_body, "error": None}
            if "destatis.de" in url and "Pressemitteilungen" not in url:
                return {"ok": True, "http_status": 200, "body": listing, "error": None}
            if "Pressemitteilungen" in url:
                return {"ok": True, "http_status": 200, "body": press, "error": None}
            return {"ok": False, "http_status": 404, "body": b"", "error": "skip"}

        payload = ea_adapter.fetch_series(
            spec,
            opener=opener,
            now=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
        self.assertTrue(payload["ok"])
        last = payload["points"][-1]
        self.assertEqual(last["period"], "2026-10")
        self.assertAlmostEqual(last["value"], 9.5)
        self.assertEqual(last["vintage"], "national_preliminary")
        prior = payload["points"][-2]
        self.assertEqual(prior["period"], "2026-08")
        self.assertEqual(prior["vintage"], "eurostat_final")
        self.assertEqual(spec["weight"], 0.0)

    def test_context_not_scored_in_bridge(self) -> None:
        cal = {"as_of": "2026-01-01", "components": {}}
        point = {
            "catalog_id": "EA.Inflation.hicp_de",
            "role": "context",
            "period": "2026-10",
            "value": 9.5,
        }
        result = merge_scored_points({}, cal, [point], checked_at="2026-10-01T00:00:00Z")
        self.assertEqual(result["skipped"][0]["reason"], "context_not_scored")

    def test_vintage_rank_legacy_eurostat(self) -> None:
        self.assertEqual(
            vintage_rank(
                {
                    "vintage": "latest_available",
                    "revision_status": "final",
                    "source_url": "https://ec.europa.eu/eurostat/api",
                }
            ),
            3,
        )


if __name__ == "__main__":
    unittest.main()
