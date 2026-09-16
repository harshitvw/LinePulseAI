# LinePulse AI

LinePulse AI is a human-in-the-loop maintenance decision-support prototype for Class A assembly-line assets. It turns the official hackathon workbook into a ranked attention queue, explains the evidence behind each alert, estimates a **planning horizon**, recommends a safe next action, and records the Equipment Owner's decision. It never writes to equipment or automatically shuts anything down.

The analytical source of truth is the three files supplied in the official organizer pack:

- `Synthetic_Dataset.xlsx` for model training and runtime analysis
- `Participant_Guide.docx` for the challenge and judging requirements
- `Synthetic_Dataset_Report.docx` for the dataset semantics and known data-quality cases

The LinePulse AI name and human-control principle continue the team's submitted concept, but the official guide, report, and workbook override any older mock scope or sample values. No earlier dataset, real factory data, hidden answer key, asset-ID rule, OpenAI key, Ignition connection, Docker service, or EC2 instance is required.

## What makes this prototype different

- **Evidence Passport:** every alert shows the measured value, recent change, peer-derived warning boundary, source sheet, and confidence.
- **Two-layer decision:** technical degradation risk is shown separately from business impact, then combined into an attention priority.
- **Honest prediction:** an auxiliary XGBoost model learns the workbook's seeded degradation pattern as display-only corroboration; it has 0% RAG weight. Status remains signal/trend driven, and the displayed days are a planning horizon—not claimed remaining useful life.
- **Data-trust gate:** missing, duplicate, or orphaned records reduce confidence and are surfaced. Missing data never silently means healthy.
- **Human authority:** the maintenance team may approve, modify, or reject a recommendation. No equipment-control function exists.

## Run it on Windows PowerShell

Use Python 3.12. The simplest path (when a process-scoped script-policy override is permitted) is:

```powershell
cd C:\path\to\LinePulse_AI
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
.\run_app.ps1
```

Open <http://localhost:8501>. `setup.ps1` creates the environment, installs dependencies, trains the model, and runs the tests. `run_app.ps1` starts the complete dashboard through the shared service layer; the separate API is optional.

If corporate policy blocks PowerShell scripts, use these manual commands. They do not require virtual-environment activation:

```powershell
cd C:\path\to\LinePulse_AI

py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .

$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe scripts\train_model.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\smoke_test.py
```

Start the dashboard:

```powershell
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe -m streamlit run dashboard\app.py
```

The dashboard uses the same service layer as the API and does not need the API process. For an integration/API demonstration, open a second terminal and run:

```powershell
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Then open:

- Dashboard: <http://localhost:8501>
- API health: <http://127.0.0.1:8000/api/v1/health>
- API documentation: <http://127.0.0.1:8000/docs>

If port 8501 is already used, run the frontend with `--server.port 8502` and open <http://127.0.0.1:8502>.

## Five-minute explanation

1. The official workbook contains 45 critical assets and three weekly observations across six operational sheets.
2. The data pipeline joins sensor, usage, maintenance, production, quality, and asset-impact context without depending on particular asset IDs.
3. An auxiliary trained XGBoost classifier estimates how strongly the current evidence resembles the workbook's seeded degradation cases. `ScenarioFlag` is used only as the training target and is never an input feature. The model is display-only corroboration with 0% RAG weight, so core status/horizon logic works without it.
4. Transparent peer-relative level and trend calculations estimate *why* an asset is concerning and how soon a data-derived warning boundary may be reached.
5. Technical risk and business impact are kept visible and combined into an attention priority, so the maintenance team knows what to examine first.
6. Red, amber, and green are real card colors. Hover over each `?` to see the classification reason and estimated days remaining.
7. The Equipment Owner makes the decision. The system records it for audit and future learning but has no equipment-write capability.

## Project map

| Location | Purpose |
|---|---|
| `data/source/Synthetic_Dataset.xlsx` | Unmodified official model/data source |
| `src/linepulse/` | Data validation, feature engineering, model inference, scoring, explanations, and decision logic |
| `scripts/train_model.py` | Trains and saves the XGBoost degradation detector |
| `artifacts/degradation_model.joblib` | Generated model bundle and metadata; reproducible from the official workbook |
| `api/main.py` | Optional FastAPI integration adapter |
| `dashboard/app.py` | Streamlit frontend using the same core service directly |
| `runtime/linepulse.db` | Local SQLite audit trail of human decisions/outcomes; created at runtime |
| `tests/` | Unit, API, data-quality, and generalization checks |
| `docs/` | Beginner guide, architecture, assumptions, demo script, model card, and data dictionary |
| `reference/` | Organizer guide and dataset report, kept for traceability |

Start with [docs/PROJECT_GUIDE.md](docs/PROJECT_GUIDE.md) if you are new to the project. Use [docs/DEMO_WALKTHROUGH.md](docs/DEMO_WALKTHROUGH.md) before presenting to judges.

## Safety and scope

LinePulse AI is a hackathon prototype trained on 100% synthetic data. Its boundaries are **project-derived warning boundaries**, not OEM safety limits. Its planning horizon is not validated remaining useful life. It supports inspection and planning; it must not be used by itself for a shutdown or maintenance decision.
