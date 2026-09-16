$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    throw "Run .\setup.ps1 first."
}

$env:PYTHONPATH = "$PWD\src"
& ".venv\Scripts\python.exe" -m streamlit run dashboard\app.py

