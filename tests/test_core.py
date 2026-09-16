from __future__ import annotations

import unittest
from pathlib import Path

from _support import metadata_dict, official_assessments, official_bundle, trained_model
from linepulse.repository import DecisionRepository
from linepulse.service import LinePulseService


class LinePulseCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = official_bundle()
        cls.model_metadata = metadata_dict()
        cls.assessments = list(official_assessments())

    def test_official_portfolio_has_45_class_a_assets(self) -> None:
        self.assertEqual(self.bundle.asset_count, 45)
        self.assertEqual(self.bundle.assets["AssetID"].nunique(), 45)
        self.assertEqual(set(self.bundle.assets["Class"].str.upper()), {"A"})
        self.assertEqual(len(self.assessments), 45)

    def test_only_declared_operational_sheets_are_loaded(self) -> None:
        audit = self.bundle.data_quality
        loaded = set(audit["worksheets_read"])
        blocked = set(audit["worksheets_explicitly_not_read"])

        self.assertNotIn("ANSWER_KEY", loaded)
        self.assertIn("ANSWER_KEY", blocked)
        self.assertNotIn("README", loaded)
        self.assertEqual(len(loaded), 6)

    def test_known_data_quality_cases_are_detected(self) -> None:
        audit = self.bundle.data_quality

        self.assertEqual(audit["missing_sensor_row_count"], 2)
        self.assertEqual(len(audit["missing_sensor_asset_weeks"]), 2)
        self.assertEqual(len(audit["orphan_maintenance_asset_ids"]), 1)
        self.assertEqual(len(audit["duplicate_work_order_ids"]), 1)
        self.assertEqual(audit["duplicate_usage_key_rows"], 0)
        self.assertEqual(audit["duplicate_sensor_key_rows"], 0)

    def test_model_card_is_honest_about_its_target(self) -> None:
        metadata = self.model_metadata

        self.assertFalse(metadata["is_failure_probability"])
        self.assertFalse(metadata["used_in_rag"])
        self.assertIn("degradation", metadata["semantic_label"].lower())
        self.assertIn("not", metadata["semantic_label"].lower())
        self.assertFalse(metadata["production_validated"])

        feature_names = set(metadata["feature_names"])
        forbidden = {
            "AssetID",
            "AssetName",
            "ReadingID",
            "UsageID",
            "QualityID",
            "ContextID",
            "ScenarioFlag",
            "LinkedFailureMode",
            "ANSWER_KEY",
        }
        self.assertTrue(feature_names)
        self.assertFalse(feature_names & forbidden)
        excluded = set(metadata["excluded_fields"])
        for required_exclusion in ("AssetID", "ScenarioFlag", "LinkedFailureMode", "ANSWER_KEY"):
            self.assertIn(required_exclusion, excluded)

    def test_validation_is_grouped_by_asset_without_leakage(self) -> None:
        metadata = self.model_metadata

        self.assertIn("AssetID", metadata["validation_strategy"])
        self.assertGreaterEqual(metadata["fold_count"], 2)
        self.assertFalse(metadata["group_leakage_detected"])
        self.assertEqual(metadata["asset_groups"], 45)
        self.assertEqual(metadata["training_rows"], len(self.bundle.sensors))

    def test_every_asset_has_an_explainable_human_gated_assessment(self) -> None:
        statuses = set()
        for assessment in self.assessments:
            with self.subTest(asset=assessment.get("asset_id")):
                self.assertTrue(assessment["asset_id"])
                self.assertIn(assessment["status"], {"RED", "AMBER", "GREEN"})
                statuses.add(assessment["status"])
                self.assertGreaterEqual(float(assessment["attention_priority"]), 0)
                self.assertLessEqual(float(assessment["attention_priority"]), 100)
                self.assertGreaterEqual(int(assessment["days_remaining"]), 0)
                self.assertTrue(assessment["classification_reason"].strip())
                self.assertTrue(assessment["failure_mode"].strip())
                self.assertTrue(assessment["recommended_action"].strip())
                self.assertTrue(assessment["evidence_passport"])
                self.assertEqual(assessment["human_approval"], "PENDING")
                self.assertFalse(assessment["equipment_action_taken"])

                first_evidence = assessment["evidence_passport"][0]
                self.assertTrue(first_evidence["source_sheet"])
                self.assertTrue(first_evidence["field"])
                self.assertIn("latest_value", first_evidence)

        # The ranking should demonstrate clearly different attention levels,
        # without binding the test to seeded asset IDs or fixed status counts.
        self.assertEqual(statuses, {"RED", "AMBER", "GREEN"})

    def test_missing_sensor_weeks_are_visible_not_silently_healthy(self) -> None:
        missing_assets = {
            row["asset_id"]
            for row in self.bundle.data_quality["missing_sensor_asset_weeks"]
        }
        by_asset = {row["asset_id"]: row for row in self.assessments}

        for asset_id in missing_assets:
            assessment = by_asset[asset_id]
            with self.subTest(asset=asset_id):
                flags = " ".join(assessment["data_quality_flags"]).lower()
                self.assertIn("missing", flags)
                self.assertLess(float(assessment["data_confidence"]), 100)

    def test_human_decision_memory_never_claims_equipment_action(self) -> None:
        repository = DecisionRepository(":memory:")
        assessment = max(
            self.assessments,
            key=lambda row: float(row["attention_priority"]),
        )
        case_id = repository.add_decision(
            asset_id=assessment["asset_id"],
            decision="APPROVE",
            rationale="Equipment Owner reviewed the evidence passport.",
            owner="Test Owner",
            failure_mode=assessment["failure_mode"],
            recommended_action=assessment["recommended_action"],
            modified_action=None,
            model_status=assessment["status"],
            model_risk_score=float(assessment["technical_risk"]),
            model_horizon_days=int(assessment["days_remaining"]),
            model_snapshot=assessment,
            evidence=assessment["evidence_passport"],
        )
        recorded = repository.add_outcome(
            case_id,
            "RESOLVED",
            notes="Condition verified after approved maintenance.",
            verified_by="Test Owner",
        )

        self.assertEqual(recorded["outcome"], "RESOLVED")
        self.assertFalse(recorded["equipment_action_taken"])
        self.assertEqual(repository.counts(), {"decisions": 1, "verified_outcomes": 1})

    def test_verified_resolved_outcome_changes_display_not_model_record(self) -> None:
        service = LinePulseService(
            data_bundle=self.bundle,
            model_bundle=trained_model(),
            assessments=self.assessments,
            repository=DecisionRepository(":memory:"),
        )
        original = max(
            self.assessments,
            key=lambda row: float(row["attention_priority"]),
        )
        decision = service.record_decision(
            original["asset_id"],
            "APPROVE",
            "Evidence checked by the Equipment Owner.",
            owner="Test Owner",
        )
        after_decision = service.asset_detail(original["asset_id"])["asset"]
        self.assertEqual(after_decision["status"], original["status"])
        self.assertFalse(decision["asset_status_changed"])
        self.assertFalse(decision["equipment_action_taken"])

        outcome = service.record_outcome(
            decision["case"]["id"],
            "RESOLVED",
            notes="Inspection and approved repair resolved the condition.",
            verified_by="Test Owner",
        )
        detail = service.asset_detail(original["asset_id"])

        self.assertEqual(outcome["new_display_status"], "GREEN")
        self.assertEqual(detail["asset"]["status"], "GREEN")
        self.assertEqual(detail["asset"]["status_source"], "VERIFIED_MAINTENANCE_OUTCOME")
        self.assertEqual(detail["original_model_assessment"]["status"], original["status"])
        self.assertTrue(outcome["original_model_assessment_preserved"])
        self.assertFalse(outcome["equipment_action_taken"])

    def test_dashboard_has_real_rag_cards_and_hover_explanations(self) -> None:
        dashboard_source = (
            Path(__file__).resolve().parents[1] / "dashboard" / "app.py"
        ).read_text(encoding="utf-8").lower()

        for status_class in (".lp-summary.red", ".lp-summary.amber", ".lp-summary.green"):
            self.assertIn(status_class, dashboard_source)
        for colour in ("#f04438", "#f79009", "#12b76a"):
            self.assertIn(colour, dashboard_source)
        self.assertIn(".lp-help:hover .lp-tip", dashboard_source)
        self.assertIn("why this status", dashboard_source)
        self.assertIn("to warning boundary", dashboard_source)


if __name__ == "__main__":
    unittest.main()
