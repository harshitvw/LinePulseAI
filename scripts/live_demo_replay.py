r"""Run a reversible live sensor replay for the LinePulse AI demo.

The replay appends a new usage row and sensor row for five Class A assets at
each step. By default it works on the repository's original workbook after
creating a reversible backup. Use --demo-copy for a disposable workbook.

Examples (PowerShell):
    .\.venv\Scripts\python.exe scripts\live_demo_replay.py start --steps 6 --interval 5
    .\.venv\Scripts\python.exe scripts\live_demo_replay.py cleanup

This is a simulated live sensor replay, not a plant connector.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from openpyxl import load_workbook


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = PROJECT_ROOT / "data" / "source" / "Synthetic_Dataset.xlsx"
DEMO_PATH = PROJECT_ROOT / "data" / "source" / "Synthetic_Dataset.live-demo.xlsx"
BACKUP_PATH = PROJECT_ROOT / "data" / "source" / "Synthetic_Dataset.live-demo-backup.xlsx"
MANIFEST_PATH = PROJECT_ROOT / "runtime" / "live_demo_manifest.json"

SCENARIOS = (
    ("S1-Overheat", "AvgTempC", "MaxTempC", 3.0, 5.0),
    ("S2-Vibration", "AvgVibration_mm_s", "MaxVibration_mm_s", 0.8, 1.2),
    ("S3-Current", "AvgCurrent_A", "MaxCurrent_A", 8.0, 12.0),
    ("S4-CycleTimeDrift", "CycleTime_s", None, 1.5, 0.0),
    ("S5-PressureDrop", "AvgPressure_bar", None, -0.35, 0.0),
)


def _headers(ws: Any) -> list[str]:
    return [str(cell.value) for cell in ws[1]]


def _records(ws: Any) -> list[dict[str, Any]]:
    headers = _headers(ws)
    return [dict(zip(headers, row)) for row in ws.iter_rows(min_row=2, values_only=True)]


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)).date()


def _next_id(records: list[dict[str, Any]], field: str, fallback: int) -> int:
    values = []
    for row in records:
        try:
            values.append(int(row.get(field)))
        except (TypeError, ValueError):
            continue
    return max(values, default=fallback) + 1


def _copy_row(row: dict[str, Any], headers: list[str]) -> list[Any]:
    return [row.get(header) for header in headers]


def _asset_base(records: list[dict[str, Any]], asset_id: str) -> dict[str, Any]:
    matches = [row for row in records if str(row.get("AssetID")) == asset_id]
    if not matches:
        raise ValueError(f"No source record found for Class A asset {asset_id}")
    return max(matches, key=lambda row: _as_date(row["WeekStarting"]))


def _class_a_assets(records: list[dict[str, Any]]) -> list[str]:
    assets = [
        str(row["AssetID"])
        for row in records
        if str(row.get("Class", "")).upper() == "A"
    ]
    if len(assets) < len(SCENARIOS):
        raise ValueError("The workbook must contain at least five Class A assets")
    return assets[: len(SCENARIOS)]


def _prepare_demo_copy(source: Path, demo: Path, force: bool) -> None:
    if demo.exists():
        if not force:
            raise FileExistsError(
                f"{demo.name} already exists. Run cleanup first or use --force."
            )
        demo.unlink()
    demo.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, demo)


def _append_step(workbook_path: Path, step: int) -> dict[str, Any]:
    workbook = load_workbook(workbook_path)
    assets_ws = workbook["Asset_Master"]
    usage_ws = workbook["Usage_Log"]
    sensors_ws = workbook["Sensor_Readings"]

    assets = _records(assets_ws)
    usage = _records(usage_ws)
    sensors = _records(sensors_ws)
    asset_ids = _class_a_assets(assets)
    usage_headers = _headers(usage_ws)
    sensor_headers = _headers(sensors_ws)
    source_week = max(_as_date(row["WeekStarting"]) for row in usage)
    week = source_week + timedelta(days=7 * step)
    usage_id = _next_id(usage, "UsageID", 0)
    reading_id = _next_id(sensors, "ReadingID", 0)

    appended = []
    for asset_id, scenario in zip(asset_ids, SCENARIOS):
        label, primary, secondary, delta, secondary_delta = scenario
        usage_base = _asset_base(usage, asset_id)
        sensor_base = _asset_base(sensors, asset_id)

        usage_row = dict(usage_base)
        usage_row["UsageID"] = usage_id
        usage_row["WeekStarting"] = week
        usage_row["AssetID"] = asset_id
        if "CumulativeCyclesEOW" in usage_row:
            try:
                usage_row["CumulativeCyclesEOW"] = float(usage_base["CumulativeCyclesEOW"]) + 2500 * step
            except (TypeError, ValueError):
                pass
        usage_ws.append(_copy_row(usage_row, usage_headers))
        usage_id += 1

        sensor_row = dict(sensor_base)
        sensor_row["ReadingID"] = reading_id
        sensor_row["WeekStarting"] = week
        sensor_row["AssetID"] = asset_id
        sensor_row["ScenarioFlag"] = None
        for field, amount in ((primary, delta), (secondary, secondary_delta)):
            if not field or field not in sensor_row:
                continue
            try:
                sensor_row[field] = float(sensor_base[field]) + amount * step
            except (TypeError, ValueError):
                raise ValueError(f"Sensor field {field} is not numeric for {asset_id}")
        sensors_ws.append(_copy_row(sensor_row, sensor_headers))
        reading_id += 1
        appended.append({"asset_id": asset_id, "scenario": label, "week": week.isoformat()})

    workbook.save(workbook_path)
    return {"step": step, "week": week.isoformat(), "rows": appended}


def start(args: argparse.Namespace) -> None:
    if not SOURCE_PATH.exists():
        raise FileNotFoundError(f"Source workbook not found: {SOURCE_PATH}")
    target = SOURCE_PATH if args.in_place else DEMO_PATH
    if args.in_place:
        if BACKUP_PATH.exists() and not args.force:
            raise FileExistsError(
                f"{BACKUP_PATH.name} already exists. Run cleanup first or use --force."
            )
        shutil.copy2(SOURCE_PATH, BACKUP_PATH)
    else:
        _prepare_demo_copy(SOURCE_PATH, target, args.force)

    manifest = {
        "source": str(SOURCE_PATH),
        "target": str(target),
        "in_place": bool(args.in_place),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "steps": [],
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    for step in range(1, args.steps + 1):
        result = _append_step(target, step)
        manifest["steps"].append(result)
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"Step {step}/{args.steps}: {result['week']} | {target.name}", flush=True)
        if step < args.steps:
            time.sleep(args.interval)
    print(f"Live replay complete. Dashboard data path: {target}")
    print("Run cleanup after the demo to remove the replay workbook or restore in-place data.")


def cleanup() -> None:
    if not MANIFEST_PATH.exists():
        print("No live-demo manifest found; nothing to clean up.")
        return
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    target = Path(manifest["target"])
    if manifest.get("in_place"):
        if not BACKUP_PATH.exists():
            raise FileNotFoundError(f"Cannot restore; backup not found: {BACKUP_PATH}")
        shutil.copy2(BACKUP_PATH, target)
        BACKUP_PATH.unlink()
        print(f"Restored original workbook: {target}")
    elif target.exists():
        target.unlink()
        print(f"Removed demo workbook: {target}")
    MANIFEST_PATH.unlink()
    print("Cleanup complete. The original workbook was left unchanged.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    start_parser = subparsers.add_parser("start", help="create and populate a live replay workbook")
    start_parser.add_argument("--steps", type=int, default=6, help="number of weekly replay steps")
    start_parser.add_argument("--interval", type=float, default=5.0, help="seconds between steps")
    start_parser.add_argument("--force", action="store_true", help="replace an existing demo workbook")
    mode = start_parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--in-place",
        dest="in_place",
        action="store_true",
        default=True,
        help="use the original workbook (default; backup is created first)",
    )
    mode.add_argument(
        "--demo-copy",
        dest="in_place",
        action="store_false",
        help="use a disposable workbook copy instead",
    )
    start_parser.set_defaults(func=start)
    cleanup_parser = subparsers.add_parser("cleanup", help="remove the disposable replay workbook")
    cleanup_parser.set_defaults(func=lambda _args: cleanup())
    args = parser.parse_args()
    if args.command == "start" and args.steps < 1:
        parser.error("--steps must be at least 1")
    try:
        args.func(args)
    except Exception as exc:
        print(f"live_demo_replay: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
