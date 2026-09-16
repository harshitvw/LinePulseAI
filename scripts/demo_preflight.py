"""Judge-demo readiness checks with readable pass/fail output."""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from linepulse.repository import DecisionRepository  # noqa: E402
from linepulse.service import LinePulseService  # noqa: E402


@dataclass
class Check:
    label: str
    passed: bool
    detail: str


def main() -> None:
    checks: list[Check] = []

    def record(label: str, passed: bool, detail: str) -> None:
        checks.append(Check(label=label, passed=bool(passed), detail=detail))

    expected_files = (
        "data/source/Synthetic_Dataset.xlsx",
        "reference/Participant_Guide.docx",
        "reference/Synthetic_Dataset_Report.docx",
        "api/main.py",
        "dashboard/app.py",
        "docs/PROJECT_GUIDE.md",
        "docs/ARCHITECTURE.md",
        "docs/DEMO_WALKTHROUGH.md",
        "docs/MODEL_CARD.md",
        "docs/ASSUMPTIONS.md",
    )
    missing_files = [name for name in expected_files if not (PROJECT_ROOT / name).exists()]
    record(
        "Project deliverables",
        not missing_files,
        "all required files present" if not missing_files else f"missing: {', '.join(missing_files)}",
    )

    source_workbooks = list((PROJECT_ROOT / "data" / "source").glob("*.xlsx"))
    record(
        "Official data only",
        len(source_workbooks) == 1 and source_workbooks[0].name == "Synthetic_Dataset.xlsx",
        f"{len(source_workbooks)} runtime workbook(s) found",
    )
    record(
        "Simple local architecture",
        not (PROJECT_ROOT / "Dockerfile").exists()
        and not (PROJECT_ROOT / "docker-compose.yml").exists(),
        "no Docker dependency",
    )

    try:
        service = LinePulseService(repository=DecisionRepository(":memory:"))
        overview = service.overview()
        portfolio = service.portfolio()
        items = portfolio["items"]

        record(
            "Complete Class A portfolio",
            portfolio["total"] == 45 and len(items) == 45,
            f"{portfolio['total']} assets assessed",
        )
        rag_present = {
            status for status, count in portfolio["status_counts"].items() if count > 0
        }
        record(
            "High and low attention contrast",
            rag_present == {"RED", "AMBER", "GREEN"},
            str(portfolio["status_counts"]),
        )
        explainable = all(
            item.get("classification_reason")
            and item.get("evidence_passport")
            and item.get("recommended_action")
            and item.get("days_remaining") is not None
            for item in items
        )
        record(
            "Traceable recommendations",
            explainable,
            "reason + horizon + action + Evidence Passport for every asset",
        )
        ambiguous = [item for item in items if item.get("ambiguous_case")]
        record(
            "Ambiguous case for walkthrough",
            bool(ambiguous),
            (
                f"{ambiguous[0]['asset_id']}: {ambiguous[0].get('ambiguity_reason', 'flagged')}"
                if ambiguous
                else "no data-driven borderline case flagged"
            ),
        )
        model = overview["model"]
        honest_model = (
            model.get("production_validated") is False
            and model.get("is_failure_probability") is False
            and model.get("used_in_rag") is False
            and model.get("group_leakage_detected") is False
            and "AssetID" in model.get("validation_strategy", "")
        )
        record(
            "Honest grouped model validation",
            honest_model,
            model.get("semantic_label", "model metadata missing"),
        )
        audit = overview["data"]["data_quality"]
        quality_gate = (
            audit.get("missing_sensor_row_count") == 2
            and len(audit.get("duplicate_work_order_ids", [])) == 1
            and len(audit.get("orphan_maintenance_asset_ids", [])) == 1
            and "ANSWER_KEY" not in audit.get("worksheets_read", [])
        )
        record(
            "Data-trust gate",
            quality_gate,
            "missing weeks, duplicate work order and orphan record surfaced",
        )

        top = max(items, key=lambda row: float(row["attention_priority"]))
        decision = service.record_decision(
            top["asset_id"],
            "APPROVE",
            "Preflight owner review of the Evidence Passport.",
            owner="Preflight Owner",
        )
        outcome = service.record_outcome(
            decision["case"]["id"],
            "RESOLVED",
            notes="Preflight-only verified outcome.",
            verified_by="Preflight Owner",
        )
        human_gate = (
            decision["asset_status_changed"] is False
            and decision["equipment_action_taken"] is False
            and outcome["new_display_status"] == "GREEN"
            and outcome["original_model_assessment_preserved"] is True
            and outcome["equipment_action_taken"] is False
        )
        record(
            "Human authority and verified outcome",
            human_gate,
            "decision does not actuate; verified resolution changes display to green",
        )

        scenario = service.what_if(top["asset_id"], 20, 25)
        record(
            "Non-persistent what-if",
            scenario["simulation_only"]
            and not scenario["persisted"]
            and not scenario["equipment_action_taken"],
            "workload sensitivity shown without changing source data or equipment",
        )
    except Exception as exc:  # show a useful preflight report instead of a raw partial run
        record("Integrated service", False, f"{type(exc).__name__}: {exc}")

    try:
        api_module = importlib.import_module("api.main")
        paths = {
            route.path
            for route in api_module.app.routes
            if hasattr(route, "path")
        }
        required_paths = {
            "/api/v1/health",
            "/api/v1/readiness",
            "/api/v1/portfolio",
            "/api/v1/decisions",
        }
        record(
            "Backend routes",
            required_paths <= paths,
            f"{len(paths)} routes available",
        )
    except Exception as exc:
        record("Backend routes", False, f"{type(exc).__name__}: {exc}")

    print("\nLinePulse AI demo preflight")
    print("=" * 52)
    for check in checks:
        symbol = "PASS" if check.passed else "FAIL"
        print(f"[{symbol}] {check.label}: {check.detail}")

    failed = [check for check in checks if not check.passed]
    print("=" * 52)
    if failed:
        print(f"NOT READY: resolve {len(failed)} failed check(s) before the demo.")
        raise SystemExit(1)
    print("READY: the local demo passed every preflight check.")


if __name__ == "__main__":
    main()
