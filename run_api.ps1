$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    throw "Run .\setup.ps1 first."
}

$env:PYTHONPATH = "$PWD\src"
& ".venv\Scripts\python.exe" -m uvicorn api.main:app --host 127.0.0.1 --port 8000

