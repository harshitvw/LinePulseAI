# LinePulse AI — Complete Project Guide

This guide is written for a teammate who has never seen the code. Read it once from top to bottom and you will know what the project does, where everything lives, how to run it, what the model actually learned, and how to explain its limitations honestly.

## 1. The problem in one sentence

Maintenance teams cannot manually investigate every critical asset quickly enough, so LinePulse AI turns six disconnected operational tables into an explainable, prioritized queue of Class A assets while leaving the final decision with the human expert.

## 2. What the finished prototype does

The prototype:

1. reads the official workbook only;
2. validates and joins all six operational sheets;
3. scores all 45 Class A assets;
4. ranks them using both technical degradation risk and business impact;
5. displays genuinely colored red, amber, and green cards;
6. estimates a warning-boundary planning horizon;
7. explains the most important evidence and likely failure-mode hypothesis;
8. suggests a safe maintenance action and planning window;
9. lowers confidence when data is missing or inconsistent;
10. records the Equipment Owner's approve, modify, or reject decision;
11. records the eventual outcome for an auditable feedback loop; and
12. never sends an equipment command or creates an automatic shutdown.

The prototype intentionally does **not** require OpenAI, an LLM, EC2, Docker, Ignition, or a production database. Those can be later integrations, but they do not improve the central analytical proof required for this demo.

## 3. What data is used

Only `data/source/Synthetic_Dataset.xlsx`, copied from the organizer-provided `Synthetic_Dataset 1 1.xlsx`, enters the analytical pipeline. It contains 45 Class A assets observed over three weekly snapshots.

The authority order is explicit:

1. `Participant_Guide.docx`, `Synthetic_Dataset_Report.docx`, and `Synthetic_Dataset.xlsx` are the source of truth.
2. Only the LinePulse AI identity and promised human-control principle are carried forward from the team's earlier concept.
3. Any older 20-asset mock, previous dataset, or earlier implementation detail is superseded.

The six operational sheets are:

| Sheet | Rows | Role in the prototype |
|---|---:|---|
| `Asset_Master` | 45 | Asset identity, type, line, maintenance interval, lifecycle, and business impact |
| `Usage_Log` | 135 | Cycles, duty, start/stop stress, throughput, and cumulative usage |
| `Sensor_Readings` | 133 | Temperature, vibration, current, pressure, and cycle time; two asset-weeks are intentionally absent |
| `Maintenance_History` | 103 | Preventive/corrective/inspection work, historical failure mode, downtime, parts, and notes |
| `Production_Context` | 45 | Shift-level volume, overtime, model mix, and demand by line and week |
| `Quality_Linkage` | 135 | Defects, scrap, rework, and quality context by asset and week |

The application reads the six sheets by **schema**, not by worksheet order. It does not read the hidden facilitator `ANSWER_KEY`. It ignores `ReadingID`, `UsageID`, `QualityID`, `ContextID`, `WorkOrderID`, and asset-name patterns as predictive features. That is why shuffled or replaced record IDs do not change the logic.

`Sensor_Readings.ScenarioFlag` is a visible synthetic hint supplied by the organizers. It is used only as the target for the **auxiliary** model, teaching that detector what the generator considered a degradation scenario. It is removed from the input feature matrix before fitting and is not used at inference. Core RAG status and planning horizon come from measurements, trends, peer boundaries, maintenance, lifecycle, quality, and impact and continue if the hint is absent. The application does not expose seeded scenario IDs or use that field as a scoring shortcut.

## 4. The mental model

Think of LinePulse AI as five layers:

| Layer | Plain-language question | Main implementation location |
|---|---|---|
| Data contract | Are the required tables and columns present and joinable? | `src/linepulse/data.py` |
| Feature and model layer | Does this week's combined behavior resemble a seeded degradation pattern? | `src/linepulse/analytics.py`, `scripts/train_model.py` |
| Evidence layer | Which values or trends are unusual for comparable assets? | `src/linepulse/risk.py` |
| Decision layer | Which asset deserves attention first, why, and what should a person do? | `src/linepulse/service.py` |
| Delivery layer | How do people and other software use the result? | `dashboard/app.py`, `api/main.py` |

