from __future__ import annotations

import unittest

try:
    from fastapi.testclient import TestClient

    import api.main as api_main

    API_AVAILABLE = True
except ImportError:
    TestClient = None
    api_main = None
    API_AVAILABLE = False

from _support import official_assessments, official_bundle, trained_model
from linepulse.repository import DecisionRepository
from linepulse.service import LinePulseService


@unittest.skipUnless(API_AVAILABLE, "FastAPI test dependencies are not installed")
class LinePulseApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service = LinePulseService(
            data_bundle=official_bundle(),
            model_bundle=trained_model(),
            assessments=list(official_assessments()),
            repository=DecisionRepository(":memory:"),
        )
        cls.original_get_service = api_main.get_service
        api_main.get_service = lambda: cls.service
        cls.client = TestClient(api_main.app)

    @classmethod
    def tearDownClass(cls) -> None:
        api_main.get_service = cls.original_get_service

    def setUp(self) -> None:
        self.service.reset_demo()

    def test_health_and_readiness_are_safe_and_complete(self) -> None:
        health = self.client.get("/api/v1/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")
        self.assertFalse(health.json()["equipment_write_capability"])

        readiness = self.client.get("/api/v1/readiness")
        self.assertEqual(readiness.status_code, 200)
        payload = readiness.json()
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["assets"], 45)
        self.assertFalse(payload["equipment_write_capability"])
        self.assertFalse(payload["model"]["production_validated"])
        self.assertFalse(payload["model"]["is_failure_probability"])
        self.assertIn("AssetID", payload["model"]["validation_strategy"])

    def test_portfolio_and_asset_contracts(self) -> None:
        response = self.client.get("/api/v1/portfolio")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 45)
        self.assertEqual(len(payload["items"]), 45)
        self.assertFalse(payload["equipment_write_capability"])
        self.assertEqual(set(payload["status_counts"]), {"RED", "AMBER", "GREEN"})

        selected = payload["items"][0]
        detail_response = self.client.get(f"/api/v1/assets/{selected['asset_id']}")
        self.assertEqual(detail_response.status_code, 200)
        detail = detail_response.json()
        self.assertEqual(detail["asset"]["asset_id"], selected["asset_id"])
        self.assertTrue(detail["original_model_assessment"]["evidence_passport"])
        self.assertFalse(detail["human_gate"]["equipment_action_taken"])

    def test_unknown_resources_return_404(self) -> None:
        response = self.client.get("/api/v1/assets/not-a-real-asset")
        self.assertEqual(response.status_code, 404)
        self.assertIn("Unknown asset", response.json()["detail"])

        response = self.client.get("/api/v1/cases/9999999")
        self.assertEqual(response.status_code, 404)
        self.assertIn("Unknown case", response.json()["detail"])

    def test_decision_then_verified_outcome_updates_only_workflow_colour(self) -> None:
        portfolio = self.client.get("/api/v1/portfolio").json()["items"]
        original = max(portfolio, key=lambda item: float(item["attention_priority"]))

        decision_response = self.client.post(
            "/api/v1/decisions",
            json={
                "asset_id": original["asset_id"],
                "decision": "APPROVE",
                "rationale": "Equipment Owner reviewed the Evidence Passport.",
                "owner": "API Test Owner",
            },
        )
        self.assertEqual(decision_response.status_code, 201)
        decision = decision_response.json()
        self.assertFalse(decision["asset_status_changed"])
        self.assertFalse(decision["equipment_action_taken"])

        unchanged = self.client.get(
            f"/api/v1/assets/{original['asset_id']}"
        ).json()["asset"]
        self.assertEqual(unchanged["status"], original["status"])

        outcome_response = self.client.post(
            f"/api/v1/cases/{decision['case']['id']}/outcome",
            json={
                "outcome": "RESOLVED",
                "notes": "Maintenance performed and sensor condition verified.",
                "verified_by": "API Test Owner",
            },
        )
        self.assertEqual(outcome_response.status_code, 200)
        outcome = outcome_response.json()
        self.assertEqual(outcome["new_display_status"], "GREEN")
        self.assertEqual(outcome["original_model_status"], original["model_status"])
        self.assertTrue(outcome["original_model_assessment_preserved"])
        self.assertFalse(outcome["equipment_action_taken"])

    def test_what_if_is_bounded_non_persistent_and_has_no_write_action(self) -> None:
        original = self.client.get("/api/v1/portfolio").json()["items"][0]
        response = self.client.post(
            f"/api/v1/assets/{original['asset_id']}/what-if",
            json={"duty_reduction_pct": 20, "start_stop_reduction_pct": 25},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["simulation_only"])
        self.assertFalse(payload["persisted"])
        self.assertFalse(payload["equipment_action_taken"])
        self.assertLessEqual(
            payload["scenario"]["technical_risk"],
            payload["original"]["technical_risk"],
        )

        after = self.client.get(
            f"/api/v1/assets/{original['asset_id']}"
        ).json()["asset"]
        self.assertEqual(after["technical_risk"], original["technical_risk"])

    def test_api_exposes_no_equipment_command_endpoint(self) -> None:
        route_paths = {
            route.path.lower()
            for route in api_main.app.routes
            if hasattr(route, "path")
        }
        forbidden_terms = ("command", "shutdown", "equipment-write", "plc-write")
        for path in route_paths:
            self.assertFalse(any(term in path for term in forbidden_terms), path)


if __name__ == "__main__":
    unittest.main()

