import copy
import unittest

from scripts.run_state.observations import (
    ObservationConflict,
    ObservationStore,
    observation_id_from_body,
)
from scripts.run_state.schema import SCHEMA_OBSERVATION_VERSION, ContractError


def _base_observation(**overrides):
    body = {
        "schema_version": SCHEMA_OBSERVATION_VERSION,
        "series_id": "US.Labor.payrolls",
        "period": "2026-09",
        "transformation": "level",
        "raw_sha256": "aa" * 32,
        "value": 150.0,
        "units": "thousands",
        "revision_status": "final",
        "publication_time": "2026-10-02",
        "publication_time_uncertainty": "date_only",
    }
    body.update(overrides)
    body["observation_id"] = observation_id_from_body(body)
    return body


class ObservationStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = ObservationStore()

    def test_idempotent_append_same_identity(self):
        doc = _base_observation()
        first = self.store.append(copy.deepcopy(doc))
        second = self.store.append(copy.deepcopy(doc))
        self.assertEqual(first["observation_id"], second["observation_id"])
        self.assertEqual(
            self.store.get(first["observation_id"]),
            self.store.get(second["observation_id"]),
        )
        self.assertEqual(len(self.store.versions_for("US.Labor.payrolls", "2026-09")), 1)

    def test_different_raw_sha256_second_version(self):
        doc1 = _base_observation(raw_sha256="aa" * 32, value=100.0)
        doc1.pop("observation_id", None)
        doc2 = _base_observation(raw_sha256="bb" * 32, value=100.0)
        doc2.pop("observation_id", None)
        id1 = self.store.append(doc1)["observation_id"]
        id2 = self.store.append(doc2)["observation_id"]
        self.assertNotEqual(id1, id2)
        self.assertIsNotNone(self.store.get(id1))
        self.assertEqual(len(self.store.versions_for("US.Labor.payrolls", "2026-09")), 2)

    def test_same_identity_different_value_raises_conflict(self):
        doc1 = _base_observation(value=100.0)
        doc1.pop("observation_id", None)
        doc2 = _base_observation(value=101.0)
        doc2.pop("observation_id", None)
        self.store.append(doc1)
        with self.assertRaises(ObservationConflict):
            self.store.append(doc2)

    def test_reject_transform_mismatch_does_not_append(self):
        doc = _base_observation()
        doc.pop("observation_id", None)
        with self.assertRaises(ContractError):
            self.store.reject_transform_mismatch(
                doc,
                expected_units="persons",
                expected_transformation="level",
            )
        with self.assertRaises(ContractError):
            self.store.reject_transform_mismatch(
                doc,
                expected_units="thousands",
                expected_transformation="yoy_pct",
            )
        self.store.append(doc)
        self.assertEqual(len(self.store.versions_for("US.Labor.payrolls", "2026-09")), 1)

    def test_missing_publication_time_unknown_uncertainty(self):
        doc = _base_observation()
        doc.pop("observation_id", None)
        doc.pop("publication_time", None)
        doc.pop("publication_time_uncertainty", None)
        stored = self.store.append(doc)
        self.assertIsNone(stored["publication_time"])
        self.assertEqual(stored["publication_time_uncertainty"], "unknown")

    def test_date_only_and_timestamp_validation(self):
        doc = _base_observation(
            publication_time="2026-10-02",
            publication_time_uncertainty="date_only",
        )
        doc.pop("observation_id", None)
        stored = self.store.append(doc)
        self.assertEqual(stored["publication_time"], "2026-10-02")

        bad = _base_observation(
            publication_time="2026-10-02T08:30:00-04:00",
            publication_time_uncertainty="date_only",
        )
        bad.pop("observation_id", None)
        with self.assertRaises(ContractError):
            self.store.append(bad)

    def test_flash_and_final_select_preferred(self):
        flash = _base_observation(
            raw_sha256="11" * 32,
            revision_status="flash",
            value=50.0,
        )
        flash.pop("observation_id", None)
        final = _base_observation(
            raw_sha256="22" * 32,
            revision_status="final",
            value=51.0,
        )
        final.pop("observation_id", None)
        self.store.append(flash)
        self.store.append(final)
        self.assertEqual(len(self.store.versions_for("US.Labor.payrolls", "2026-09")), 2)
        preferred = self.store.select_preferred("US.Labor.payrolls", "2026-09")
        self.assertEqual(preferred["revision_status"], "final")

    def test_replay_get_deep_equals_stored(self):
        doc = _base_observation()
        doc.pop("observation_id", None)
        stored = self.store.append(doc)
        replay_read = self.store.get(stored["observation_id"])
        self.assertEqual(replay_read, stored)

    def test_append_without_value_raises(self):
        doc = _base_observation()
        doc.pop("observation_id", None)
        doc.pop("value", None)
        with self.assertRaises(ContractError):
            self.store.append(doc)
        self.assertEqual(len(self.store.versions_for("US.Labor.payrolls", "2026-09")), 0)


if __name__ == "__main__":
    unittest.main()