The UI is not the intelligence. It is the way the maintenance team sees the model, evidence, uncertainty, and suggested action. The backend is not a second model. It exposes the same central service consistently to the UI and API consumers.

### Plain-language glossary

| Term | Meaning here |
|---|---|
| Frontend | The Streamlit browser screen a maintainer clicks |
| Backend | The optional FastAPI HTTP adapter other software can call |
| Core service | The shared Python logic used by both frontend and backend |
| Model artifact | The saved, trained pipeline in `artifacts/degradation_model.joblib` |
| RAG | Red, amber, or green attention state |
| Degradation likelihood | Similarity to the workbook's seeded scenario pattern; display-only, not a failure probability |
| Technical risk | Transparent operational evidence score, independent of `ScenarioFlag` |
| Business impact | Consequence/criticality context from the official asset data |
| Attention priority | Sorting score combining technical risk and business consequence |
| Peer warning boundary | Monitoring boundary learned from comparable synthetic observations; not an OEM safety limit |
| Planning horizon | Estimated days until a warning boundary or due point if the recent pattern continues |
| Confidence | Completeness/trust of the available evidence, not the probability of correctness |
| Evidence Passport | Trace from an alert back to source sheet, field, value, trend, and boundary |
| Human gate | Required approve/modify/reject decision by the Equipment Owner |

## 5. Data flow, step by step

### Step 1 — Validate

The loader checks required sheets, required columns, date types, unique keys where appropriate, and foreign-key relationships. It deliberately detects the workbook's known quality cases:

- two missing sensor asset-weeks;
- one maintenance row whose `AssetID` is not in `Asset_Master`; and
- one duplicate `WorkOrderID`.

These issues are reported. They are never deleted silently and never converted into a healthy signal.

### Step 2 — Aggregate and join

The pipeline uses:

- `AssetID` as the asset hub;
- `AssetID + WeekStarting` for sensor, usage, and quality data;
- `Line + WeekStarting` after aggregating the three production shifts; and
- `AssetID` plus event date for maintenance history.

The joined table has one row per asset-week. Production context is aggregated before joining so three shifts do not accidentally triple the asset-week rows.

### Step 3 — Build features

Training and inference use operational measurements and derived features such as:

- sensor level and recent slope;
- cycles, duty, starts/stops, and throughput;
- maintenance recency relative to the scheduled interval, calculated as of each row's `WeekStarting` date;
- lifecycle consumption relative to rated cycle life;
- defects, scrap, and rework;
- planned volume, actual volume, line demand, and overtime; and
- recent corrective-maintenance frequency and downtime.

The predictive matrix is deliberately numeric. Asset type is used outside the model for peer baselines, while line and names remain context. Missing numeric values are imputed inside the trained pipeline, and a separate data-confidence score tells the user that imputation occurred.

### Step 4 — Train the auxiliary XGBoost detector correctly

The target is whether the workbook's synthetic `ScenarioFlag` hint is populated. The target column is removed before training. Identifiers and facilitator-only information are excluded.

Validation is grouped by `AssetID`. An asset is entirely in either training or validation, not both. This is stricter and more realistic than randomly splitting the 135 weekly rows, which would leak the same machine's behavior into both sides.

The model output is a **seeded degradation likelihood**. It is not a probability of an actual field failure, because the workbook contains no confirmed future-failure label or failure timestamp. It is shown only as corroborating context and has 0% weight in technical risk, status, and planning horizon. If the hint column is absent or unusable, the pipeline has a label-free peer-deviation fallback and the main evidence/horizon path remains operational.

### Step 5 — Calculate transparent evidence

For every major signal, LinePulse AI compares the latest value and three-week direction with comparable records. Its warning boundaries come from robust peer statistics by asset type, with a global fallback when the peer group is too small.

The evidence passport includes:

- source sheet and field;
- latest observed value;
- unit;
- change over the observed period;
- peer warning boundary;
- whether a high or low value is unfavorable; and
- contribution to the technical risk.

These are project-derived monitoring boundaries. They are never called OEM limits or certified safety thresholds.

### Step 6 — Estimate a planning horizon

When a signal is moving toward its peer-derived warning boundary, the pipeline extrapolates the recent linear trend:

`days to boundary = distance from boundary / unfavorable change per day`

