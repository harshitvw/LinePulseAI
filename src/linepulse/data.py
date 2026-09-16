"""Official GuardianLine workbook ingestion and data-quality checks.

Only the six operational worksheets are read.  In particular, this module does
not read the hidden ``ANSWER_KEY`` worksheet.  Columns intended as authoring
hints (``ScenarioFlag`` and ``LinkedFailureMode``) are retained only long enough
to construct the declared training target or for audit; they never enter the
model feature matrix or the risk formula.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET_PATH = PROJECT_ROOT / "data" / "source" / "Synthetic_Dataset.xlsx"

OPERATIONAL_SHEETS = (
    "Asset_Master",
    "Usage_Log",
    "Sensor_Readings",
    "Maintenance_History",
    "Production_Context",
    "Quality_Linkage",
)

REQUIRED_COLUMNS: dict[str, set[str]] = {
    "Asset_Master": {
        "AssetID",
        "AssetName",
        "AssetType",
        "Class",
        "Line",
        "Station",
        "Manufacturer",
        "InstallDate",
        "RatedCycleLife",
        "CumulativeCycles",
        "BusinessImpactScore",
        "ReplacementCost_EUR",
        "ReplacementLeadDays",
        "MaintIntervalDays",
    },
    "Usage_Log": {
        "UsageID",
        "AssetID",
        "WeekStarting",
        "CyclesRun",
        "StartStopEvents",
        "PeakThroughput_UPH",
        "DutyCyclePct",
        "CumulativeCyclesEOW",
    },
    "Sensor_Readings": {
        "ReadingID",
        "AssetID",
        "WeekStarting",
        "AvgTempC",
        "MaxTempC",
        "AvgVibration_mm_s",
        "MaxVibration_mm_s",
        "AvgCurrent_A",
        "MaxCurrent_A",
        "AvgPressure_bar",
        "CycleTime_s",
    },
    "Maintenance_History": {
        "WorkOrderID",
        "AssetID",
        "Date",
        "MaintType",
        "FailureMode",
        "DowntimeHours",
        "PartsReplaced",
        "TechNotes",
    },
    "Production_Context": {
        "ContextID",
        "Line",
        "WeekStarting",
        "Shift",
        "ModelMix",
        "PlannedVolume",
        "ActualVolume",
        "OvertimeHours",
        "DemandIndex",
    },
    "Quality_Linkage": {
        "QualityID",
        "AssetID",
        "WeekStarting",
        "DefectCount",
        "DefectType",
        "ScrapRate_pct",
        "ReworkCount",
    },
}

# Purely numeric, generalizable predictors.  Record identifiers, asset IDs,
# human-readable labels and facilitator hints are deliberately absent.
MODEL_FEATURES = (
    "AvgTempC",
    "MaxTempC",
    "AvgVibration_mm_s",
    "MaxVibration_mm_s",
    "AvgCurrent_A",
    "MaxCurrent_A",
    "AvgPressure_bar",
    "CycleTime_s",
    "CyclesRun",
    "StartStopEvents",
    "PeakThroughput_UPH",
    "DutyCyclePct",
    "LifecycleUsedPct",
    "DaysSincePreventive",
    "MaintenanceOverdueRatio",
    "CorrectiveWorkOrders90d",
    "MaintenanceDowntime90d",
    "DefectCount",
    "ScrapRate_pct",
    "ReworkCount",
    "PlannedVolume",
    "ActualVolume",
    "OvertimeHours",
    "DemandIndex",
)


@dataclass(slots=True)
class DataBundle:
    """Prepared official dataset plus an explicit audit trail."""

    source_path: Path
    assets: pd.DataFrame
    usage: pd.DataFrame
    sensors: pd.DataFrame
    maintenance: pd.DataFrame
    production: pd.DataFrame
    quality: pd.DataFrame
    weekly: pd.DataFrame
    analysis_date: pd.Timestamp
    data_quality: dict[str, Any]

    @property
    def asset_count(self) -> int:
        return int(self.assets["AssetID"].nunique())

    @property
    def source_sha256(self) -> str:
        """Fingerprint the exact organizer workbook used for this bundle."""

        return hashlib.sha256(self.source_path.read_bytes()).hexdigest()

    @property
    def model_features(self) -> list[str]:
        return list(MODEL_FEATURES)

    def model_matrix(self) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
        """Return X, binary degradation target and grouping key.

        ``ScenarioFlag`` is used *only* to create the binary target.  It is not
        included in ``X``.  Grouping on ``AssetID`` prevents weekly records from
        one asset appearing in both a training and validation fold.
        """

        missing = [column for column in MODEL_FEATURES if column not in self.weekly]
        if missing:
            raise ValueError(f"Prepared dataset is missing model features: {missing}")
        x = self.weekly.loc[:, MODEL_FEATURES].apply(pd.to_numeric, errors="coerce")
        y = self.weekly["DegradationTarget"].astype("int8")
        groups = self.weekly["AssetID"].astype(str)
        return x, y, groups


def _validate_schema(tables: dict[str, pd.DataFrame]) -> None:
    problems: list[str] = []
    for sheet, required in REQUIRED_COLUMNS.items():
        actual = set(tables[sheet].columns)
        absent = sorted(required - actual)
        if absent:
            problems.append(f"{sheet}: missing {', '.join(absent)}")
    if problems:
        raise ValueError("Workbook schema validation failed: " + "; ".join(problems))


def _parse_dates(tables: dict[str, pd.DataFrame]) -> None:
    for sheet, column in (
        ("Asset_Master", "InstallDate"),
        ("Usage_Log", "WeekStarting"),
        ("Sensor_Readings", "WeekStarting"),
        ("Maintenance_History", "Date"),
        ("Production_Context", "WeekStarting"),
        ("Quality_Linkage", "WeekStarting"),
    ):
        tables[sheet][column] = pd.to_datetime(tables[sheet][column], errors="coerce")
        if tables[sheet][column].isna().any():
            rows = tables[sheet].index[tables[sheet][column].isna()].tolist()
            raise ValueError(f"{sheet}.{column} contains invalid dates at rows {rows[:5]}")


def _maintenance_features_by_week(
    maintenance: pd.DataFrame,
    assets: pd.DataFrame,
    asset_weeks: pd.DataFrame,
) -> pd.DataFrame:
    valid = maintenance[maintenance["AssetID"].isin(assets["AssetID"])].copy()
    valid = valid.drop_duplicates(subset=["WorkOrderID"], keep="first")
    interval_by_asset = assets.set_index("AssetID")["MaintIntervalDays"]

    # Build each snapshot strictly from work orders dated on or before that
    # snapshot.  This prevents future maintenance from leaking into historical
    # model rows.
    rows: list[dict[str, Any]] = []
    for key in asset_weeks.drop_duplicates().itertuples(index=False):
        asset_id = str(key.AssetID)
        as_of = pd.Timestamp(key.WeekStarting)
        history = valid[(valid["AssetID"].astype(str) == asset_id) & (valid["Date"] <= as_of)]
        preventive = history[history["MaintType"].astype(str).str.casefold() == "preventive"]
        last_preventive = preventive["Date"].max() if not preventive.empty else pd.NaT
        recent = history[history["Date"] >= as_of - pd.Timedelta(days=90)]
        corrective = recent[recent["MaintType"].astype(str).str.casefold() == "corrective"]
        modes = history.dropna(subset=["FailureMode"]).sort_values("Date")
        interval = _numeric_or_nan(interval_by_asset.get(asset_id))
        days_since = (
            float((as_of - last_preventive).days) if pd.notna(last_preventive) else np.nan
        )
        rows.append(
            {
                "AssetID": asset_id,
                "WeekStarting": as_of,
                "LastPreventiveDate": last_preventive,
                "DaysSincePreventive": days_since,
                "MaintenanceOverdueRatio": days_since / interval if interval > 0 else np.nan,
                "CorrectiveWorkOrders90d": int(corrective["WorkOrderID"].nunique()),
                "MaintenanceDowntime90d": float(recent["DowntimeHours"].sum()),
                "LatestHistoricalFailureMode": (
                    modes["FailureMode"].iloc[-1] if not modes.empty else np.nan
                ),
            }
        )
    return pd.DataFrame(rows)


def _numeric_or_nan(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return numeric if np.isfinite(numeric) else float("nan")


def _production_weekly(production: pd.DataFrame) -> pd.DataFrame:
    # Production has three shifts per line/week.  Volumes and overtime are
    # additive; demand is averaged across shifts.
    return (
        production.groupby(["Line", "WeekStarting"], as_index=False)
        .agg(
            PlannedVolume=("PlannedVolume", "sum"),
            ActualVolume=("ActualVolume", "sum"),
            OvertimeHours=("OvertimeHours", "sum"),
            DemandIndex=("DemandIndex", "mean"),
        )
        .sort_values(["Line", "WeekStarting"])
    )


def _data_quality_audit(
    assets: pd.DataFrame,
    usage: pd.DataFrame,
    sensors: pd.DataFrame,
    maintenance: pd.DataFrame,
) -> dict[str, Any]:
    expected_keys = usage[["AssetID", "WeekStarting"]].drop_duplicates()
    sensor_keys = sensors[["AssetID", "WeekStarting"]].drop_duplicates()
    missing_sensor = expected_keys.merge(
        sensor_keys,
        on=["AssetID", "WeekStarting"],
        how="left",
        indicator=True,
    )
    missing_sensor = missing_sensor[missing_sensor["_merge"] == "left_only"].drop(columns="_merge")

    valid_asset_ids = set(assets["AssetID"].astype(str))
    orphan_ids = sorted(
        set(maintenance["AssetID"].astype(str)) - valid_asset_ids
    )
    duplicate_work_orders = sorted(
        maintenance.loc[
            maintenance["WorkOrderID"].duplicated(keep=False), "WorkOrderID"
        ]
        .astype(str)
        .unique()
        .tolist()
    )
    duplicate_usage_keys = int(
        usage.duplicated(subset=["AssetID", "WeekStarting"], keep=False).sum()
    )
    duplicate_sensor_keys = int(
        sensors.duplicated(subset=["AssetID", "WeekStarting"], keep=False).sum()
    )

    missing_records = [
        {
            "asset_id": str(row.AssetID),
            "week_starting": row.WeekStarting.date().isoformat(),
        }
        for row in missing_sensor.itertuples(index=False)
    ]
    return {
        "missing_sensor_asset_weeks": missing_records,
        "missing_sensor_row_count": len(missing_records),
        "orphan_maintenance_asset_ids": orphan_ids,
        "duplicate_work_order_ids": duplicate_work_orders,
        "duplicate_usage_key_rows": duplicate_usage_keys,
        "duplicate_sensor_key_rows": duplicate_sensor_keys,
        "source_is_synthetic": True,
        "worksheets_read": list(OPERATIONAL_SHEETS),
        "worksheets_explicitly_not_read": ["README", "ANSWER_KEY"],
        "hint_columns_excluded_from_features": ["ScenarioFlag", "LinkedFailureMode"],
    }


def load_official_data(path: str | Path | None = None) -> DataBundle:
    """Load and prepare the official synthetic hackathon workbook.

    The loader addresses sheets and joins by schema.  It therefore remains
    robust when record identifiers are replaced or new asset scenarios are
    appended, provided the documented columns remain available.
    """

    source_path = Path(path) if path is not None else DEFAULT_DATASET_PATH
    source_path = source_path.expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(
            f"Official dataset not found at {source_path}. "
            "Place it at data/source/Synthetic_Dataset.xlsx or pass an explicit path."
        )

    # The explicit sheet list is a safety boundary: hidden sheets are not loaded.
    tables = pd.read_excel(source_path, sheet_name=list(OPERATIONAL_SHEETS))
    _validate_schema(tables)
    _parse_dates(tables)

    assets = tables["Asset_Master"].copy()
    assets = assets[assets["Class"].astype(str).str.upper() == "A"].copy()
    if assets.empty:
        raise ValueError("The workbook contains no Class A assets")
    if assets["AssetID"].duplicated().any():
        raise ValueError("Asset_Master.AssetID must be unique")

    usage = tables["Usage_Log"].copy()
    sensors = tables["Sensor_Readings"].copy()
    maintenance = tables["Maintenance_History"].copy()
    production = tables["Production_Context"].copy()
    quality = tables["Quality_Linkage"].copy()

    analysis_date = pd.Timestamp(usage["WeekStarting"].max()) + pd.Timedelta(days=6)
    quality_audit = _data_quality_audit(assets, usage, sensors, maintenance)

    production_weekly = _production_weekly(production)
    maintenance_by_week = _maintenance_features_by_week(
        maintenance,
        assets,
        usage[["AssetID", "WeekStarting"]],
    )

    # Usage is the expected asset-week spine.  A left join intentionally retains
    # missing sensor weeks so confidence can fall rather than the record silently
    # disappearing.
    sensor_input = sensors.copy()
    if "ScenarioFlag" in sensor_input:
        sensor_input["DegradationTarget"] = sensor_input["ScenarioFlag"].notna().astype("int8")
        sensor_input = sensor_input.drop(columns=["ScenarioFlag"])
    else:
        # ScenarioFlag is explicitly a removable participant hint.  Portfolio
        # analytics must remain functional when judges remove it.
        sensor_input["DegradationTarget"] = 0
    quality_input = quality.drop(columns=["LinkedFailureMode"], errors="ignore")

    weekly = usage.merge(
        sensor_input,
        on=["AssetID", "WeekStarting"],
        how="left",
        validate="one_to_one",
    )
    weekly = weekly.merge(
        quality_input,
        on=["AssetID", "WeekStarting"],
        how="left",
        validate="one_to_one",
    )
    weekly = weekly.merge(assets, on="AssetID", how="inner", validate="many_to_one")
    weekly = weekly.merge(
        production_weekly,
        on=["Line", "WeekStarting"],
        how="left",
        validate="many_to_one",
    )
    weekly = weekly.merge(
        maintenance_by_week,
        on=["AssetID", "WeekStarting"],
        how="left",
        validate="one_to_one",
    )
    weekly["DegradationTarget"] = weekly["DegradationTarget"].fillna(0).astype("int8")
    rated_life = pd.to_numeric(weekly["RatedCycleLife"], errors="coerce").replace(0, np.nan)
    weekly["LifecycleUsedPct"] = 100.0 * weekly["CumulativeCyclesEOW"] / rated_life
    weekly = weekly.sort_values(["AssetID", "WeekStarting"]).reset_index(drop=True)

    return DataBundle(
        source_path=source_path,
        assets=assets.reset_index(drop=True),
        usage=usage.reset_index(drop=True),
        sensors=sensors.reset_index(drop=True),
        maintenance=maintenance.reset_index(drop=True),
        production=production.reset_index(drop=True),
        quality=quality.reset_index(drop=True),
        weekly=weekly,
        analysis_date=analysis_date,
        data_quality=quality_audit,
    )
