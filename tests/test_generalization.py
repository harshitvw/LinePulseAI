from __future__ import annotations

import copy
import hashlib
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from _support import (
    WORKBOOK,
    cloned_bundle,
    label_free_model,
    official_assessments,
    official_bundle,
    trained_model,
)


class LinePulseGeneralizationTests(unittest.TestCase):
    @staticmethod
    def _score_signature(rows):
        return sorted(
            (
                round(float(row["technical_risk"]), 7),
                round(float(row["attention_priority"]), 7),
                int(row["days_remaining"]),
                row["status"],
                row["failure_mode"],
            )
            for row in rows
        )

    def test_assessment_does_not_read_scenario_labels_directly(self) -> None:
        from linepulse.risk import build_asset_assessments

        changed = cloned_bundle()
        # The source hint has already been converted to this training target.
        # Inference must remain identical even when every label is inverted.
        changed.weekly["DegradationTarget"] = 1 - changed.weekly["DegradationTarget"]

        actual = build_asset_assessments(changed, trained_model())
        self.assertEqual(
            self._score_signature(official_assessments()),
            self._score_signature(actual),
        )

    def test_asset_identifiers_can_be_replaced_without_changing_scores(self) -> None:
        from linepulse.risk import build_asset_assessments

        changed = cloned_bundle()
        old_ids = changed.assets["AssetID"].astype(str).tolist()
        mapping = {
            old_id: f"REPLACED-{position:03d}"
            for position, old_id in enumerate(old_ids, start=1)
        }

        for frame_name in ("assets", "usage", "sensors", "maintenance", "quality", "weekly"):
            frame = getattr(changed, frame_name)
            if "AssetID" in frame:
                frame["AssetID"] = frame["AssetID"].astype(str).replace(mapping)

        for item in changed.data_quality["missing_sensor_asset_weeks"]:
            item["asset_id"] = mapping.get(item["asset_id"], item["asset_id"])
        changed.data_quality["orphan_maintenance_asset_ids"] = [
            mapping.get(value, value)
            for value in changed.data_quality["orphan_maintenance_asset_ids"]
        ]

        actual = build_asset_assessments(changed, trained_model())
        actual_ids = {row["asset_id"] for row in actual}

        self.assertEqual(actual_ids, set(mapping.values()))
        self.assertEqual(
            self._score_signature(official_assessments()),
            self._score_signature(actual),
        )

    def test_workbook_without_scenario_flag_still_scores_all_assets(self) -> None:
        from linepulse.data import load_official_data
        from linepulse.risk import build_asset_assessments

        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "official_without_hint.xlsx"
            workbook = load_workbook(WORKBOOK)
            worksheet = workbook["Sensor_Readings"]
            headers = [cell.value for cell in worksheet[1]]
            scenario_column = headers.index("ScenarioFlag") + 1
            worksheet.delete_cols(scenario_column)
            workbook.save(destination)

            bundle = load_official_data(destination)
            rows = build_asset_assessments(bundle, trained_model())

        self.assertEqual(len(rows), 45)
        self.assertNotIn("ScenarioFlag", bundle.model_features)
        self.assertEqual(set(bundle.weekly["DegradationTarget"]), {0})

    def test_all_blank_scenario_hint_uses_training_fallback(self) -> None:
        metadata = dict(label_free_model().metadata)

        self.assertFalse(metadata["is_failure_probability"])
        self.assertTrue(metadata["analytical_fallback_available"])
        self.assertIn("fallback", metadata["training_mode"].lower())

    def test_rag_risk_and_horizon_do_not_depend_on_scenario_hint(self) -> None:
        from linepulse.risk import build_asset_assessments

        hint_rows = list(official_assessments())
        fallback_rows = build_asset_assessments(official_bundle(), label_free_model())
        hint_by_id = {row["asset_id"]: row for row in hint_rows}
        fallback_by_id = {row["asset_id"]: row for row in fallback_rows}

        self.assertEqual(set(hint_by_id), set(fallback_by_id))
        for asset_id in hint_by_id:
            hint = hint_by_id[asset_id]
            fallback = fallback_by_id[asset_id]
            with self.subTest(asset=asset_id):
                self.assertEqual(hint["status"], fallback["status"])
                self.assertEqual(hint["technical_risk"], fallback["technical_risk"])
                self.assertEqual(hint["attention_priority"], fallback["attention_priority"])
                self.assertEqual(hint["days_remaining"], fallback["days_remaining"])

    def test_model_metadata_fingerprints_the_exact_source_workbook(self) -> None:
        expected = hashlib.sha256(WORKBOOK.read_bytes()).hexdigest()
        metadata = dict(trained_model().metadata)

        self.assertEqual(metadata["source_fingerprint_sha256"], expected)

    def test_stale_model_artifact_is_retrained_for_current_source(self) -> None:
        from linepulse.analytics import load_or_train_model, save_model_bundle

        stale = copy.deepcopy(trained_model())
        stale.metadata["source_fingerprint_sha256"] = "0" * 64

        with tempfile.TemporaryDirectory() as temporary_directory:
            artifact_path = Path(temporary_directory) / "stale.joblib"
            save_model_bundle(stale, artifact_path)
            refreshed = load_or_train_model(official_bundle(), artifact_path)

        expected = hashlib.sha256(WORKBOOK.read_bytes()).hexdigest()
        self.assertEqual(refreshed.metadata["source_fingerprint_sha256"], expected)
        self.assertFalse(refreshed.metadata["loaded_from_artifact"])


if __name__ == "__main__":
    unittest.main()