The result is bounded and combined with maintenance-due and lifecycle horizons. It answers: “How urgently should we plan a review if the recent pattern continues?”

It does **not** answer: “Exactly how many days until physical failure?” The official workbook has no future failure time, so claiming true remaining useful life would be scientifically unsupported.

### Step 7 — Separate risk from impact

The interface shows:

- **Technical risk:** transparent condition, use, maintenance, lifecycle, quality, history, and production evidence.
- **Auxiliary degradation likelihood:** a separate model corroboration signal with 0% RAG weight.
- **Business impact:** the official `BusinessImpactScore`, with production context.
- **Attention priority:** a controlled combination used to sort the queue.

This separation is important. A moderate technical concern on a line-critical, long-lead asset may deserve attention before a slightly riskier but easier-to-replace asset.

### Step 8 — Explain and recommend

The highest-contributing **sensor** evidence drives a cautious failure-mode hypothesis such as overheating, vibration/mechanical wear, excess current/motor load, pressure loss, or cycle-time drift. Usage, maintenance, lifecycle, production, and quality affect urgency and context but do not pretend to diagnose a physical failure mode.

Recommendations are intentionally bounded: continue monitoring, inspect, reduce stress until inspection, plan a swap, or request a shutdown review. The app does not automatically shut down an asset.

### Step 9 — Human decision and outcome

An Equipment Owner may approve, modify, or reject the suggestion. The choice is written to local SQLite for audit. A later verified outcome can mark the case resolved, partially resolved, or unresolved.

The display may then show a **workflow state** of green after a verified resolution. That green means the intervention case is closed by a human; it does not erase the original sensor evidence or pretend the historical measurement changed. The original score, recommendation, decision, and outcome remain in the audit trail.

## 6. Red, amber, and green

The cards use actual background colors, supported by text and icons so color is not the only cue.

| State | Planning meaning | Typical horizon | Human expectation |
|---|---|---:|---|
| Red | Review immediately | 0–10 days | Confirm evidence and decide before the next suitable stop |
| Amber | Plan an inspection | 11–30 days | Add to the near-term maintenance plan |
| Green | Continue monitoring | More than 30 days | No immediate intervention; retain monitoring |

Status uses several pieces of evidence, not a single hardcoded sensor cutoff. A high technical-risk score, an approaching trend boundary, a due-maintenance horizon, or a material data-quality concern can affect the state. The `?` on every card explains the actual reason and the estimated days for that asset.

If a required sensor record is missing, the asset receives a visible data-quality warning and lower confidence. It cannot become green merely because the risky value is absent.

## 7. Every important folder

```text
LinePulse_AI/
├── api/                         FastAPI backend entry point
├── artifacts/                   Generated trained model and model metadata
├── dashboard/                   Streamlit user interface
├── data/source/                 Official workbook; never hand-edited by the app
├── docs/                        Explanations and presentation material
├── reference/                   Official guide and dataset report
├── runtime/                     Local SQLite decisions/outcomes; created at runtime
├── scripts/                     Training, smoke-test, and preflight commands
├── src/linepulse/               Shared Python application and analytics code
├── tests/                       Automated checks
├── pyproject.toml               Installable package definition
├── requirements.txt             Python dependencies
└── README.md                    Quick start
```

Generated files are separated from source data:

- Deleting `artifacts/` is safe if you retrain.
- Deleting `runtime/linepulse.db` removes local demo decisions and outcomes, but not the official workbook or trained source code.
- The application never writes into `data/source/Synthetic_Dataset.xlsx`.

### How to show the database

The database is created at `runtime/linepulse.db` when the service starts. It contains two application tables:

- `decisions`: immutable model snapshot, evidence, recommendation, owner choice, rationale, and selected action;
- `outcomes`: later human-verified result linked to the decision.

The easiest visual view is the dashboard's **Human review** workspace or `GET /api/v1/cases` in Swagger. To inspect the physical SQLite file without changing it, install any trusted SQLite viewer in VS Code and open `runtime/linepulse.db`.

You can also print the two tables from PowerShell:

```powershell
@'
import sqlite3
db = sqlite3.connect(r"runtime\linepulse.db")
for table in ("decisions", "outcomes"):
    count = db.execute("SELECT count(*) FROM " + table).fetchone()[0]
    print(table, count)
db.close()
'@ | .\.venv\Scripts\python.exe -
```

