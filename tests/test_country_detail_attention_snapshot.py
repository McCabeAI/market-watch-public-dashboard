from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.apply_country_detail import load_country_detail_context
from scripts.country_detail import policy
from scripts.country_detail.attention import evaluate_observations, evaluate_projection
from scripts.country_detail.persistence import load_snapshot, save_snapshot

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "tests" / "fixtures" / "country_detail" / "acceptance_matrix.json"


def _matrix_observation(case_id: str, label: str) -> dict:
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    case = next(c for c in matrix["cases"] if c["id"] == case_id)
    snapshot = case["snapshots"][0]
    return copy.deepcopy(snapshot["observations"][0] if label == "first" else next(
        o for o in snapshot["observations"] if o.get("label") == label
    ))


def _labeled_obs(case_id: str, label: str) -> dict:
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    case = next(c for c in matrix["cases"] if c["id"] == case_id)
    snapshot = case["snapshots"][0]
    for obs in snapshot["observations"]:
        if obs.get("label") == label:
            return copy.deepcopy(obs)
    raise KeyError(label)


class CountryDetailAttentionSnapshotTest(unittest.TestCase):
    def test_snapshot_round_trip_unchanged_freshness(self) -> None:
        obs = _labeled_obs("unscored_zero_weight_leads", "unscored_physical")
        obs_id = policy.observation_id(obs)
        first = evaluate_observations([obs], as_of="2026-10-01", country="CA")
        member = next(m for m in first["members"] if m["observation_id"] == obs_id)
        self.assertEqual(member["alert_freshness"], "new")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snap.json"
            save_snapshot(path, first)
            prior = load_snapshot(path)
            second_obs = copy.deepcopy(obs)
            second_obs["retrieved_at"] = "2026-10-30T12:00:00Z"
            second_obs["attempted_retrieved_at"] = second_obs["retrieved_at"]
            second = evaluate_observations(
                [second_obs],
                as_of="2026-10-01",
                prior=prior,
                country="CA",
            )
            again = next(m for m in second["members"] if m["observation_id"] == obs_id)
            self.assertEqual(again["alert_freshness"], "unchanged")
            self.assertEqual(again.get("publication_day"), member.get("publication_day"))

    def test_stored_publication_day_survives_revision_release_date(self) -> None:
        obs = _labeled_obs("unscored_zero_weight_leads", "unscored_physical")
        obs_id = policy.observation_id(obs)
        obs["release_date"] = "2025-01-22"
        for item in obs.get("history") or []:
            if item.get("reference_period") == obs["reference_period"]:
                item["release_date"] = "2025-01-22"
        first = evaluate_observations([obs], as_of="2026-10-01", country="CA")
        pub = next(m for m in first["members"] if m["observation_id"] == obs_id)["publication_day"]
        self.assertIsNotNone(pub)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snap.json"
            save_snapshot(path, first)
            prior = load_snapshot(path)
            revised = copy.deepcopy(obs)
            revised["release_date"] = "2026-10-15"
            for item in revised.get("history") or []:
                if item.get("reference_period") == revised["reference_period"]:
                    item["release_date"] = "2026-10-15"
            second = evaluate_observations(
                [revised],
                as_of="2026-10-01",
                prior=prior,
                country="CA",
            )
            again = next(m for m in second["members"] if m["observation_id"] == obs_id)
            self.assertEqual(again["publication_day"], pub)

    def test_undated_not_finding_when_enforcing_publication_age(self) -> None:
        obs = _labeled_obs("unscored_zero_weight_leads", "unscored_physical")
        obs.pop("release_date", None)
        for item in obs.get("history") or []:
            item.pop("release_date", None)
        result = evaluate_observations(
            [obs],
            as_of="2026-10-30",
            enforce_publication_age=True,
            publication_as_of="2026-10-30",
            country="CA",
        )
        obs_id = policy.observation_id(obs)
        finding_ids = {f["observation_id"] for f in result.get("findings") or []}
        self.assertNotIn(obs_id, finding_ids)
        member = next(m for m in result["members"] if m["observation_id"] == obs_id)
        self.assertIsNone(member.get("publication_day"))

    def test_prior_first_seen_day_used_without_release_date(self) -> None:
        obs = _labeled_obs("unscored_zero_weight_leads", "unscored_physical")
        obs_id = policy.observation_id(obs)
        obs.pop("release_date", None)
        for item in obs.get("history") or []:
            item.pop("release_date", None)
        prior = {
            obs_id: {
                "value": obs["value"],
                "reference_period": obs["reference_period"],
                "transformation": obs["transformation"],
                "revision_status": obs.get("revision_status"),
                "vintage": obs.get("vintage"),
                "first_seen_day": "2026-09-05",
            }
        }
        first = evaluate_observations([obs], as_of="2026-10-01", prior=prior, country="CA")
        member = next(m for m in first["members"] if m["observation_id"] == obs_id)
        self.assertEqual(member["publication_day"], "2026-09-05")
        self.assertEqual(member.get("first_seen_day"), "2026-09-05")

        bumped = copy.deepcopy(obs)
        bumped["retrieved_at"] = "2026-10-30T12:00:00Z"
        second = evaluate_observations(
            [bumped],
            as_of="2026-10-01",
            prior={
                obs_id: {
                    **prior[obs_id],
                    "publication_day": member["publication_day"],
                }
            },
            country="CA",
        )
        again = next(m for m in second["members"] if m["observation_id"] == obs_id)
        self.assertEqual(again["publication_day"], "2026-09-05")

    def _outlier_observation(self, *, country: str, release_date: str, period: str) -> dict:
        obs = _labeled_obs("unscored_zero_weight_leads", "unscored_physical")
        obs["country"] = country
        obs["geography"] = country
        obs["reference_period"] = period
        obs["release_date"] = release_date
        history: list[dict] = []
        idx = 0
        for year in range(2018, 2027):
            for month in range(1, 13):
                if year == 2026 and month > 9:
                    break
                ref = f"{year:04d}-{month:02d}"
                idx += 1
                history.append({"reference_period": ref, "value": float(idx)})
        obs["history"] = history
        for point in obs["history"]:
            if point["reference_period"] == period:
                point["value"] = 99.0
                point["release_date"] = release_date
                break
        else:
            obs["history"].append(
                {"reference_period": period, "value": 99.0, "release_date": release_date}
            )
        obs["value"] = 99.0
        obs["observation_id"] = policy.observation_id(obs)
        return obs

    def test_evaluate_projection_publication_age_window(self) -> None:
        aged = self._outlier_observation(
            country="US",
            release_date="2026-08-28",
            period="2026-08",
        )
        fresh = self._outlier_observation(
            country="NZ",
            release_date="2026-10-19",
            period="2026-09",
        )
        projection = {
            "as_of": "2026-10-30",
            "countries": {
                "US": {"observations": [aged], "as_of": "2026-10-30"},
                "NZ": {"observations": [fresh], "as_of": "2026-10-30"},
            },
        }
        stale = {code: 4 for code in policy.COUNTRY_CODES}
        result = evaluate_projection(
            projection,
            stale_after_days=stale,
            publication_as_of="2026-10-30",
        )
        us_findings = result["countries"]["US"].get("findings") or []
        self.assertEqual(len(us_findings), 0)
        nz_findings = result["countries"]["NZ"].get("findings") or []
        if nz_findings:
            self.assertEqual(nz_findings[0]["observation_id"], fresh["observation_id"])

    def test_load_country_detail_context_snapshot_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "attention_snapshot.json"
            load_country_detail_context(
                ROOT,
                snapshot_path=snap,
                publication_as_of="2026-10-30",
            )
            second = load_country_detail_context(
                ROOT,
                snapshot_path=snap,
                publication_as_of="2026-10-30",
            )
            ca_second = second["attention"]["countries"]["CA"]
            snap_doc = load_snapshot(snap)
        for finding in ca_second.get("findings") or []:
            if finding.get("alert_freshness") != "new":
                continue
            row = snap_doc["observations"].get(str(finding["observation_id"]))
            if row is None:
                continue
            member = next(
                m
                for m in ca_second["members"]
                if m["observation_id"] == finding["observation_id"]
            )
            if policy.is_unchanged_reprint(
                units=str(member.get("units") or ""),
                previous_value=row.get("value"),
                current_value=member.get("value"),
                previous_reference_period=row.get("reference_period"),
                current_reference_period=member.get("reference_period"),
                previous_transformation=row.get("transformation"),
                current_transformation=member.get("transformation"),
                previous_revision_status=row.get("revision_status"),
                current_revision_status=member.get("revision_status"),
            ):
                self.fail(
                    f"finding {finding['observation_id']} still alert_freshness=new after snapshot round-trip"
                )

        for finding in ca_second.get("findings") or []:
            self.assertNotEqual(finding.get("reference_period"), "2026-Q2")
            pub = finding.get("publication_day")
            if pub:
                age = policy.publication_age_days(pub, "2026-10-30")
                self.assertIsNotNone(age)
                self.assertLessEqual(age, policy.WMN_MAX_PUBLICATION_AGE_DAYS)
                self.assertNotEqual(pub, "2026-08-28")

        ca_obs = second["projection"]["countries"]["CA"]["observations"]
        headline_sept = next(
            o
            for o in ca_obs
            if o.get("catalog_id") == "CA.Inflation.headline"
            and o.get("reference_period") == "2026-09"
        )
        self.assertEqual(headline_sept.get("release_date"), "2026-10-19")


if __name__ == "__main__":
    unittest.main()
