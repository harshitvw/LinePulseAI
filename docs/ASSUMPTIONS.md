Assumptions and Boundaries

This statement makes the prototype's claims reviewable. It should be available during the demo and included with the submission.

Data assumptions

The only analytical source is the organizer-provided Synthetic_Dataset.xlsx. The participant guide and dataset report are requirements/reference documents, not training records.

The official Participant Guide, Dataset Report, and workbook override earlier mock scope or data. Only the LinePulse AI identity and human-control principle are carried forward from the team's concept.

The workbook is 100% synthetic, generated with fixed seed 20260909. Results are therefore demonstration evidence, not production performance.

The 45 rows in Asset_Master are the intended Class A portfolio.

AssetID is the asset join key. AssetID + WeekStarting joins sensor, usage, and quality. Line + WeekStarting joins aggregated production context.

Three weekly snapshots are enough to illustrate a trend calculation, but not enough to validate long-term seasonality or physical degradation dynamics.

The known missing sensor weeks, duplicate work order, and orphan maintenance record are deliberate data-quality cases and should remain visible.

The hidden ANSWER_KEY, workbook shading, specific seeded asset IDs, and row IDs are not analytical inputs.

ScenarioFlag is a visible synthetic hint. It may be used only as the training target for an auxiliary XGBoost detector and is never an input feature. Core red/amber/green status, horizon, and explanations continue to work from signals, trends, peer context, maintenance, lifecycle, quality, and impact if the hint is absent.

Model assumptions

XGBoost can learn useful nonlinear associations in the supplied tabular features, but the small three-week dataset limits statistical confidence.

Validation must hold out whole assets using AssetID groups. A random row split would leak the same asset across train and validation.

A high XGBoost output means similarity to the synthetic generator's seeded degradation cases. It is not a calibrated probability of physical failure.

Identifiers are excluded from features, so asset renaming or record-ID replacement should not change predictions when operational values remain the same.

The auxiliary model is display-only corroboration with 0% weight in technical risk, RAG status, and horizon. The transparent evidence engine is the judge-robust decision logic.

No accuracy metric from this synthetic workbook should be presented as expected production accuracy.

Threshold and horizon assumptions

The workbook does not provide OEM operating or safety limits.

LinePulse AI therefore derives robust warning boundaries from comparable assets and labels them project-derived peer warning boundaries.

Higher temperature, vibration, current, cycle time, duty, start-stop activity, scrap, rework, and overdue maintenance are generally treated as unfavorable. Lower pressure is generally treated as unfavorable.

Recent unfavorable slopes are extrapolated only for planning. A trend is not assumed to continue indefinitely.

The displayed days mean estimated time to a peer warning boundary or an operational due point, not true remaining useful life and not a guaranteed failure date.

Red typically means a 0–10-day planning horizon, amber 11–30 days, and green more than 30 days. Risk, confidence, and data-quality conditions may make the state more conservative.

Green means no current near-term warning under the project logic. It does not guarantee that failure is impossible.

Business assumptions

BusinessImpactScore is the organizer's comparative impact input and is not inferred by the model.

Technical risk and business impact are displayed separately before being combined into attention priority.

Replacement cost and lead time provide context; they do not automatically trigger a maintenance decision.

The target users are maintenance, production, and quality staff who need a concise queue plus drill-down evidence.

Human and safety assumptions

LinePulse AI supports the Equipment Owner; it does not replace them.

The AI recommendation is followed by an explicit approve, modify, or reject gate.

Maintenance work happens outside the prototype, using the organization's approved safety and work-management processes.

A human verifies the outcome after maintenance. Only verified outcomes may affect feedback memory or later governed retraining.

Approval is not an outcome label. Clicking “approve” does not make the model correct and does not retrain it.

A resolved outcome may change the current workflow display to green, but the original assessment remains immutable and visible in history.

There is no PLC write, automatic shutdown, automatic work order, or equipment-control capability.

Technical assumptions

The hackathon demo runs locally on Python 3.12.

The model artifact is trained before the demo and loaded by the service.

SQLite is sufficient for a single-team prototype audit trail. Production would need controlled identities, permissions, retention, and backups.

The Streamlit login and Maintainer/Operator roles are demo controls, not enterprise identity or authorization.

The core risk, evidence, recommendation, decision, and verification workflow does not depend on network access, an LLM key, EC2, Docker, or Ignition.

Ask AI is optional. It requires VW LLM gateway credentials and corporate network access, and it remains unavailable when those dependencies fail.

The assistant receives only the selected asset and portfolio context assembled by the application. It has no file, database, equipment, decision, or control tool.

The live-data feature is a reversible synthetic replay that updates the workbook. It is not a plant, PLC, SCADA, historian, or CMMS connection.

Credentials must be stored only in an ignored local .env file. They must not appear in a file named env, source code, logs, screenshots, Git history, or the submission ZIP.

Known limitations

Synthetic rather than field data.

Only three weekly snapshots.

No confirmed future failure event, time-to-failure label, or censored survival history.

No OEM limits or engineering envelopes.

No intervention-cost optimization.

No live historian or CMMS connector.

Local demo authentication rather than enterprise identity and role provisioning.

Local SQLite rather than a governed multi-user audit database.

Optional Ask AI availability depends on the VW LLM gateway, credentials, and network.

The LLM summarizes supplied evidence but does not independently validate the analytical result.

No formal probability calibration or production drift monitoring.

The feedback loop is a prototype recommendation-memory/governance pattern; substantial verified history is needed before outcome-based model retraining is defensible.

Claims we can safely make

The complete signal-to-decision workflow works for all 45 supplied assets.

Every alert is traceable to operational fields and derived calculations.

The auxiliary XGBoost model excludes its target and identifiers and is evaluated on unseen assets.

The core ranking does not depend on seeded asset IDs, hidden answers, or the presence of ScenarioFlag at judging.

The system distinguishes technical risk from business impact.

Missing and malformed data are surfaced.

The human remains responsible for the decision and verified outcome.

The optional assistant answers questions from bounded synthetic evidence and cannot control equipment.

The synthetic replay demonstrates rescoring as measurements change, not live plant integration.

Claims we must not make

Production-validated failure prediction.

Exact remaining useful life.

Manufacturer-certified thresholds.

Guaranteed failure prevention or downtime savings.

Autonomous maintenance or shutdown control.

Learning from real production outcomes.

A production-ready identity, cybersecurity, secret-management, or deployment design.

A live PLC, historian, SCADA, MES, or CMMS connection.

An autonomous or multi-agent maintenance-control system.