This reads only the user-created audit database. It does not inspect or modify equipment.

## 8. Setup from zero on Windows

### Prerequisites

- Windows 10 or 11
- VS Code
- Python 3.12
- PowerShell

Check the interpreters:

```powershell
py -0p
py -3.12 --version
```

### Simplest setup

From the extracted project folder:

```powershell
cd C:\path\to\LinePulse_AI
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
.\run_app.ps1
```

Use `Set-ExecutionPolicy` only if your organization allows a process-scoped override. `setup.ps1` creates the Python 3.12 environment, installs the package, trains the model, and runs the tests. `run_app.ps1` launches the complete dashboard at <http://localhost:8501>.

If group policy blocks scripts, use the manual commands below. They call the virtual-environment interpreter directly and require no activation.

### Manual setup

From the folder that contains `LinePulse_AI`:

```powershell
cd .\LinePulse_AI
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
$env:PYTHONPATH = "$PWD\src"
```

You do not need to run `Activate.ps1`. Calling `.venv\Scripts\python.exe` directly avoids corporate execution-policy problems.

### Train the model

```powershell
.\.venv\Scripts\python.exe scripts\train_model.py
```

Training creates `artifacts/degradation_model.joblib` and prints the grouped-validation summary. Its metadata includes a fingerprint of the official source and feature contract. The service loads a compatible artifact rather than retraining on every page refresh, but rejects/rebuilds a stale artifact when the workbook or analytical contract changes.

### Verify the project

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\smoke_test.py
```

Do not present until both commands finish successfully.

### Run the dashboard

The dashboard calls the shared `LinePulseService` directly, so this is the only process needed for the live walkthrough:

```powershell
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe -m streamlit run dashboard\app.py
```

Leave the terminal running and open <http://localhost:8501>.

### Optionally run the API

The API is an integration adapter, not a dashboard dependency. To show it, open a second terminal:

```powershell
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/docs> to inspect the API.

### Stop the app

Click each server terminal and press `Ctrl+C`. This stops only the local process; it does not delete the model, source data, or recorded decisions.

## 9. How frontend, backend, model, and database fit together

| Part | Technology | Responsibility |
|---|---|---|
| Frontend | Streamlit + Plotly/CSS | Colored cards, ranked queue, evidence drill-down, what-if view, human-decision forms; calls shared service directly |
| Backend | FastAPI | Optional stable integration endpoints for health, portfolio, asset details, decisions, outcomes, and audit records |
| Analytics | pandas, NumPy, scikit-learn-compatible preprocessing, XGBoost | Data contract, features, trained seeded-degradation detector, transparent risk and horizon logic |
| Database | SQLite | User-created decisions and verified outcomes only |
| Source data | Excel | Organizer-provided operational evidence only |

The database is not used to invent training samples on first launch. It stores the user's actions and verified outcomes. The prototype uses verified outcomes as recommendation memory for comparable cases. A future governed retraining workflow may incorporate them after enough genuine, reviewed examples exist; the model is never silently retrained from an approval click.

## 10. The main API surfaces

Use the generated Swagger page at `/docs` as the source of truth. The important concepts are:

| Purpose | Typical method/path |
|---|---|
| Liveness | `GET /api/v1/health` |
| Readiness/model state | `GET /api/v1/readiness` |
| Ranked portfolio | `GET /api/v1/portfolio` |
| One asset and its evidence | `GET /api/v1/assets/{asset_id}` |
| Record Equipment Owner decision | `POST /api/v1/decisions` |
| Record verified maintenance outcome | `POST /api/v1/cases/{case_id}/outcome` |
| View audit trail | `GET /api/v1/cases` |
| Non-persistent what-if | `POST /api/v1/assets/{asset_id}/what-if` |
| Clear user-created demo memory | `POST /api/v1/demo/reset` |

The exact schemas appear interactively in Swagger. None of the endpoints can write to a PLC, robot, machine, or safety system.

## 11. How to explain the model without overclaiming

Use this wording:

