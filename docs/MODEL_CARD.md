# Model Card — Auxiliary Seeded-Degradation Detector

## Summary

LinePulse AI contains a trained XGBoost binary classifier that estimates whether an observed asset-week resembles the synthetic degradation scenarios seeded by the organizer's data generator.

The classifier is **auxiliary and display-only**. It has 0% weight in technical risk, red/amber/green classification, and planning horizon. Those outputs come from current signals, recent trends, peer-derived warning boundaries, maintenance urgency, lifecycle, quality, and business context. The application remains usable if `ScenarioFlag` is not present in a judging workbook.

| Item | Description |
|---|---|
| Model family | Gradient-boosted decision trees (`XGBClassifier` when installed) |
| Unit of prediction | One asset-week with an observed sensor row |
| Target | Binary value derived from `ScenarioFlag.notna()` |
| Positive examples in supplied sensor sheet | 47 seeded scenario rows |
| Negative examples in supplied sensor sheet | 86 non-scenario rows |
| Training source | Organizer-provided synthetic workbook only |
| Validation | Whole-asset group holdout/group validation using `AssetID` |
| Random seed | `20260909` |
| Output | Seeded-degradation likelihood between 0 and 1 |
| Production validated | No |

The normal project installation includes XGBoost. If it is unavailable, runtime metadata names the selected compatible fallback rather than pretending XGBoost ran. If the hint target is absent or has only one class, a label-free robust peer-deviation fallback keeps the evidence engine operational.

## Intended use

- Provide a multivariate corroboration signal beside the transparent technical-risk assessment.
- Prioritize human review across the supplied Class A portfolio.
- Demonstrate a reproducible, leakage-aware tabular ML pipeline.
- Support, but not replace, signal-level explanation.

## Out-of-scope use

- Exact failure-date or remaining-useful-life prediction.
- Safety-limit enforcement.
- Autonomous shutdown, slowdown, or work-order creation.
- Direct use on a real plant without engineering review, new training data, calibration, monitoring, and validation.
- Treating the synthetic validation result as real-world performance.

## Target construction

The visible `Sensor_Readings.ScenarioFlag` identifies the five synthetic scenario families:

- `S1-Overheat`
- `S2-Vibration`
- `S3-Current`
- `S4-CycleTimeDrift`
- `S5-PressureDrop`

For the auxiliary binary detector:

- non-empty flag → `1` (seeded degradation)
- empty flag → `0` (not flagged by the generator)

`ScenarioFlag` is immediately removed from model inputs. It is a synthetic training hint, not a future physical-failure label and not a reliable judging-time dependency.

Rows with an intentionally missing sensor record are handled by the operational data-quality path, not mislabeled as negative model examples.

## Input policy

Allowed inputs include operational fields and derived features from:

- temperature, vibration, current, pressure, and cycle time;
- weekly cycles, duty cycle, starts/stops, and throughput;
- maintenance recency as of each `WeekStarting`, recent corrective-work-order count, downtime, and due-state features;
- lifecycle consumption;
- defect, scrap, and rework context; and
- aggregated planned/actual production volume, demand, and overtime.

Excluded inputs include:

- `ScenarioFlag` itself;
- the hidden `ANSWER_KEY`;
- workbook shading;
- `AssetID` as a predictive feature;
- `ReadingID`, `UsageID`, `QualityID`, `ContextID`, and `WorkOrderID`;
- names or substrings that reveal a seeded scenario;
- external, earlier, or real factory datasets; and
- human decisions that have not been verified as outcomes.

`AssetID` is retained outside the matrix only to form validation groups and join records.

## Training and validation design

The 133 observed sensor asset-weeks are joined with the other official operational sheets. Median imputation and XGBoost fitting occur inside a reproducible pipeline. Predictive inputs are numeric; asset type is used separately to form comparable peer baselines.

The validation split is grouped by `AssetID`: all weekly records for an asset belong to one side of a split. This prevents the common leakage error where week 1 of a machine is used for training and week 2 of the same machine is used for evaluation.

Training reports machine-readable metadata and classification metrics from the grouped validation. The current values should be read from the generated artifact/metadata or `scripts/train_model.py` output; they must always be presented as **synthetic group-validation metrics**, not production accuracy.

Why not a purely chronological split? There are only three weekly snapshots, so a single time split would be unusually small and unstable. Holding out complete assets is the most important generalization test for the organizer's likely ID/scenario swaps. A future field model should use both asset-grouped and forward-time validation.

