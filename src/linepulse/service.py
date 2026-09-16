"""Application service for the LinePulse AI decision-support workflow."""

from __future__ import annotations

import dataclasses
import datetime as dt
import importlib.util
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from .analytics import load_model_bundle, train_degradation_model
from .data import load_official_data
from .repository import DecisionRepository
from .risk import build_asset_assessments


STATUS_ORDER = {"RED": 0, "AMBER": 1, "GREEN": 2}
OUTCOME_STATUS = {
    "RESOLVED": "GREEN",
    "PARTIAL": "AMBER",
    "UNRESOLVED": "RED",
}
STATUS_COLOURS = {
    "RED": "#D92D20",
    "AMBER": "#F59E0B",
    "GREEN": "#16A34A",
}
HUMAN_LIFECYCLE = [
    "AI_RECOMMENDATION",
    "AWAITING_OWNER",
    "APPROVED_OR_MODIFIED_OR_REJECTED",
    "OUTCOME_PENDING",
    "VERIFIED",
]


def _to_builtin(value: Any) -> Any:
    """Convert pandas/numpy/date values into JSON-safe Python values."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if dataclasses.is_dataclass(value):
        return _to_builtin(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(key): _to_builtin(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_builtin(item) for item in value]
    if hasattr(value, "item") and callable(value.item):
        try:
            return _to_builtin(value.item())
        except (TypeError, ValueError):
            pass
    return str(value)


def find_project_root(start: str | Path | None = None) -> Path:
    """Locate the project root without depending on the caller's directory."""

    configured = os.getenv("LINEPULSE_PROJECT_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()

    candidates = [Path(start).resolve()] if start else []
    candidates.extend([Path(__file__).resolve(), Path.cwd().resolve()])
    for candidate in candidates:
        candidate = candidate if candidate.is_dir() else candidate.parent
        for directory in (candidate, *candidate.parents):
            if (directory / "pyproject.toml").exists() or (
                (directory / "src" / "linepulse").is_dir()
                and (directory / "data").is_dir()
            ):
                return directory
    return Path(__file__).resolve().parents[2]


def _resolve_data_path(project_root: Path, supplied: str | Path | None) -> Path:
    configured = supplied or os.getenv("LINEPULSE_DATA_PATH")
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = project_root / path
        if not path.exists():
            raise FileNotFoundError(f"Official dataset not found: {path}")
        return path.resolve()

    candidates = (
        project_root / "data" / "source" / "Synthetic_Dataset.xlsx",
        project_root / "data" / "Synthetic_Dataset.xlsx",
    )
    for path in candidates:
        if path.exists():
            return path.resolve()
    raise FileNotFoundError(
        "Official Synthetic_Dataset.xlsx was not found under data/source. "
        "No fallback or earlier dataset will be used."
    )


class LinePulseService:
    """Coordinate source data, the degradation model and human review memory.

    The model assessment is immutable during a running service.  A human
    decision records intent only.  A *verified* outcome can change the status
    displayed by the workflow, while the original assessment and evidence stay
    attached for auditability.
    """

    def __init__(
        self,
        *,
        data_path: str | Path | None = None,
        model_path: str | Path | None = None,
        db_path: str | Path | None = None,
        project_root: str | Path | None = None,
        data_bundle: Any | None = None,
        model_bundle: Any | None = None,
        assessments: list[dict[str, Any]] | None = None,
        repository: DecisionRepository | None = None,
    ) -> None:
        self.project_root = find_project_root(project_root)
        self.data_path = _resolve_data_path(self.project_root, data_path)
        self.model_path = self._project_path(
            model_path or os.getenv("LINEPULSE_MODEL_PATH") or "artifacts/degradation_model.joblib"
        )
        resolved_db_path: str | Path = (
            db_path
            or os.getenv("LINEPULSE_DB_PATH")
            or (self.project_root / "runtime" / "linepulse.db")
        )
        if str(resolved_db_path) != ":memory:":
            resolved_db_path = self._project_path(resolved_db_path)

        self.bundle = data_bundle or load_official_data(self.data_path)
        self.model_bundle = model_bundle or self._load_or_train_model()
        built = assessments or build_asset_assessments(self.bundle, self.model_bundle)
        self._base_assessments = {
            str(item["asset_id"]): _to_builtin(deepcopy(item)) for item in built
        }
        if not self._base_assessments:
            raise ValueError("No Class A asset assessments were produced")
        self.repository = repository or DecisionRepository(resolved_db_path)

    def _project_path(self, path: str | Path) -> Path:
        result = Path(path).expanduser()
        if not result.is_absolute():
            result = self.project_root / result
        return result.resolve()

    def _load_or_train_model(self) -> Any:
        if self.model_path.exists():
            try:
                loaded = load_model_bundle(self.model_path)
                metadata = getattr(loaded, "metadata", {})
                same_source = (
                    isinstance(metadata, dict)
                    and metadata.get("source_sha256") == self.bundle.source_sha256
                )
                same_features = list(getattr(loaded, "feature_names", [])) == list(
                    self.bundle.model_features
                )
                runtime_has_xgboost = importlib.util.find_spec("xgboost") is not None
                same_model_family = (
                    not runtime_has_xgboost
                    or bool(metadata.get("xgboost_available", False))
                )
                if same_source and same_features and same_model_family:
                    loaded.metadata = {**metadata, "loaded_from_artifact": True}
                    return loaded
            except Exception:
                # An incompatible/stale artifact must never prevent a demo.  It
                # is replaced from the one official workbook only.
                pass
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        trained = train_degradation_model(self.bundle, artifact_path=self.model_path)
        if hasattr(trained, "metadata") and isinstance(trained.metadata, dict):
            trained.metadata = {**trained.metadata, "loaded_from_artifact": False}
        return trained

    @staticmethod
    def _current_case_state(case: dict[str, Any]) -> str:
        if case.get("outcome"):
            return "VERIFIED"
        return {
            "APPROVE": "OUTCOME_PENDING",
            "MODIFY": "OUTCOME_PENDING",
            "REJECT": "REJECTED",
        }.get(str(case.get("decision", "")).upper(), "AWAITING_OWNER")

    @classmethod
    def _decorate_case(cls, case: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(case)
        result["case_id"] = result.get("id")
        decision = str(result.get("decision", "")).upper()
        outcome = result.get("outcome")
        decision_state = {
            "APPROVE": "APPROVED",
            "MODIFY": "MODIFIED",
            "REJECT": "REJECTED",
        }.get(decision)
        path = ["AI_RECOMMENDATION", "AWAITING_OWNER"]
        if decision_state:
            path.append(decision_state)
        if decision in {"APPROVE", "MODIFY"}:
            path.append("OUTCOME_PENDING")
        if outcome:
            path.append("VERIFIED")
        result["lifecycle_state"] = cls._current_case_state(result)
        result["lifecycle_path"] = path
        result["equipment_action_taken"] = False
        return _to_builtin(result)

    def _assessment_with_workflow(
        self,
        base: dict[str, Any],
        latest_outcome: dict[str, Any] | None,
        latest_case: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        item = deepcopy(base)
        item["model_status"] = str(base["status"]).upper()
        item["model_days_remaining"] = base.get(
            "days_remaining", base.get("planning_horizon_days")
        )
        item["model_attention_priority"] = base.get("attention_priority")
        item["status_source"] = "MODEL_ASSESSMENT"
        item["workflow_state"] = "AWAITING_OWNER"
        item["equipment_action_taken"] = False
        item["equipment_write_capability"] = False
        item["human_approval"] = "PENDING"
        item["human_gate"] = {
            "state": "AWAITING_OWNER",
            "owner": "Equipment Owner",
            "allowed_decisions": ["APPROVE", "MODIFY", "REJECT"],
            "automatic_equipment_action": False,
        }

        if latest_case:
            case_state = self._current_case_state(latest_case)
            item["workflow_state"] = case_state
            item["human_approval"] = str(latest_case.get("decision", "PENDING"))
            item["active_case_id"] = latest_case.get("id")
            item["human_gate"] = {
                **item["human_gate"],
                "state": case_state,
                "owner": latest_case.get("owner") or "Equipment Owner",
            }

        if latest_outcome:
            outcome = str(latest_outcome["outcome"]).upper()
            item["status"] = OUTCOME_STATUS[outcome]
            item["status_colour"] = STATUS_COLOURS[item["status"]]
            item["status_label"] = {
                "RESOLVED": "Resolved — monitor",
                "PARTIAL": "Partially resolved — inspect",
                "UNRESOLVED": "Unresolved — review now",
            }[outcome]
            item["status_source"] = "VERIFIED_MAINTENANCE_OUTCOME"
            outcome_is_current_case = not latest_case or int(
                latest_outcome.get("decision_id") or -1
            ) == int(latest_case.get("id") or -2)
            if outcome_is_current_case:
                item["workflow_state"] = "VERIFIED"
                item["human_approval"] = "COMPLETED"
                item["human_gate"] = {
                    **item["human_gate"],
                    "state": "VERIFIED",
                    "verified_outcome": outcome,
                }
            item["verified_outcome"] = outcome
            item["outcome_case_id"] = latest_outcome.get("decision_id")
            item["outcome_verified_at"] = latest_outcome.get("created_at")
            item["outcome_note"] = latest_outcome.get("notes", "")
            item["display_reason"] = (
                "The displayed colour comes from a verified maintenance outcome; "
                "the original model assessment remains available below."
            )
            original_horizon = item.get("model_days_remaining")
            item["reason_summary"] = (
                f"The Equipment Owner verified the outcome as {outcome}. "
                f"Before work, the model status was {item['model_status']} with a "
                f"{original_horizon}-day planning horizon."
            )
            item["classification_reason"] = (
                f"{item['status']} is the post-maintenance workflow colour mapped "
                f"from the verified {outcome} outcome; it is not a new sensor prediction."
            )
            item["tooltip"] = (
                f"Why {item['status']}? The Equipment Owner verified {outcome}. "
                f"Original model result: {item['model_status']} with "
                f"{original_horizon} days remaining. Fresh sensor evidence is required "
                "for a new technical assessment."
            )
            if outcome == "RESOLVED":
                # A resolved workflow is green, but we do not invent a new
                # remaining-life estimate before fresh telemetry arrives.
                item["days_remaining"] = None
                item["planning_horizon_days"] = None
                item["planning_window"] = "Resolved; confirm on next sensor refresh"
            elif outcome == "PARTIAL":
                item["planning_window"] = "Re-inspect during the next planned stop"
            else:
                item["planning_window"] = "Immediate owner review"
        return _to_builtin(item)

    def _all_with_workflow(self) -> list[dict[str, Any]]:
        outcomes = self.repository.latest_asset_outcomes()
        recent_cases = self.repository.list_cases(limit=500)
        cases_by_asset: dict[str, dict[str, Any]] = {}
        for case in recent_cases:
            cases_by_asset.setdefault(str(case["asset_id"]), case)
        items = [
            self._assessment_with_workflow(
                base,
                outcomes.get(asset_id),
                cases_by_asset.get(asset_id),
            )
            for asset_id, base in self._base_assessments.items()
        ]
        return sorted(
            items,
            key=lambda item: (
                STATUS_ORDER.get(str(item.get("status", "GREEN")).upper(), 9),
                1 if item.get("verified_outcome") == "RESOLVED" else 0,
                -float(item.get("attention_priority") or 0.0),
                str(item.get("asset_id", "")),
            ),
        )

    def _model_summary(self) -> dict[str, Any]:
        model = self.model_bundle
        metadata = getattr(model, "metadata", {})
        summary: dict[str, Any] = (
            _to_builtin(metadata) if isinstance(metadata, dict) else {}
        )
        for name in (
            "algorithm",
            "model_name",
            "target_name",
            "metrics",
            "validation",
            "training_rows",
            "feature_names",
            "loaded_from_artifact",
            "artifact_path",
        ):
            if hasattr(model, name):
                summary[name] = _to_builtin(getattr(model, name))
        summary.setdefault("artifact_path", str(self.model_path))
        summary["production_validated"] = False
        summary.setdefault(
            "semantic_label",
            "degradation likelihood (not a real-world failure probability)",
        )
        summary["is_failure_probability"] = False
        summary["used_in_rag"] = False
        summary["claim"] = (
            "Degradation-signal likelihood on the supplied synthetic workbook; "
            "not a calibrated failure probability or certified safety limit."
        )
        return summary

    def _data_summary(self) -> dict[str, Any]:
        quality = _to_builtin(getattr(self.bundle, "data_quality", {}))
        weekly = getattr(self.bundle, "weekly", None)
        assets = getattr(self.bundle, "assets", None)
        return {
            "source": self.data_path.name,
            "scope": "Official hackathon synthetic workbook only",
            "asset_count": len(assets) if assets is not None else len(self._base_assessments),
            "weekly_rows": len(weekly) if weekly is not None else None,
            "analysis_date": _to_builtin(getattr(self.bundle, "analysis_date", None)),
            "data_quality": quality,
            "excluded_from_model_inputs": [
                "AssetID and row IDs",
                "ScenarioFlag (used only to form the synthetic training target)",
                "LinkedFailureMode",
                "hidden ANSWER_KEY",
                "future maintenance records",
            ],
        }

    def _learning_summary(self) -> dict[str, Any]:
        cases = self.repository.list_cases(limit=500)
        outcomes = [case for case in cases if case.get("outcome")]
        outcome_counts = {
            outcome: sum(case.get("outcome") == outcome for case in outcomes)
            for outcome in ("RESOLVED", "PARTIAL", "UNRESOLVED")
        }
        return {
            **self.repository.counts(),
            "outcome_counts": outcome_counts,
            "verified_examples_available": len(outcomes),
            "learning_method": (
                "Verified outcomes become case-based recommendation memory matched "
                "by asset type and failure mode. Approvals are not treated as labels."
            ),
            "degradation_model_retrained_from_approvals": False,
        }

    def overview(self) -> dict[str, Any]:
        items = self._all_with_workflow()
        counts = {
            status: sum(str(item.get("status", "")).upper() == status for item in items)
            for status in ("RED", "AMBER", "GREEN")
        }
        model_counts = {
            status: sum(item.get("model_status") == status for item in items)
            for status in ("RED", "AMBER", "GREEN")
        }
        return {
            "status": "ready",
            "total_assets": len(items),
            "status_counts": counts,
            "original_model_status_counts": model_counts,
            "urgent_review_count": counts["RED"],
            "top_attention": items[:5],
            "model": self._model_summary(),
            "data": self._data_summary(),
            "learning_summary": self._learning_summary(),
            "human_in_the_loop": {
                "owner": "Equipment Owner",
                "lifecycle": HUMAN_LIFECYCLE,
                "automatic_equipment_action": False,
                "status_change_rule": (
                    "A decision alone changes no asset colour. Only a verified "
                    "RESOLVED/PARTIAL/UNRESOLVED outcome sets green/amber/red."
                ),
            },
            "equipment_write_capability": False,
            "disclaimer": (
                "Decision support only. All supplied operational data is synthetic; "
                "the Equipment Owner retains final authority."
            ),
        }

    def portfolio(
        self,
        *,
        status: str | None = None,
        line: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        items = self._all_with_workflow()
        if status:
            normalized = str(status).upper()
            if normalized not in STATUS_ORDER:
                raise ValueError("status must be RED, AMBER or GREEN")
            items = [item for item in items if str(item.get("status")).upper() == normalized]
        if line:
            items = [item for item in items if str(item.get("line")) == str(line)]
        if limit is not None:
            items = items[: max(1, min(int(limit), 100))]

        counts = {
            rag: sum(str(item.get("status", "")).upper() == rag for item in items)
            for rag in ("RED", "AMBER", "GREEN")
        }
        return {
            "total": len(items),
            "status_counts": counts,
            "items": items,
            "generated_from": self.data_path.name,
            "equipment_write_capability": False,
        }

    def _find_base(self, asset_id: str) -> dict[str, Any]:
        try:
            return deepcopy(self._base_assessments[str(asset_id)])
        except KeyError as exc:
            raise KeyError(str(asset_id)) from exc

    def asset_detail(self, asset_id: str) -> dict[str, Any]:
        base = self._find_base(asset_id)
        latest = self.repository.latest_asset_outcomes().get(str(asset_id))
        asset_cases = self.repository.list_cases(limit=20, asset_id=str(asset_id))
        display = self._assessment_with_workflow(
            base, latest, asset_cases[0] if asset_cases else None
        )
        exact_cases = self.repository.successful_similar_cases(
            str(base.get("failure_mode", "")),
            asset_type=str(base.get("type") or base.get("asset_type") or ""),
            limit=5,
        )
        broader_cases = self.repository.successful_similar_cases(
            str(base.get("failure_mode", "")), limit=5
        )
        learned_option = exact_cases[0]["selected_action"] if exact_cases else None
        learning_summary = {
            "same_type_and_mode_resolved_cases": len(exact_cases),
            "same_mode_resolved_cases": len(broader_cases),
            "learned_action_option": learned_option,
            "source": "VERIFIED_OUTCOME_MEMORY" if learned_option else "NO_MATCH_YET",
            "note": (
                "Verified outcomes can inform the next recommendation, but do "
                "not overwrite sensor evidence or retrain on approvals."
            ),
            "examples": exact_cases[:3],
        }
        # Return the assessment fields at the top level for a simple frontend,
        # and retain the explicit nested object for API consumers that prefer it.
        return {
            **display,
            "asset": display,
            "original_model_assessment": _to_builtin(base),
            "decision_memory": learning_summary,
            "learning_summary": learning_summary,
            "human_gate": {
                **display.get("human_gate", {}),
                "state": display.get("workflow_state", "AWAITING_OWNER"),
                "owner": display.get("human_gate", {}).get(
                    "owner", "Equipment Owner"
                ),
                "allowed_decisions": ["APPROVE", "MODIFY", "REJECT"],
                "allowed_outcomes": ["RESOLVED", "PARTIAL", "UNRESOLVED"],
                "equipment_action_taken": False,
            },
            "cases": self.list_cases(asset_id=str(asset_id), limit=20),
        }

    def list_cases(
        self, *, limit: int = 100, asset_id: str | None = None
    ) -> list[dict[str, Any]]:
        return [
            self._decorate_case(case)
            for case in self.repository.list_cases(limit=limit, asset_id=asset_id)
        ]

    def get_case(self, case_id: int) -> dict[str, Any]:
        case = self._decorate_case(self.repository.get_case(case_id))
        case["outcome_history"] = self.repository.outcome_history(case_id)
        return case

    def record_decision(
        self,
        asset_id: str,
        decision: str,
        rationale: str,
        owner: str = "Equipment Owner",
        modified_action: str | None = None,
    ) -> dict[str, Any]:
        base = self._find_base(asset_id)
        case_id = self.repository.add_decision(
            asset_id=str(asset_id),
            decision=decision,
            rationale=rationale,
            owner=owner,
            failure_mode=str(base.get("failure_mode", "Unspecified degradation")),
            recommended_action=str(base.get("recommended_action", "Inspect asset")),
            modified_action=modified_action,
            model_status=str(base.get("status", "AMBER")),
            model_risk_score=float(
                base.get("attention_priority", base.get("technical_risk", 0.0))
            ),
            model_horizon_days=int(
                base.get("days_remaining")
                or base.get("planning_horizon_days")
                or 0
            ),
            model_snapshot=base,
            evidence=base.get("evidence_passport", []),
        )
        case = self._decorate_case(self.repository.get_case(case_id))
        return {
            "status": "DECISION_RECORDED",
            "case": case,
            "asset_status_changed": False,
            "equipment_action_taken": False,
            "message": (
                "The decision is stored for audit. No equipment action was taken, "
                "and the asset colour will not change until an outcome is verified."
            ),
        }

    def record_outcome(
        self,
        case_id: int,
        outcome: str,
        notes: str = "",
        verified_by: str = "Equipment Owner",
    ) -> dict[str, Any]:
        before = self.repository.get_case(case_id)
        previous = self.asset_detail(before["asset_id"])["asset"]
        recorded = self.repository.add_outcome(
            int(case_id), outcome, notes=notes, verified_by=verified_by
        )
        updated = self.asset_detail(recorded["asset_id"])["asset"]
        return {
            "status": "VERIFIED_OUTCOME_RECORDED",
            "case": self._decorate_case(recorded),
            "asset_id": recorded["asset_id"],
            "previous_display_status": previous["status"],
            "new_display_status": updated["status"],
            "original_model_status": updated["model_status"],
            "original_model_assessment_preserved": True,
            "equipment_action_taken": False,
            "message": (
                "Workflow colour updated from verified human evidence. The model's "
                "original risk score, horizon and Evidence Passport were preserved."
            ),
        }

    @staticmethod
    def _scenario_status(priority: float, days: int) -> str:
        if days <= 10 or priority >= 80:
            return "RED"
        if days <= 30 or priority >= 55:
            return "AMBER"
        return "GREEN"

    def what_if(
        self,
        asset_id: str,
        duty_reduction_pct: float,
        start_stop_reduction_pct: float,
    ) -> dict[str, Any]:
        base = self._find_base(asset_id)
        duty = float(duty_reduction_pct)
        starts = float(start_stop_reduction_pct)
        if not 0 <= duty <= 100 or not 0 <= starts <= 100:
            raise ValueError("workload reductions must be between 0 and 100 percent")

        original_risk = float(base.get("technical_risk", 0.0))
        original_priority = float(base.get("attention_priority", original_risk))
        original_days = max(
            0,
            int(
                base.get("days_remaining")
                or base.get("planning_horizon_days")
                or 0
            ),
        )

        # This is deliberately a bounded sensitivity calculation, not a claim
        # that maintenance or workload control has already changed the machine.
        stress_relief = 0.20 * (duty / 100.0) + 0.12 * (starts / 100.0)
        new_risk = max(0.0, original_risk * (1.0 - stress_relief))
        technical_delta = original_risk - new_risk
        new_priority = max(0.0, original_priority - 0.75 * technical_delta)
        if original_days <= 0:
            new_days = round(10.0 * stress_relief)
        else:
            new_days = round(original_days * (1.0 + 0.60 * duty / 100 + 0.35 * starts / 100))
        new_days = int(max(0, min(new_days, 90)))

        return {
            "asset_id": str(asset_id),
            "simulation_only": True,
            "persisted": False,
            "equipment_action_taken": False,
            "inputs": {
                "duty_reduction_pct": duty,
                "start_stop_reduction_pct": starts,
            },
            "original": {
                "status": base["status"],
                "days_remaining": original_days,
                "technical_risk": round(original_risk, 1),
                "attention_priority": round(original_priority, 1),
            },
            "scenario": {
                "status": self._scenario_status(new_priority, new_days),
                "days_remaining": new_days,
                "technical_risk": round(new_risk, 1),
                "attention_priority": round(new_priority, 1),
            },
            "assumption": (
                "A transparent bounded sensitivity estimate: reduced duty and "
                "start-stop stress affect only the usage-stress portion of risk. "
                "It is not a new model prediction and does not write to equipment."
            ),
            # Compact aliases keep the browser client simple.
            "baseline_priority": round(original_priority, 1),
            "scenario_priority": round(new_priority, 1),
            "baseline_days": original_days,
            "scenario_days": new_days,
            "explanation": (
                "Lower workload reduces only the transparent usage-stress term; "
                "condition evidence, business impact and maintenance history remain."
            ),
        }

    def reset_demo(self) -> dict[str, Any]:
        self.repository.clear()
        return {
            "status": "DEMO_MEMORY_RESET",
            "source_data_changed": False,
            "model_changed": False,
            "equipment_action_taken": False,
            "status_counts": self.overview()["status_counts"],
        }


# Backwards-friendly name retained for simple imports in notebooks/scripts.
Service = LinePulseService