> “We train an auxiliary XGBoost detector on whether the organizer's synthetic scenario hint is populated. We exclude that target, all identifiers, and facilitator-only information from model inputs. We validate on assets the model did not see during training. Its likelihood is display-only corroboration with zero RAG weight. Core RAG and horizon remain measurement- and trend-driven even without the hint. The remaining-days display comes from recent trends approaching peer-derived warning boundaries, so we call it a planning horizon—not true RUL or a certified failure date.”

Avoid these claims:

- “It predicts exact machine failure.”
- “It is production validated.”
- “The warning lines are manufacturer safety limits.”
- “It has learned from years of real failures.”
- “AI automatically decides shutdowns.”
- “A green status guarantees no failure.”

## 12. What is trained and what is rules-based

| Output | How it is produced |
|---|---|
| Seeded degradation likelihood | Auxiliary trained XGBoost classifier, or explicitly disclosed analytical fallback |
| Sensor level/trend evidence | Transparent peer-relative calculations |
| Planning horizon | Trend extrapolation to a data-derived warning boundary plus maintenance/lifecycle context |
| Likely failure mode | Dominant sensor-evidence-to-hypothesis mapping |
| Recommended action | Guardrailed decision-support policy based on state and dominant evidence |
| Attention priority | Explicit fusion of technical risk and business impact |
| Confidence | Sensor completeness, preventive-history availability, and data-quality checks |
| Human outcome state | Equipment Owner input stored in SQLite |

This hybrid design is deliberate. XGBoost finds multivariate interactions; the transparent layer lets a maintainer challenge the result.

## 13. The data-quality contract

The system treats quality as part of the result, not as a preprocessing footnote.

| Issue | Detection | Behavior |
|---|---|---|
| Missing sensor week | Compare expected asset-week grid with observed readings | Flag the asset, reduce confidence, avoid silent green |
| Duplicate work order | Duplicate `WorkOrderID` check | Keep an auditable warning; deduplicate only for aggregate calculations |
| Orphan maintenance asset | Foreign-key check against `Asset_Master` | Exclude from asset aggregation and report it |
| Missing numeric value | Validation and model-pipeline imputation | Lower confidence and show affected source |
| Unknown category | Model encoder/fallback | Handle without using ID-specific rules |
| Changed record IDs | IDs excluded from features | Prediction remains based on operational values |

## 14. A winning two-minute technical explanation

> “The problem is not simply classification; it is deciding what deserves scarce maintenance attention. We built one asset-week evidence layer from six official sheets. An auxiliary XGBoost detector identifies multivariate seeded-degradation patterns and is validated by holding out whole assets, but has zero RAG weight. The primary, judge-robust logic uses peer-relative levels and three-week slopes to create a traceable Evidence Passport and planning horizon. We then keep technical risk separate from business impact before ranking all 45 Class A assets. Missing data reduces confidence rather than becoming green. Finally, the human owner approves, modifies, or rejects the recommendation; maintenance happens externally; a human verifies the outcome; and the original evidence stays auditable. The application cannot control equipment.”

## 15. Likely judge questions and prepared answers

### “Is this really predicting failure?”

It detects patterns matching the synthetic generator's degradation cases and estimates when recent trends may reach project-derived warning boundaries. The official data has no confirmed future failure timestamp, so we deliberately do not call the horizon true RUL.

### “Why auxiliary XGBoost?”

It handles nonlinear interactions among sensor, usage, maintenance, production, and quality variables well on tabular data. It also works with a modest dataset and supports feature-attribution methods. Because `ScenarioFlag` is only a hint, the model is display-only corroboration; the RAG/horizon engine remains transparent and works without it.

### “How did you avoid leakage?”

We remove `ScenarioFlag` from inputs, exclude record and asset identifiers, exclude the hidden answer key, and validate with groups defined by `AssetID`, so all weeks for a validation asset remain unseen during training.

### “What does 8 days remaining mean?”

It means the recent unfavorable trend would reach a peer-derived warning boundary in roughly eight days if it continues. It is a planning horizon, not a promised failure date.

### “Where do the thresholds come from?”

They are robust peer/type statistics computed from the official workbook. They are explicitly labeled project-derived warning boundaries, not OEM or safety thresholds. A production rollout would replace or augment them with engineer-approved operating envelopes.

### “If a value crosses the boundary, does that mean the machine will fail?”

