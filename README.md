LinePulse AI

LinePulse AI is a human-controlled maintenance decision workspace for Class A assembly-line assets. It turns the organizer-provided synthetic workbook into a ranked attention queue, explains the evidence behind each alert, estimates a planning horizon, recommends a safe next action, and records the maintainer's decision and the operator's verified outcome.

The prototype never writes to equipment, creates an automatic work order, or issues a shutdown command.

What works today

Scores and prioritizes all 45 supplied Class A assets.

Shows red, amber, and green attention states with a traceable reason and planning horizon.

Separates technical condition risk from business impact.

Provides an Evidence Passport with source field, current value, trend, peer warning boundary, and data-quality limitations.

Suggests a failure-mode hypothesis and maintenance action.

Supports Maintainer approval, modification, or rejection with mandatory rationale.

Supports Operator verification as resolved, partial, or unresolved.

Preserves the original model assessment when a verified outcome changes the workflow display.

Stores decisions and outcomes in a local SQLite audit trail.

Provides a reversible synthetic live-data replay and a non-persistent what-if view.

Provides an optional VW LLM assistant that answers questions using only the selected asset and visible portfolio context.

Exposes the same service through an optional FastAPI adapter.

Data and modelling position

The analytical source of truth is the organizer pack:

data/source/Synthetic_Dataset.xlsx

reference/Participant_Guide.docx

reference/Synthetic_Dataset_Report.docx

The workbook contains 45 Class A assets across six linked operational sheets and three weekly snapshots. It is 100% synthetic.

The trained XGBoost classifier is an auxiliary seeded-degradation detector. It uses the supplied ScenarioFlag only to construct its training target, never as an input feature. Its output is display-only corroboration with 0% weight in red, amber, green, technical risk, or planning horizon.

The operational assessment comes from transparent signal levels, recent trends, peer-derived warning boundaries, maintenance urgency, lifecycle usage, quality context, and business impact. The displayed days are a planning horizon, not certified remaining useful life or a guaranteed failure date.

User workflow

Home shows the portfolio, current priorities, workflow counts, and recent decisions.

Priorities ranks all Class A assets by current attention priority.

Asset review shows one asset's condition, Evidence Passport, recommendation, and Maintainer decision gate.

Work verification lets an Operator record the technician-confirmed result.

Ask AI explains the selected asset in plain language from bounded dashboard context.

Maintainers can record approve, modify, or reject decisions. Operators can record verified outcomes. Both roles can inspect the audit history. Neither role can control equipment through LinePulse AI.

Quick start on Windows

Use Python 3.12.

cd C:\path\to\LinePulseAI-main
Get-ChildItem -Recurse | Unblock-File
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
.\run_app.ps1

Open http://localhost:8501.

If corporate policy blocks PowerShell scripts, run:

cd C:\path\to\LinePulseAI-main
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .

$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe scripts\train_model.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\smoke_test.py
.\.venv\Scripts\python.exe -m streamlit run dashboard\app.py

The Streamlit application calls the shared Python service directly. FastAPI is optional.

Optional API

Start the API in a second terminal:

$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000

Health: http://127.0.0.1:8000/api/v1/health

Readiness: http://127.0.0.1:8000/api/v1/readiness

OpenAPI: http://127.0.0.1:8000/docs

The API has no equipment-control endpoint.

Optional Ask AI configuration

The core risk-to-recommendation workflow works without an LLM. To enable the optional conversational assistant, create a local .env file:

VW_LLM_CLIENT_ID=your_cloudidp_client_id
VW_LLM_CLIENT_SECRET=your_cloudidp_client_secret
VW_LLM_API_KEY=your_vw_virtual_key
OPENAI_MODEL=gpt-4o

Never put live credentials in a file named env, source code, screenshots, documentation, Git history, or the submission ZIP. Rotate a key immediately if it has been shared or packaged.

The assistant receives only a small portfolio summary and the selected asset's current evidence. It cannot access local files, query equipment, change decisions, or issue commands. See docs/ASK_AI.md.

Synthetic live replay

Start the dashboard, then run this in a second terminal:

.\.venv\Scripts\python.exe scripts\live_demo_replay.py start --steps 6 --interval 5

The replay adds increasing synthetic temperature, vibration, current, cycle-time, and pressure conditions to five assets. It is not a plant or historian connection. Restore the original workbook after the demo:

.\.venv\Scripts\python.exe scripts\live_demo_replay.py cleanup

See docs/LIVE_DATA_SIMULATOR.md.

Project map

Location

Purpose

dashboard/app.py

Streamlit UI, login, role-aware workflow, and Ask AI workspace

src/linepulse/data.py

Workbook validation, joins, data-quality checks, and feature table

src/linepulse/analytics.py

XGBoost training, validation, model metadata, and artifact loading

src/linepulse/risk.py

Transparent risk, impact, horizon, evidence, and recommendation logic

src/linepulse/service.py

Shared application service and human workflow rules

src/linepulse/openai_assistant.py

Bounded VW LLM gateway client and assistant context

src/linepulse/repository.py

SQLite decision and outcome audit trail

api/main.py

Optional FastAPI integration adapter

scripts/live_demo_replay.py

Reversible synthetic signal replay

scripts/demo_preflight.py

Submission and demo readiness checks

tests/

Core, generalization, API, and assistant contract tests

docs/

Architecture, assumptions, model card, data dictionary, guides, and demo script

Documentation

Start with docs/PROJECT_GUIDE.md for the full technical and presentation guide.

Use docs/DEMO_WALKTHROUGH.md to record or present the demo.

Use docs/ARCHITECTURE.md for system boundaries and data flow.

Use docs/MODEL_CARD.md for model claims and limitations.

Use docs/ASSUMPTIONS.md for safe claims.

Use docs/ASK_AI.md for VW LLM setup and safety.

Safe claims

LinePulse AI demonstrates an end-to-end, evidence-grounded maintenance decision workflow on the supplied synthetic data. It does not demonstrate production failure accuracy, certified safety limits, exact remaining useful life, guaranteed downtime reduction, or autonomous maintenance.