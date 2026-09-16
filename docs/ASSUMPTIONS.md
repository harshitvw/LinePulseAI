# Assumptions and Boundaries

This statement makes the prototype's claims reviewable. It should be available during the demo and included with the submission.

## Data assumptions

1. The only analytical source is the organizer-provided `Synthetic_Dataset.xlsx`. The participant guide and dataset report are requirements/reference documents, not training records.
2. The official Participant Guide, Dataset Report, and workbook override earlier mock scope or data. Only the LinePulse AI identity and human-control principle are carried forward from the team's concept.
3. The workbook is 100% synthetic, generated with fixed seed `20260909`. Results are therefore demonstration evidence, not production performance.
4. The 45 rows in `Asset_Master` are the intended Class A portfolio.
5. `AssetID` is the asset join key. `AssetID + WeekStarting` joins sensor, usage, and quality. `Line + WeekStarting` joins aggregated production context.
6. Three weekly snapshots are enough to illustrate a trend calculation, but not enough to validate long-term seasonality or physical degradation dynamics.
7. The known missing sensor weeks, duplicate work order, and orphan maintenance record are deliberate data-quality cases and should remain visible.
8. The hidden `ANSWER_KEY`, workbook shading, specific seeded asset IDs, and row IDs are not analytical inputs.
9. `ScenarioFlag` is a visible synthetic hint. It may be used only as the training target for an **auxiliary** XGBoost detector and is never an input feature. Core red/amber/green status, horizon, and explanations continue to work from signals, trends, peer context, maintenance, lifecycle, quality, and impact if the hint is absent.

## Model assumptions

1. XGBoost can learn useful nonlinear associations in the supplied tabular features, but the small three-week dataset limits statistical confidence.
2. Validation must hold out whole assets using `AssetID` groups. A random row split would leak the same asset across train and validation.
3. A high XGBoost output means similarity to the synthetic generator's seeded degradation cases. It is not a calibrated probability of physical failure.
4. Identifiers are excluded from features, so asset renaming or record-ID replacement should not change predictions when operational values remain the same.
5. The auxiliary model is display-only corroboration with 0% weight in technical risk, RAG status, and horizon. The transparent evidence engine is the judge-robust decision logic.
6. No accuracy metric from this synthetic workbook should be presented as expected production accuracy.

## Threshold and horizon assumptions

1. The workbook does not provide OEM operating or safety limits.
2. LinePulse AI therefore derives robust warning boundaries from comparable assets and labels them **project-derived peer warning boundaries**.
3. Higher temperature, vibration, current, cycle time, duty, start-stop activity, scrap, rework, and overdue maintenance are generally treated as unfavorable. Lower pressure is generally treated as unfavorable.
4. Recent unfavorable slopes are extrapolated only for planning. A trend is not assumed to continue indefinitely.
5. The displayed days mean estimated time to a peer warning boundary or an operational due point, not true remaining useful life and not a guaranteed failure date.
6. Red typically means a 0–10-day planning horizon, amber 11–30 days, and green more than 30 days. Risk, confidence, and data-quality conditions may make the state more conservative.
7. Green means no current near-term warning under the project logic. It does not guarantee that failure is impossible.

## Business assumptions

1. `BusinessImpactScore` is the organizer's comparative impact input and is not inferred by the model.
2. Technical risk and business impact are displayed separately before being combined into attention priority.
3. Replacement cost and lead time provide context; they do not automatically trigger a maintenance decision.
4. The target users are maintenance, production, and quality staff who need a concise queue plus drill-down evidence.

## Human and safety assumptions

1. LinePulse AI supports the Equipment Owner; it does not replace them.
2. The AI recommendation is followed by an explicit approve, modify, or reject gate.
3. Maintenance work happens outside the prototype, using the organization's approved safety and work-management processes.
4. A human verifies the outcome after maintenance. Only verified outcomes may affect feedback memory or later governed retraining.
5. Approval is not an outcome label. Clicking “approve” does not make the model correct and does not retrain it.
6. A resolved outcome may change the current workflow display to green, but the original assessment remains immutable and visible in history.
7. There is no PLC write, automatic shutdown, automatic work order, or equipment-control capability.

## Technical assumptions

1. The hackathon demo runs locally on Python 3.12.
2. The model artifact is trained before the demo and loaded by the service.
3. SQLite is sufficient for a single-team prototype audit trail. Production would need controlled identities, permissions, retention, and backups.
4. The core demo does not depend on network access, an LLM API key, EC2, Docker, or Ignition.

## Known limitations

- Synthetic rather than field data.
- Only three weekly snapshots.
- No confirmed future failure event, time-to-failure label, or censored survival history.
- No OEM limits or engineering envelopes.
- No intervention-cost optimization.
- No live historian or CMMS connector.
- No formal probability calibration or production drift monitoring.
- The feedback loop is a prototype recommendation-memory/governance pattern; substantial verified history is needed before outcome-based model retraining is defensible.

## Claims we can safely make

- The complete signal-to-decision workflow works for all 45 supplied assets.
- Every alert is traceable to operational fields and derived calculations.
- The auxiliary XGBoost model excludes its target and identifiers and is evaluated on unseen assets.
- The core ranking does not depend on seeded asset IDs, hidden answers, or the presence of `ScenarioFlag` at judging.
- The system distinguishes technical risk from business impact.
- Missing and malformed data are surfaced.
- The human remains responsible for the decision and verified outcome.

## Claims we must not make

- Production-validated failure prediction.
- Exact remaining useful life.
- Manufacturer-certified thresholds.
- Guaranteed failure prevention or downtime savings.
- Autonomous maintenance or shutdown control.
- Learning from real production outcomes.