No. Crossing this monitoring boundary means the evidence deserves faster human review; it is not proof of physical failure. In production, certified machine/PLC safety limits would stay independent and authoritative. LinePulse would add an earlier, softer trend-warning layer and could never override the safety system.

### “What if a sensor value is missing?”

The model pipeline can impute a value so the service remains available, but the asset's confidence falls, the missing source is shown, and the asset is prevented from silently appearing healthy.

### “Why combine business impact with risk?”

The team has limited capacity. Technical risk tells us what may be degrading; business impact tells us the consequence of delay. We display both so the priority remains challengeable.

### “Can it shut down a line?”

No. There is no equipment-write tool or control endpoint. It recommends a review; the Equipment Owner decides.

### “Does it use an LLM?”

No LLM is needed for the core proof. Explanations are generated from traceable evidence so the demo remains deterministic, inexpensive, and auditable. An LLM could later improve conversational access without becoming the risk engine.

### “Why no cloud deployment?”

The prototype runs locally to reduce operational complexity during the hackathon. The API/UI separation makes later EC2 deployment straightforward, but deployment is not allowed to distract from analytics, traceability, and the live demo.

### “How does it learn from decisions?”

The full path is AI recommendation → Equipment Owner approve/modify/reject → maintenance in the existing process → human-verified outcome → recommendation memory. Decisions and outcomes are stored separately in SQLite. The prototype does not falsely retrain on one click or treat an approval as proof of failure. Only verified outcomes are eligible for later governed batch retraining.

### “Will it work if the judges change asset IDs?”

Yes. IDs are join keys only and are excluded from the model and threshold rules. The automated tests include an identifier-renaming/generalization check.

### “What would productionization require?”

Historian connectors, engineer-approved limits, confirmed failure and intervention labels, temporal validation, calibration monitoring, access control, model registry/versioning, drift monitoring, and a formal safety and change-management review.

## 16. Troubleshooting

### `.venv\Scripts\python.exe` is not recognized

The environment was not created in the current folder. Run:

```powershell
Get-Location
Get-ChildItem
py -3.12 -m venv .venv
Test-Path .\.venv\Scripts\python.exe
```

The final line must print `True`.

### PowerShell blocks `Activate.ps1`

Do not activate. Run the environment's interpreter directly, as every command in this guide does.

### `ModuleNotFoundError: linepulse` or `pandas`

```powershell
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe -m pip install -e .
```

Make sure `Get-Location` is the project root.

### Model artifact is missing

```powershell
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe scripts\train_model.py
```

Then restart the dashboard and optional API.

### The optional API is unavailable

The dashboard does not depend on the API. For an API demonstration, run `.\run_api.ps1` and check <http://127.0.0.1:8000/api/v1/health>.

### The page looks blurry

Reset browser zoom with `Ctrl+0`, set Windows display scaling to the recommended value, and present at 100% or 110% browser zoom. Streamlit reruns do not improve blur caused by browser or Windows scaling.

### A port is already in use

Use another port, for example:

```powershell
.\.venv\Scripts\python.exe -m streamlit run dashboard\app.py --server.port 8502
```

### Decisions from rehearsal remain visible

Use the application's **Reset demo memory** control or `POST /api/v1/demo/reset`. If you intentionally need a manual clean slate, stop the app/API, make a backup of `runtime/linepulse.db`, then remove only that file and restart. Never delete the source workbook.

## 17. Pre-demo checklist

- [ ] Python 3.12 environment installs cleanly.
- [ ] Training completes and saves the model artifact.
- [ ] All automated tests pass.
- [ ] Smoke test passes.
- [ ] Backend health and readiness endpoints are green.
- [ ] Dashboard shows all 45 assets and both high- and low-attention examples.
- [ ] Red, amber, and green are visible as real card colors.
- [ ] The `?` hover explains classification and days remaining.
- [ ] One missing-data or borderline case is ready to show.
- [ ] An Equipment Owner decision can be recorded.
- [ ] The presenter uses “planning horizon,” “seeded degradation,” and “project-derived boundary.”
- [ ] No one claims production validation, exact failure prediction, or automatic equipment action.

For the exact presentation flow, use [DEMO_WALKTHROUGH.md](DEMO_WALKTHROUGH.md). For model limitations, use [MODEL_CARD.md](MODEL_CARD.md).
