# Data Dictionary

This dictionary covers the organizer-provided workbook and the principal derived concepts used by LinePulse AI. The workbook is 100% synthetic.

## Join map

| From | To | Join |
|---|---|---|
| `Asset_Master` | `Usage_Log` | `AssetID` |
| `Asset_Master` | `Sensor_Readings` | `AssetID` |
| `Asset_Master` | `Maintenance_History` | `AssetID` |
| `Asset_Master` | `Quality_Linkage` | `AssetID` |
| `Asset_Master` → line | `Production_Context` | `Line + WeekStarting` after shift aggregation |
| Weekly sources | Each other | `AssetID + WeekStarting` where applicable |

`AssetID` and record IDs are used to join and audit only. They are excluded from predictive inputs.

## `Asset_Master`

Grain: one row per Class A asset. Supplied rows: 45.

| Column | Type | Meaning | Analytical use |
|---|---|---|---|
| `AssetID` | text | Synthetic asset key | Join/group key only; never a feature |
| `AssetName` | text | Human-readable asset name | Display only |
| `AssetType` | text | Equipment category | Peer baselines and model category |
| `Class` | text | Criticality class | Portfolio filter/contract; expected `A` |
| `Line` | text | Assembly-line identifier | Production join and display context |
| `Station` | text | Station identifier/name | Display context |
| `Manufacturer` | text | Fictitious manufacturer | Display context; not an approved source of limits |
| `InstallDate` | date text | Synthetic installation date | Asset age context |
| `RatedCycleLife` | integer cycles | Nominal rated cycle life | Lifecycle consumption calculation |
| `CumulativeCycles` | integer cycles | Master snapshot of accumulated cycles | Sanity check/base lifecycle context |
| `BusinessImpactScore` | integer | Organizer-supplied impact score | Business-impact layer, shown separately from risk |
| `ReplacementCost_EUR` | integer EUR | Synthetic replacement cost | Decision context |
| `ReplacementLeadDays` | integer days | Synthetic replacement lead time | Planning context |
| `MaintIntervalDays` | integer days | Nominal preventive-maintenance interval | Maintenance due/overdue calculation |

## `Usage_Log`

Grain: one row per asset-week. Supplied rows: 135 (45 assets × 3 weeks).

| Column | Type/unit | Meaning | Analytical use |
|---|---|---|---|
| `UsageID` | integer | Synthetic record ID | Audit only; never a feature |
| `AssetID` | text | Asset key | Join/group key only |
| `WeekStarting` | date | Start of weekly observation | Time join and trend order |
| `CyclesRun` | cycles/week | Cycles completed during week | Weekly workload and lifecycle rate |
| `StartStopEvents` | count/week | Start/stop events | Mechanical/electrical stress proxy |
| `PeakThroughput_UPH` | units/hour | Weekly peak throughput | Operating-intensity context |
| `DutyCyclePct` | percent | Share of time under operation | Operating-intensity context |
| `CumulativeCyclesEOW` | cycles | Accumulated cycles at week end | Latest lifecycle consumption and trend |

## `Sensor_Readings`

Grain: one row per observed asset-week. Supplied rows: 133. Two of the expected 135 asset-weeks are intentionally missing.

| Column | Type/unit | Meaning | Direction generally treated as unfavorable |
|---|---|---|---|
| `ReadingID` | integer | Synthetic reading ID | Not a feature |
| `AssetID` | text | Asset key | Join/group key only |
| `WeekStarting` | date | Start of weekly observation | Time join and trend order |
| `AvgTempC` | °C | Weekly average temperature | Higher |
| `MaxTempC` | °C | Weekly maximum temperature | Higher |
| `AvgVibration_mm_s` | mm/s | Weekly average vibration velocity | Higher |
| `MaxVibration_mm_s` | mm/s | Weekly maximum vibration velocity | Higher |
| `AvgCurrent_A` | A | Weekly average electrical current | Higher |
| `MaxCurrent_A` | A | Weekly maximum electrical current | Higher |
| `AvgPressure_bar` | bar | Weekly average pressure | Lower, for pressure-loss detection |
| `CycleTime_s` | seconds | Weekly cycle time | Higher/slower |
| `ScenarioFlag` | text/blank | Synthetic seeded-scenario hint | Target only for auxiliary training; excluded from inputs and core RAG logic |

The five non-empty `ScenarioFlag` families are `S1-Overheat`, `S2-Vibration`, `S3-Current`, `S4-CycleTimeDrift`, and `S5-PressureDrop`. The auxiliary model collapses them to flagged/not flagged. The evidence engine still identifies the dominant signal type independently.

## `Maintenance_History`

Grain: one maintenance event/work order. Supplied rows: 103.

| Column | Type/unit | Meaning | Analytical use |
|---|---|---|---|
| `WorkOrderID` | text | Synthetic work-order key | Duplicate-quality check; never a feature value |
| `AssetID` | text | Asset key | Join; orphan-key check |
| `Date` | date | Work date | Recency and due-state calculation |
| `MaintType` | category | Preventive, corrective, or inspection | Maintenance-pattern features |
| `FailureMode` | category/blank | Historical recorded mode | Retained as history; not used to assign the current sensor-driven hypothesis |
| `DowntimeHours` | hours | Event downtime | History burden/context |
| `PartsReplaced` | text/blank | Recorded replaced part(s) | Retained in the source; not scored or surfaced in the current prototype |
| `TechNotes` | text/blank | Synthetic technician note | Retained in the source; not scored or surfaced in the current prototype |

