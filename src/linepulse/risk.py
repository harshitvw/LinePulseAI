"""Transparent, cross-system maintenance risk and planning-horizon engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd

from .analytics import ModelBundle, SEMANTIC_LABEL
from .data import DataBundle


Direction = Literal["high", "low"]


@dataclass(frozen=True, slots=True)
class SignalSpec:
    column: str
    label: str
    unit: str
    direction: Direction
    failure_mode: str
    action: str


SIGNALS = (
    SignalSpec(
        "MaxTempC",
        "maximum temperature",
        "°C",
        "high",
        "Overheating / thermal stress",
        "Inspect cooling, airflow and lubrication; confirm temperature with a handheld measurement.",
    ),
    SignalSpec(
        "MaxVibration_mm_s",
        "maximum vibration",
        "mm/s",
        "high",
        "Abnormal vibration / mechanical wear",
        "Inspect bearings, alignment and mounting; verify vibration before replacing parts.",
    ),
    SignalSpec(
        "MaxCurrent_A",
        "maximum motor current",
        "A",
        "high",
        "Excess current / mechanical load",
        "Inspect mechanical load, drive condition and electrical connections; compare current under a controlled cycle.",
    ),
    SignalSpec(
        "AvgPressure_bar",
        "average pressure",
        "bar",
        "low",
        "Pressure loss / pneumatic or hydraulic leak",
        "Inspect pressure supply, filters, valves and seals; perform a controlled leak test.",
    ),
    SignalSpec(
        "CycleTime_s",
        "cycle time",
        "s",
        "high",
        "Cycle-time drift / process resistance",
        "Inspect motion sequence, tooling friction and controls timing; compare a reference cycle.",
    ),
)

STATUS_COLOURS = {
    "RED": "#D92D20",
    "AMBER": "#F59E0B",
    "GREEN": "#16A34A",
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if np.isfinite(number) else default


def _optional_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _percentile(value: float | None, peers: pd.Series, direction: Direction = "high") -> float:
    if value is None:
        return 50.0
    clean = pd.to_numeric(peers, errors="coerce").dropna().to_numpy(dtype=float)
    if clean.size == 0:
        return 50.0
    percentile = 100.0 * (np.sum(clean < value) + 0.5 * np.sum(clean == value)) / clean.size
    return float(percentile if direction == "high" else 100.0 - percentile)


def _risk_from_percentile(percentile: float) -> float:
    # Below the peer median is not evidence of degradation.  The transformation
    # intentionally concentrates risk in the upper half of the peer distribution.
    return float(np.clip((percentile - 45.0) / 55.0 * 100.0, 0.0, 100.0))


def _asset_slope(frame: pd.DataFrame, column: str) -> tuple[float | None, float | None, int]:
    valid = frame[["WeekStarting", column]].dropna().sort_values("WeekStarting")
    count = int(len(valid))
    if count == 0:
        return None, None, 0
    latest = float(valid[column].iloc[-1])
    if count < 2:
        return latest, None, count
    day = (valid["WeekStarting"] - valid["WeekStarting"].min()).dt.days.to_numpy(dtype=float)
    slope_per_day = float(np.polyfit(day, valid[column].to_numpy(dtype=float), 1)[0])
    return latest, slope_per_day, count


def _all_asset_slopes(weekly: pd.DataFrame, column: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for asset_id, asset_frame in weekly.groupby("AssetID", sort=False):
        latest, slope, count = _asset_slope(asset_frame, column)
        rows.append(
            {
                "AssetID": asset_id,
                "AssetType": str(asset_frame["AssetType"].iloc[-1]),
                "latest": latest,
                "slope": slope,
                "count": count,
            }
        )
    return pd.DataFrame(rows)


def _peer_rows(weekly: pd.DataFrame, asset_type: str, column: str) -> pd.Series:
    typed = weekly.loc[weekly["AssetType"].astype(str) == str(asset_type), column]
    typed = pd.to_numeric(typed, errors="coerce").dropna()
    if len(typed) >= 8:
        return typed
    return pd.to_numeric(weekly[column], errors="coerce").dropna()


def _peer_limit(peers: pd.Series, direction: Direction) -> float | None:
    clean = pd.to_numeric(peers, errors="coerce").dropna().to_numpy(dtype=float)
    if clean.size < 4:
        return None
    median = float(np.median(clean))
    mad_sigma = 1.4826 * float(np.median(np.abs(clean - median)))
    q25, q75 = np.percentile(clean, [25, 75])
    scale = mad_sigma if mad_sigma > 1e-9 else float((q75 - q25) / 1.349)
    if scale <= 1e-9:
        scale = max(abs(median) * 0.05, 0.01)
    if direction == "high":
        return float(max(np.percentile(clean, 95), median + 3.1 * scale))
    return float(min(np.percentile(clean, 5), median - 3.1 * scale))


def _days_to_limit(
    latest: float | None,
    slope_per_day: float | None,
    limit: float | None,
    direction: Direction,
) -> int | None:
    if latest is None or limit is None:
        return None
    if direction == "high":
        if latest >= limit:
            return 0
        if slope_per_day is None or slope_per_day <= 0:
            return None
        days = (limit - latest) / slope_per_day
    else:
        if latest <= limit:
            return 0
        if slope_per_day is None or slope_per_day >= 0:
            return None
        days = (limit - latest) / slope_per_day
    if not np.isfinite(days) or days < 0:
        return None
    return int(np.clip(np.ceil(days), 0, 365))


def _signal_evidence(
    data: DataBundle,
    asset_frame: pd.DataFrame,
    spec: SignalSpec,
    slopes: pd.DataFrame,
) -> dict[str, Any]:
    asset_type = str(asset_frame["AssetType"].iloc[-1])
    latest, slope_per_day, point_count = _asset_slope(asset_frame, spec.column)
    peers = _peer_rows(data.weekly, asset_type, spec.column)
    limit = _peer_limit(peers, spec.direction)
    level_percentile = _percentile(latest, peers, spec.direction)

    asset_slopes = slopes.loc[slopes["AssetType"] == asset_type, "slope"].dropna()
    if len(asset_slopes) < 4:
        asset_slopes = slopes["slope"].dropna()
    slope_per_week = None if slope_per_day is None else slope_per_day * 7.0
    bad_slope = (
        slope_per_week is not None
        and ((spec.direction == "high" and slope_per_week > 0) or (spec.direction == "low" and slope_per_week < 0))
    )
    trend_percentile = (
        _percentile(slope_per_week, asset_slopes * 7.0, spec.direction) if bad_slope else 45.0
    )
    level_risk = _risk_from_percentile(level_percentile)
    trend_risk = _risk_from_percentile(trend_percentile)
    evidence_score = float(np.clip(0.63 * level_risk + 0.37 * trend_risk, 0.0, 100.0))
    days = _days_to_limit(latest, slope_per_day, limit, spec.direction)

    if latest is None:
        message = f"{spec.label.capitalize()} is unavailable for the latest usable record."
    else:
        trend_text = "trend unavailable"
        if slope_per_week is not None:
            sign = "+" if slope_per_week >= 0 else ""
            trend_text = f"{sign}{slope_per_week:.2f} {spec.unit}/week"
        limit_text = "unavailable" if limit is None else f"{limit:.2f} {spec.unit}"
        message = (
            f"{spec.label.capitalize()} is {latest:.2f} {spec.unit}; "
            f"three-week trend {trend_text}; peer planning limit {limit_text}."
        )
    return {
        "source_sheet": "Sensor_Readings",
        "field": spec.column,
        "label": spec.label,
        "latest_value": None if latest is None else round(latest, 3),
        "unit": spec.unit,
        "trend_per_week": None if slope_per_week is None else round(slope_per_week, 3),
        "peer_warning_limit": None if limit is None else round(limit, 3),
        "limit_method": "asset-type peer median ± 3.1 robust sigma, no OEM safety claim",
        "unfavourable_direction": spec.direction,
        "days_to_peer_limit": days,
        "evidence_score": round(evidence_score, 1),
        "observed_weeks": point_count,
        "failure_mode_hypothesis": spec.failure_mode,
        "message": message,
    }


def _latest_metric_risk(
    latest: pd.Series,
    weekly: pd.DataFrame,
    column: str,
    direction: Direction = "high",
) -> float:
    value = _optional_number(latest.get(column))
    if value is None:
        return 35.0
    peers = _peer_rows(weekly, str(latest["AssetType"]), column)
    return _risk_from_percentile(_percentile(value, peers, direction))


def _asset_quality_flags(data: DataBundle, asset_id: str, latest: pd.Series) -> list[str]:
    flags: list[str] = []
    missing = [
        item["week_starting"]
        for item in data.data_quality["missing_sensor_asset_weeks"]
        if item["asset_id"] == asset_id
    ]
    if missing:
        flags.append("Missing sensor week: " + ", ".join(missing))
    if pd.isna(latest.get("LastPreventiveDate")):
        flags.append("No preventive work order is present in the supplied maintenance history")

    duplicated = set(data.data_quality["duplicate_work_order_ids"])
    if duplicated:
        affected = data.maintenance[
            data.maintenance["WorkOrderID"].astype(str).isin(duplicated)
            & data.maintenance["AssetID"].astype(str).eq(asset_id)
        ]
        if not affected.empty:
            flags.append("Duplicate work-order identifier affects maintenance evidence")
    return flags


def _planning_window(days: int) -> tuple[str, str, str]:
    if days <= 10:
        return "RED", "0-10 days", "Immediate review"
    if days <= 30:
        return "AMBER", "11-30 days", "Plan inspection"
    return "GREEN", ">30 days", "Continue monitoring"


def _hypothesis_and_action(
    top_signal: dict[str, Any],
    status: str,
) -> tuple[str, str, list[str]]:
    mode = str(top_signal["failure_mode_hypothesis"])
    spec = next(item for item in SIGNALS if item.column == top_signal["field"])
    if status == "RED":
        prefix = "Review at the next safe production stop. "
    elif status == "AMBER":
        prefix = "Schedule a targeted inspection within the planning window. "
    else:
        prefix = "Continue operation with monitoring. "
    primary = prefix + spec.action
    options = [
        "Continue with monitoring",
        "Inspect during a planned stop",
        "Temporarily reduce duty or start-stop stress",
        "Prepare a component swap if inspection confirms wear",
        "Escalate for a controlled shutdown review if evidence worsens",
    ]
    return mode, primary, options


def build_asset_assessments(
    data: DataBundle,
    model: ModelBundle | None = None,
) -> list[dict[str, Any]]:
    """Build one evidence-backed maintenance assessment per Class A asset.

    RAG is based on the estimated *planning horizon*.  It is not an autonomous
    trip limit.  Technical risk remains separate from business impact, and the
    final recommendation always passes through a human decision gate.
    """

    latest_rows = (
        data.weekly.sort_values(["AssetID", "WeekStarting"])
        .groupby("AssetID", as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )
    slopes_by_signal = {
        spec.column: _all_asset_slopes(data.weekly, spec.column) for spec in SIGNALS
    }

    if model is not None:
        model_scores = model.predict_likelihood(latest_rows)
        model_drivers = model.driver_contributions(latest_rows, top_n=3)
        # ScenarioFlag is an organizer hint, so its classifier remains an
        # explainability/corroboration signal and never determines RAG.
        model_weight = 0.0
        model_family = str(model.metadata.get("model_family", "degradation detector"))
    else:
        model_scores = np.full(len(latest_rows), np.nan)
        model_drivers = [[] for _ in range(len(latest_rows))]
        model_weight = 0.0
        model_family = "not available; transparent evidence engine used"

    impact_values = pd.to_numeric(latest_rows["BusinessImpactScore"], errors="coerce")
    lead_values = pd.to_numeric(latest_rows["ReplacementLeadDays"], errors="coerce")
    cost_values = pd.to_numeric(latest_rows["ReplacementCost_EUR"], errors="coerce")

    assessments: list[dict[str, Any]] = []
    for position, latest in latest_rows.iterrows():
        asset_id = str(latest["AssetID"])
        asset_frame = data.weekly[data.weekly["AssetID"].astype(str) == asset_id]
        signal_evidence = [
            _signal_evidence(data, asset_frame, spec, slopes_by_signal[spec.column])
            for spec in SIGNALS
        ]
        signal_evidence.sort(key=lambda item: item["evidence_score"], reverse=True)
        top_signal = signal_evidence[0]
        condition_score = float(
            0.72 * signal_evidence[0]["evidence_score"]
            + 0.28 * signal_evidence[1]["evidence_score"]
        )

        usage_score = float(
            0.42 * _latest_metric_risk(latest, data.weekly, "StartStopEvents")
            + 0.33 * _latest_metric_risk(latest, data.weekly, "DutyCyclePct")
            + 0.25 * _latest_metric_risk(latest, data.weekly, "CyclesRun")
        )
        production_score = float(
            0.65 * _latest_metric_risk(latest, data.weekly, "DemandIndex")
            + 0.35 * _latest_metric_risk(latest, data.weekly, "OvertimeHours")
        )
        quality_score = float(
            0.42 * _latest_metric_risk(latest, data.weekly, "ScrapRate_pct")
            + 0.33 * _latest_metric_risk(latest, data.weekly, "DefectCount")
            + 0.25 * _latest_metric_risk(latest, data.weekly, "ReworkCount")
        )
        overdue_ratio = _optional_number(latest.get("MaintenanceOverdueRatio"))
        maintenance_score = (
            42.0
            if overdue_ratio is None
            else float(np.clip((overdue_ratio - 0.55) / 1.05 * 100.0, 0.0, 100.0))
        )
        lifecycle_used = _number(latest.get("LifecycleUsedPct"))
        lifecycle_score = float(np.clip((lifecycle_used - 55.0) / 45.0 * 100.0, 0.0, 100.0))
        history_score = float(
            0.65 * _latest_metric_risk(latest, data.weekly, "CorrectiveWorkOrders90d")
            + 0.35 * _latest_metric_risk(latest, data.weekly, "MaintenanceDowntime90d")
        )
        raw_model_score = _optional_number(model_scores[position])
        model_score = condition_score if raw_model_score is None else raw_model_score

        fixed_weight = 1.0 - model_weight
        non_model = (
            0.43 * condition_score
            + 0.155 * maintenance_score
            + 0.115 * lifecycle_score
            + 0.11 * usage_score
            + 0.105 * quality_score
            + 0.045 * history_score
            + 0.04 * production_score
        )
        technical_risk = float(np.clip(fixed_weight * non_model + model_weight * model_score, 0, 100))

        impact = float(np.clip(_number(latest.get("BusinessImpactScore")) * 10.0, 0, 100))
        lead_percentile = _percentile(_optional_number(latest.get("ReplacementLeadDays")), lead_values)
        cost_percentile = _percentile(_optional_number(latest.get("ReplacementCost_EUR")), cost_values)
        attention_priority = float(
            np.clip(0.72 * technical_risk + 0.20 * impact + 0.05 * lead_percentile + 0.03 * cost_percentile, 0, 100)
        )

        horizon_candidates = [
            item["days_to_peer_limit"]
            for item in signal_evidence
            if item["days_to_peer_limit"] is not None and item["evidence_score"] >= 68
        ]
        days_since = _optional_number(latest.get("DaysSincePreventive"))
        interval = _optional_number(latest.get("MaintIntervalDays"))
        if overdue_ratio is not None and interval is not None and days_since is not None:
            # An overdue calendar interval merits planning, but does not by
            # itself justify an emergency red classification without condition
            # evidence.  Severe condition/lifecycle evidence has its own horizon.
            if overdue_ratio >= 1.0 and (
                condition_score >= 45 or lifecycle_score >= 55 or quality_score >= 60
            ):
                horizon_candidates.append(30)
            elif overdue_ratio >= 0.7:
                horizon_candidates.append(max(11, int(np.ceil(interval - days_since))))

        recent_daily_cycles = max(_number(asset_frame["CyclesRun"].tail(2).mean()) / 7.0, 1.0)
        remaining_cycles = _number(latest.get("RatedCycleLife")) - _number(latest.get("CumulativeCyclesEOW"))
        lifecycle_days = int(np.ceil(max(remaining_cycles, 0.0) / recent_daily_cycles))
        if lifecycle_days <= 90:
            horizon_candidates.append(lifecycle_days)

        estimated_days = min(horizon_candidates) if horizon_candidates else 90
        # Evidence intensity supplies a conservative planning window when a
        # three-point trend cannot yield a stable intercept.
        if technical_risk >= 74:
            estimated_days = min(estimated_days, 10)
        elif technical_risk >= 57:
            estimated_days = min(estimated_days, 30)
        estimated_days = int(np.clip(estimated_days, 0, 90))

        data_quality_flags = _asset_quality_flags(data, asset_id, latest)
        sensor_completeness = min(
            1.0,
            sum(item["observed_weeks"] for item in signal_evidence) / (len(SIGNALS) * 3.0),
        )
        confidence = 55.0 + 35.0 * sensor_completeness
        if pd.notna(latest.get("LastPreventiveDate")):
            confidence += 7.0
        if not data_quality_flags:
            confidence += 3.0
        confidence = float(np.clip(confidence, 0, 100))

        status, planning_window, status_label = _planning_window(estimated_days)
        # Broken/missing evidence can never be silently green.
        material_data_gap = any(
            flag.startswith("Missing sensor week")
            or flag.startswith("Duplicate work-order")
            for flag in data_quality_flags
        )
        if material_data_gap and status == "GREEN":
            status, planning_window, status_label = "AMBER", "11-30 days", "Resolve data gap"
            estimated_days = 30

        top_signal_horizon = top_signal.get("days_to_peer_limit")
        near_boundary = bool(
            top_signal_horizon is not None
            and top_signal["evidence_score"] >= 68
            and (9 <= int(top_signal_horizon) <= 11 or 29 <= int(top_signal_horizon) <= 31)
        )
        evidence_conflict = abs(model_score - condition_score) >= 50
        is_ambiguous = bool(material_data_gap or near_boundary or evidence_conflict)
        ambiguity_reasons: list[str] = []
        if material_data_gap:
            ambiguity_reasons.append("incomplete or conflicting source records")
        if near_boundary:
            ambiguity_reasons.append("planning horizon is close to a RAG boundary")
        if evidence_conflict:
            ambiguity_reasons.append("model likelihood and transparent condition evidence diverge")
        ambiguity_reason = "; ".join(ambiguity_reasons) if ambiguity_reasons else ""

        failure_mode, action, recommendation_options = _hypothesis_and_action(top_signal, status)
        why = (
            f"{top_signal['label'].capitalize()} contributes the strongest condition evidence "
            f"({top_signal['evidence_score']:.1f}/100). Technical risk is {technical_risk:.1f}/100; "
            f"business impact is {impact:.0f}/100."
        )
        classification_reason = (
            f"{status} means the evidence-derived maintenance planning horizon is "
            f"{estimated_days} days ({planning_window}). These are project-derived peer limits, "
            "not OEM safety trip limits."
        )
        tooltip = f"Why {status}? {why} {classification_reason}"

        maintenance_message = (
            "Preventive history unavailable in the supplied window."
            if overdue_ratio is None
            else f"Maintenance interval use is {overdue_ratio * 100:.0f}% ({int(days_since or 0)} days since preventive work)."
        )
        passport = signal_evidence[:3] + [
            {
                "source_sheet": "Usage_Log",
                "field": "StartStopEvents, DutyCyclePct, CyclesRun",
                "label": "operating stress",
                "latest_value": round(_number(latest.get("DutyCyclePct")), 1),
                "unit": "% duty cycle",
                "evidence_score": round(usage_score, 1),
                "message": (
                    f"Duty cycle {_number(latest.get('DutyCyclePct')):.0f}%, "
                    f"{_number(latest.get('StartStopEvents')):.0f} starts/stops and "
                    f"{_number(latest.get('CyclesRun')):.0f} cycles in the latest week."
                ),
            },
            {
                "source_sheet": "Maintenance_History + Asset_Master",
                "field": "Date, MaintType, MaintIntervalDays",
                "label": "maintenance exposure",
                "latest_value": None if overdue_ratio is None else round(overdue_ratio * 100, 1),
                "unit": "% of interval",
                "evidence_score": round(maintenance_score, 1),
                "message": maintenance_message,
            },
            {
                "source_sheet": "Quality_Linkage",
                "field": "DefectCount, ScrapRate_pct, ReworkCount",
                "label": "quality impact",
                "latest_value": round(_number(latest.get("ScrapRate_pct")), 2),
                "unit": "% scrap",
                "evidence_score": round(quality_score, 1),
                "message": (
                    f"Latest quality record: {_number(latest.get('DefectCount')):.0f} defects, "
                    f"{_number(latest.get('ScrapRate_pct')):.2f}% scrap and "
                    f"{_number(latest.get('ReworkCount')):.0f} rework events."
                ),
            },
            {
                "source_sheet": "Production_Context",
                "field": "DemandIndex, OvertimeHours",
                "label": "production consequence",
                "latest_value": round(_number(latest.get("DemandIndex")), 2),
                "unit": "demand index",
                "evidence_score": round(production_score, 1),
                "message": (
                    f"Line demand index is {_number(latest.get('DemandIndex')):.2f} with "
                    f"{_number(latest.get('OvertimeHours')):.0f} overtime hours across shifts."
                ),
            },
            {
                "source_sheet": "Model output",
                "field": "auxiliary degradation detector",
                "label": SEMANTIC_LABEL,
                "latest_value": round(model_score, 1),
                "unit": "/100",
                "evidence_score": round(model_score, 1),
                "model_family": model_family,
                "local_drivers": model_drivers[position],
                "message": (
                    f"Auxiliary degradation likeness is {model_score:.1f}/100. "
                    "It is advisory-only, does not set RAG, and is not a calibrated failure probability."
                ),
            },
        ]
        for evidence_item in passport:
            evidence_item.setdefault("signal", evidence_item.get("label", evidence_item.get("field")))
            evidence_item.setdefault("value", evidence_item.get("latest_value"))

        component_scores = {
            "condition": round(condition_score, 1),
            "maintenance": round(maintenance_score, 1),
            "lifecycle": round(lifecycle_score, 1),
            "usage": round(usage_score, 1),
            "quality": round(quality_score, 1),
            "maintenance_history": round(history_score, 1),
            "production_context": round(production_score, 1),
            "auxiliary_model": round(model_score, 1),
        }
        assessments.append(
            {
                "asset_id": asset_id,
                "asset_name": str(latest["AssetName"]),
                "name": str(latest["AssetName"]),
                "asset_type": str(latest["AssetType"]),
                "type": str(latest["AssetType"]),
                "class": str(latest["Class"]),
                "line": str(latest["Line"]),
                "station": str(latest["Station"]),
                "manufacturer": str(latest["Manufacturer"]),
                "status": status,
                "status_colour": STATUS_COLOURS[status],
                "status_label": status_label,
                "days_remaining": estimated_days,
                "planning_horizon_days": estimated_days,
                "planning_window": planning_window,
                "degradation_likelihood": round(model_score, 1),
                "model_used_in_rag": False,
                "technical_risk": round(technical_risk, 1),
                "attention_priority": round(attention_priority, 1),
                "business_impact": round(impact, 1),
                "data_confidence": round(confidence, 1),
                "confidence_pct": round(confidence, 1),
                "failure_mode": failure_mode,
                "recommended_action": action,
                "recommendation_options": recommendation_options,
                "reason_summary": why,
                "classification_reason": classification_reason,
                "tooltip": tooltip,
                "component_scores": component_scores,
                "evidence_passport": passport,
                "evidence": passport,
                "data_quality_flags": data_quality_flags,
                "ambiguous_case": is_ambiguous,
                "is_ambiguous": is_ambiguous,
                "ambiguity_reason": ambiguity_reason,
                "human_approval": "PENDING",
                "human_gate": {
                    "required": True,
                    "owner": "Equipment Owner",
                    "allowed_decisions": ["APPROVE", "MODIFY", "REJECT"],
                    "automatic_equipment_action": False,
                },
                "equipment_action_taken": False,
                "equipment_write_capability": False,
                "source_week": pd.Timestamp(latest["WeekStarting"]).date().isoformat(),
            }
        )

    assessments.sort(key=lambda item: item["attention_priority"], reverse=True)
    return assessments


def get_asset_assessment(assessments: list[dict[str, Any]], asset_id: str) -> dict[str, Any]:
    for assessment in assessments:
        if assessment["asset_id"] == asset_id:
            return assessment
    raise KeyError(asset_id)