## Role beside the final score

The likelihood is displayed as corroboration and is not a component of technical risk or RAG. The primary evidence engine evaluates:

- latest peer-relative signal level;
- recent unfavorable slope;
- estimated time to a peer warning boundary;
- maintenance-due state;
- rated-cycle-life consumption;
- usage stress;
- quality degradation;
- data completeness and confidence; and
- business impact for final attention ranking.

This means an asset can be prioritized because of a new transparent trend even when the auxiliary model likelihood is moderate, and a missing sensor record cannot become healthy because the model imputed a normal value.

The auxiliary likelihood has exactly 0% RAG weight. The current attention ranking uses 72% transparent technical risk, 20% official business impact, 5% replacement lead-time context, and 3% replacement-cost context. These are prototype planning weights, not learned safety policy.

## Explainability

Explainability is required for this problem because maintenance decisions are consequential and the guide asks for traceable alerts.

LinePulse AI uses three complementary levels:

1. **Model-level context:** permutation importance indicates which features matter across the fitted detector.
2. **Local model sensitivity:** one feature at a time is replaced with its training median; the change in likelihood is shown as directional context, not as a causal or exactly additive claim.
3. **Decision-level Evidence Passport:** each asset displays source field, value, unit, recent change, peer boundary, direction of concern, and contribution.

The Evidence Passport is the primary operational explanation. It is deterministic, directly connected to measurements, and understandable without trusting an opaque model score.

Likely failure mode is a hypothesis based on the dominant current sensor evidence. It is not a diagnosed root cause.

## Planning horizon

The model does not produce RUL. A separate transparent estimator calculates time to a project-derived peer warning boundary when an unfavorable slope exists:

`planning days = distance to warning boundary / unfavorable change per day`

Maintenance-due and lifecycle urgency may shorten the displayed horizon. The value is capped to keep extrapolation within a reasonable planning range.

Interpretation:

- `8 days` means “if the recent pattern continues, the selected monitoring boundary may be reached in about eight days.”
- It does **not** mean “the asset will physically fail in eight days.”

## Data quality and uncertainty

Known organizer-supplied conditions include two missing sensor asset-weeks, a duplicate work order, and an orphan maintenance record. The pipeline surfaces these separately from model risk.

Model preprocessing may impute missing numeric features so the API stays operational. Confidence is reduced and the affected evidence is shown. Imputation is never interpreted as evidence of health.

Uncertainty comes from:

- 100% synthetic data;
- only 133 sensor observations and 45 assets;
- three weekly time points;
- target defined by a generator hint rather than confirmed future failures;
- project-derived rather than OEM limits; and
- possible mismatch between seeded scenarios and new judge scenarios.

## Fairness and safety

Traditional demographic fairness is not applicable. Operational fairness still matters: one asset type or line should not be systematically over-prioritized because it naturally operates at a different scale. Peer/type baselines reduce this risk, while the dashboard keeps raw values and impact visible.

The system has no equipment write tools. The output must be reviewed by an Equipment Owner under existing maintenance and safety processes.

## Feedback and learning

The full loop is:

1. AI makes an assessment and recommendation.
2. Equipment Owner approves, modifies, or rejects it.
3. Maintenance occurs outside the application.
4. A human records and verifies the outcome.
5. Verified outcomes update auditable recommendation memory and become candidates for a later governed retraining set.

A decision is not automatically a correct label. The model artifact is not silently retrained after a single click. Original assessments remain immutable even when a verified outcome changes the current workflow display.

## Monitoring for a future production model

A production deployment should track:

- input-schema failures and sensor missingness;
- feature and prediction drift by asset type and line;
- calibration against confirmed future failures;
- alert precision, recall, and time-to-warning;
- false-alert burden and missed-event reviews;
- recommendation acceptance versus verified effectiveness;
- threshold overrides by maintenance experts; and
- model/data version attached to every assessment.

## Reproducibility

Train:

```powershell
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe scripts\train_model.py
```

Verify:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\smoke_test.py
```

The fixed seed, documented source workbook, saved pipeline, feature list, target definition, and grouped split metadata make the prototype reproducible. The artifact records a source/feature-contract fingerprint so a different workbook cannot silently reuse stale predictions. The generated artifact is `artifacts/degradation_model.joblib`.