Known condition: one orphan `AssetID` and one duplicate `WorkOrderID` are intentionally present.

## `Production_Context`

Raw grain: one line-week-shift row. Supplied rows: 45. The application aggregates shifts before joining to assets.

| Column | Type/unit | Meaning | Aggregation/use |
|---|---|---|---|
| `ContextID` | text | Synthetic context-record ID | Audit only; never a feature |
| `Line` | text | Production line | Join key with asset master |
| `WeekStarting` | date | Start of production week | Join key |
| `Shift` | category | Shift | Grouping only |
| `ModelMix` | category/text | Synthetic product-mix context | Encoded/summary context where used |
| `PlannedVolume` | units | Planned shift volume | Sum by line-week |
| `ActualVolume` | units | Actual shift volume | Sum by line-week and use as context |
| `OvertimeHours` | hours | Shift overtime | Sum by line-week |
| `DemandIndex` | ratio/index | Relative demand intensity | Mean/max context by line-week |

## `Quality_Linkage`

Grain: one row per asset-week. Supplied rows: 135.

| Column | Type/unit | Meaning | Analytical use |
|---|---|---|---|
| `QualityID` | text | Synthetic quality-record ID | Audit only; never a feature |
| `AssetID` | text | Asset key | Join/group key only |
| `WeekStarting` | date | Start of quality week | Time join and trend order |
| `DefectCount` | count | Weekly defects linked to asset context | Level and trend evidence |
| `DefectType` | text/category | Synthetic defect type | Display/category context |
| `ScrapRate_pct` | percent | Weekly scrap rate | Level and trend evidence |
| `ReworkCount` | count | Weekly rework events | Level and trend evidence |
| `LinkedFailureMode` | text/blank | Synthetic historical linkage | Explicitly excluded from current model and risk logic |

## Facilitator/reference sheets

| Sheet | Application policy |
|---|---|
| `README` | May be read by a person; not a model input |
| `ANSWER_KEY` | Never read by application code, training, tests, or scoring |

Workbook cell shading and seeded asset IDs are also excluded.

## Derived analytical concepts

Exact field names in the API may be snake_case or presentation case, but these definitions remain stable.

| Concept | Range/unit | Definition |
|---|---:|---|
| Seeded-degradation likelihood | 0–100 | Auxiliary XGBoost output indicating similarity to a seeded scenario; not calibrated field-failure probability |
| Signal level percentile | 0–100 | Relative position versus comparable peer/type observations, oriented so larger means more concerning |
| Signal trend | units/day or period change | Recent least-squares direction across available weekly observations |
| Peer warning boundary | signal unit | Robust data-derived monitoring boundary; not an OEM limit |
| Days to boundary | days | Linear trend extrapolation to the peer warning boundary, capped for planning |
| Maintenance horizon | days | Time until scheduled interval is reached; zero if already due/overdue |
| Lifecycle consumption | percent | Latest cumulative cycles divided by rated cycle life |
| Technical risk | 0–100 | Transparent fusion of condition, trend, usage, maintenance, lifecycle, quality, maintenance history, and production context; auxiliary model weight is 0% |
| Business impact | 0–100 display scale | Normalized official `BusinessImpactScore` and context used for ranking |
| Attention priority | 0–100 | Explicit combination of technical risk and business impact |
| Confidence | 0–100 | Evidence completeness and quality, not model likelihood |
| Planning horizon | days | Earliest credible trend/maintenance/lifecycle attention horizon; not true RUL |
| Failure-mode hypothesis | text | Dominant sensor-evidence family translated into a likely mechanism for inspection |
| Recommended action | text | Guardrailed human-review suggestion |
| RAG state | Red/Amber/Green | Operational attention state supported by horizon, risk, and confidence |
| Workflow state | Open/Resolved/Partial/etc. | Human decision/outcome state kept separate from original model assessment |

## RAG interpretation

| Color | Typical planning horizon | Meaning |
|---|---:|---|
| Red | 0–10 days | Immediate Equipment Owner review |
| Amber | 11–30 days | Plan inspection or intervention |
| Green | >30 days | Continue monitoring |

The actual tooltip on each card explains which condition produced that asset's state. Data-quality concerns may force a conservative status even when a numerical horizon is unavailable.

## Runtime decision/audit data

The SQLite database is application-generated and is not an external training dataset.

Typical audit concepts include:

| Field | Meaning |
|---|---|
| Case/decision ID | Local immutable audit key |
| Asset ID | Asset reviewed by the human |
| Original assessment | Model/risk version, score, RAG, evidence, and recommendation at decision time |
| Decision | Approve, modify, or reject |
| Human rationale | Optional explanation entered by Equipment Owner |
| Modified action/window | Human-adjusted plan when relevant |
| Decision time | Recorded timestamp |
| Outcome | Resolved, partially resolved, unresolved, or monitoring |
| Outcome notes | Human-verified maintenance/result details |
| Outcome time | Verification timestamp |

No decision/audit field is sent to equipment. The original assessment is retained even if a verified outcome changes the current workflow state.
