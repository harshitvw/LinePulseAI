"""Fast end-to-end verification using only in-memory human-decision storage."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from linepulse.repository import DecisionRepository  # noqa: E402
from linepulse.service import LinePulseService  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    service = LinePulseService(repository=DecisionRepository(":memory:"))
    overview = service.overview()
    portfolio = service.portfolio()
    items = portfolio["items"]

    require(overview["status"] == "ready", "service is not ready")
    require(portfolio["total"] == 45, "official portfolio must contain 45 assets")
    require(len(items) == 45, "portfolio response is incomplete")
    require(
        set(portfolio["status_counts"]) == {"RED", "AMBER", "GREEN"},
        "RAG status summary is incomplete",
    )
    require(
        all(item["evidence_passport"] for item in items),
        "every asset needs an Evidence Passport",
    )
    require(
        all(item.get("classification_reason") for item in items),
        "every asset needs a classification reason",
    )
    require(
        all(item.get("days_remaining") is not None for item in items),
        "every model assessment needs a planning horizon",
    )
    require(
        overview["equipment_write_capability"] is False,
        "equipment write capability must stay disabled",
    )
    require(
        overview["model"]["production_validated"] is False,
        "synthetic model must not be marked production validated",
    )
    require(
        overview["model"].get("used_in_rag") is False,
        "ScenarioFlag-trained model must remain advisory and outside RAG",
    )

    top = max(items, key=lambda row: float(row["attention_priority"]))
    what_if = service.what_if(top["asset_id"], 20, 25)
    require(what_if["persisted"] is False, "what-if scenario must not persist")
    require(
        what_if["equipment_action_taken"] is False,
        "what-if scenario must never actuate equipment",
    )

    audit = overview["data"]["data_quality"]
    print("LinePulse AI smoke test: PASS")
    print(f"  Official Class A assets: {portfolio['total']}")
    print(f"  RAG distribution: {portfolio['status_counts']}")
    print(
        "  Model: "
        f"{overview['model'].get('model_family', 'degradation detector')} | "
        f"{overview['model'].get('validation_strategy', 'grouped validation')}"
    )
    print(
        "  Data-quality gate: "
        f"{audit['missing_sensor_row_count']} missing sensor weeks, "
        f"{len(audit['duplicate_work_order_ids'])} duplicate work-order ID, "
        f"{len(audit['orphan_maintenance_asset_ids'])} orphan maintenance asset"
    )
    print(
        "  Top current attention item: "
        f"{top['asset_id']} | {top['status']} | "
        f"priority {top['attention_priority']:.1f}/100 | "
        f"planning horizon {top['days_remaining']} days"
    )
    print("  Safety gate: human approval required; equipment writes disabled")


if __name__ == "__main__":
    main()
